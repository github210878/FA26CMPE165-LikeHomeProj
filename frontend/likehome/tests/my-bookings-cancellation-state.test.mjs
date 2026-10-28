import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { afterEach, beforeEach, test } from "node:test";
import { cloneElement, createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

import { ApiError } from "../lib/api.ts";
import * as bookings from "../lib/bookings.ts";
import * as cancellation from "../lib/booking-cancellation.ts";
import * as payment from "../lib/payment.ts";
import { clearAccessToken, saveAccessToken } from "../lib/token-storage.ts";

const originalFetch = globalThis.fetch;
const originalWindow = globalThis.window;
const require = createRequire(import.meta.url);
const tick = () => new Promise(setImmediate);
const copy = (value) => structuredClone(value);
beforeEach(() => {
  const entries = new Map();
  globalThis.window = { sessionStorage: {
    getItem: (key) => entries.get(key) ?? null,
    setItem: (key, value) => entries.set(key, value),
    removeItem: (key) => entries.delete(key),
  } };
  saveAccessToken("synthetic-display-test-token");
  globalThis.fetch = async () => { throw new Error("Unexpected request outside the synthetic API"); };
});
afterEach(() => { globalThis.fetch = originalFetch; globalThis.window = originalWindow; });

const original = {
  reservation_id: 12, hotel_name: "Harbor House", room_type_name: "Queen room",
  hotel_address: "123 Harbor Street", hotel_phone: null, hotel_description: "Harbor description",
  room_description: "One queen bed", check_in_date: "2026-11-05", check_out_date: "2026-11-08",
  price_per_night: 47.78, total_price: 150.5, status: "confirmed",
};
const other = { ...original, reservation_id: 13, hotel_name: "Garden Stay", total_price: 240 };
const paid = { payment_id: 19, reservation_id: 12, amount: 162.54, payment_type: "booking", payment_status: "paid" };
const otherPayment = { ...paid, payment_id: 31, reservation_id: 13, amount: 259.2, payment_status: "pending" };
const receipt = { reservation_id: 12, status: "cancelled", booking_payment_id: 19,
  booking_payment_status: "refunded", cancellation_payment_id: 20,
  cancellation_amount: 30.1, cancellation_payment_status: "pending" };
const fee = { payment_id: 20, reservation_id: 12, amount: 30.1, payment_type: "cancellation", payment_status: "pending" };

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function text(node) {
  if (Array.isArray(node)) return node.map(text).join("");
  if (node && typeof node === "object") return text(node.props?.children);
  return node == null || typeof node === "boolean" ? "" : String(node);
}
function nodesIn(tree) {
  const nodes = [];
  function visit(node) {
    if (Array.isArray(node)) return node.forEach(visit);
    if (!node || typeof node !== "object") return;
    nodes.push(node); visit(node.props.children);
  }
  visit(tree);
  return nodes;
}
const buttonsIn = (tree, label) => nodesIn(tree).filter((node) => node.type === "button" && text(node) === label);

// Real API adapters and cancellation helpers execute against an allow-listed,
// in-memory fetch replacement. Nothing can reach a backend or financial provider.
function syntheticApi(options = {}) {
  const requests = [];
  const state = { bookings: copy(options.bookings ?? [original, other]), payments: copy(options.payments ?? [paid, otherPayment]) };
  let listReads = 0, paymentReads = 0;
  const json = (value) => new Response(JSON.stringify(value));
  globalThis.fetch = async (url, init = {}) => {
    const path = new URL(url).pathname;
    requests.push({ path, method: init.method ?? "GET", body: init.body, headers: init.headers });
    assert.equal(init.headers.Authorization, "Bearer synthetic-display-test-token");
    if (path === "/bookings/get-all-bookings" && !init.method) {
      const value = options.readBookings ? await options.readBookings(++listReads, state) : state.bookings;
      return json(value);
    }
    if (path === "/bookings/get-all-payments" && !init.method) {
      const value = options.readPayments ? await options.readPayments(++paymentReads, state) : state.payments;
      return json(value);
    }
    const detail = /^\/bookings\/get-booking-details\/(\d+)$/.exec(path);
    if (detail && !init.method) {
      const id = Number(detail[1]);
      const value = options.readDetail ? await options.readDetail(id, state) : state.bookings.find((b) => b.reservation_id === id);
      return json(value ? { ...value, guest_full_name: null, guest_email: null } : null);
    }
    if (path === "/bookings/cancel-booking/12" && init.method === "POST") {
      assert.equal(init.body, undefined);
      assert.equal(init.headers["Content-Type"], undefined);
      if (options.cancel) return json(await options.cancel(state));
      state.bookings = state.bookings.map((b) => b.reservation_id === 12 ? { ...b, status: "cancelled" } : b);
      state.payments = [...state.payments.map((p) => p.payment_id === 19 ? { ...p, payment_status: receipt.booking_payment_status } : p), copy(fee)];
      return json(receipt);
    }
    assert.fail(`Unexpected request: ${init.method ?? "GET"} ${path}`);
  };
  return { requests, state, writes: () => requests.filter((r) => r.method !== "GET") };
}

// Existing project convention: deterministic hook/effect scheduling followed by
// React host-markup rendering. Exercises actual component handlers, not a browser.
function harness(status = "authenticated") {
  const instances = new Map(), navigation = [], writes = [];
  let current, effects, seen, disposed = false, invalidations = 0;
  const auth = { status, invalidateSession: () => { invalidations++; clearAccessToken(); auth.status = "unauthenticated"; } };
  const router = { replace: (href) => navigation.push(href) };
  const hooks = {
    useState(initial) {
      const instance = current, index = instance.cursor++;
      if (!(index in instance.slots)) instance.slots[index] = { value: typeof initial === "function" ? initial() : initial };
      const slot = instance.slots[index];
      return [slot.value, (value) => { writes.push({ mounted: instance.mounted }); slot.value = typeof value === "function" ? value(slot.value) : value; }];
    },
    useRef(initial) {
      const index = current.cursor++;
      if (!(index in current.slots)) current.slots[index] = { value: { current: initial } };
      return current.slots[index].value;
    },
    useEffect(effect, dependencies) {
      const instance = current, index = instance.cursor++;
      if (!(index in instance.slots)) instance.slots[index] = {};
      const slot = instance.slots[index];
      if (!slot.dependencies || dependencies.some((v, i) => !Object.is(v, slot.dependencies[i]))) {
        effects.push(() => { slot.cleanup?.(); slot.dependencies = dependencies; slot.cleanup = effect(); });
      }
    },
  };
  const skeleton = (label) => function LoadingSkeleton() { return createElement("p", { role: "status" }, label); };
  const imports = {
    react: hooks, "next/navigation": { useRouter: () => router },
    "next/link": { default: ({ children, ...props }) => createElement("a", props, children) },
    "@/components/AuthProvider": { useAuth: () => auth }, "@/lib/api": { ApiError },
    "@/lib/bookings": bookings, "@/lib/booking-cancellation": cancellation, "@/lib/payment": payment,
    "@/components/LoadingSkeletons": { BookingDetailsSkeleton: skeleton("Loading booking details…"),
      BookingListSkeleton: skeleton("Loading your bookings…"), SessionLoadingSkeleton: skeleton("Checking your session…") },
  };
  const { outputText } = ts.transpileModule(readFileSync(new URL("../components/MyBookingsExperience.tsx", import.meta.url), "utf8"), {
    compilerOptions: { target: ts.ScriptTarget.ES2017, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  });
  const loaded = { exports: {} };
  new Function("require", "module", "exports", outputText)((name) => {
    if (Object.hasOwn(imports, name)) return imports[name];
    if (name === "react/jsx-runtime") return require(name);
    throw new Error(`Unexpected dependency: ${name}`);
  }, loaded, loaded.exports);
  function unmount(instance) { instance.slots.forEach((slot) => slot.cleanup?.()); instance.mounted = false; }
  function expand(node, path) {
    if (Array.isArray(node)) return node.map((child, i) => {
      const expanded = expand(child, `${path}/${child?.key ?? i}`);
      return expanded && typeof expanded === "object" && !Array.isArray(expanded) ? cloneElement(expanded, { key: child?.key ?? i }) : expanded;
    });
    if (!node || typeof node !== "object") return node;
    if (typeof node.type === "function") return renderComponent(node.type, node.props, `${path}/${node.type.name}/${node.key ?? ""}`);
    return cloneElement(node, { children: expand(node.props.children, `${path}/children`) });
  }
  function renderComponent(component, props, path) {
    seen.add(path);
    if (!instances.has(path)) instances.set(path, { slots: [], mounted: true });
    const previous = current;
    current = instances.get(path); current.cursor = 0;
    const tree = component(props);
    current = previous;
    return expand(tree, path);
  }
  return {
    auth, navigation, writes, invalidations: () => invalidations,
    render() {
      assert.equal(disposed, false); effects = []; seen = new Set();
      const tree = renderComponent(loaded.exports.default, {}, "root");
      for (const [path, instance] of instances) if (!seen.has(path)) { unmount(instance); instances.delete(path); }
      const nodes = nodesIn(tree);
      const view = { html: renderToStaticMarkup(tree), nodes, buttons: (label) => buttonsIn(tree, label),
        card: (id) => nodes.find((n) => n.type === "li" && n.key === String(id)) };
      effects.forEach((effect) => effect());
      return view;
    },
    unmount() { instances.forEach(unmount); instances.clear(); disposed = true; },
  };
}
async function loaded(options) {
  const api = syntheticApi(options), h = harness();
  h.render(); await tick();
  return { api, h, view: h.render() };
}
function start(h) {
  buttonsIn(h.render().card(12), "Cancel booking")[0].props.onClick();
  h.render().buttons("Confirm cancellation")[0].props.onClick();
}
function assertCancelled(view) {
  const card = view.card(12);
  assert.ok(card, "cancelled reservation remains visible");
  assert.match(text(card), /cancelled/i);
  assert.match(text(card), /Harbor House.*Queen room/);
  assert.match(text(card), /2026-11-05.*2026-11-08.*150\.50/);
  assert.equal(buttonsIn(card, "Cancel booking").length, 0);
  assert.equal(buttonsIn(card, "Confirm cancellation").length, 0);
  assert.equal(nodesIn(card).filter((n) => n.type === "a" && text(n) === "Complete payment").length, 0);
}

test("confirmed booking is visible with its existing controls before any cancellation", async () => {
  const { api, view } = await loaded();
  assert.match(text(view.card(12)), /confirmed/i);
  assert.equal(buttonsIn(view.card(12), "Cancel booking").length, 1);
  assert.equal(api.writes().length, 0);
});

test("confirmed cancellation preserves the row, original stay and other bookings with one explicit POST", async () => {
  const { api, h, view } = await loaded();
  const otherBefore = renderToStaticMarkup(view.card(13));
  start(h); await tick();
  const after = h.render(); assertCancelled(after);
  assert.match(after.html, /Cancellation recorded/);
  assert.equal(renderToStaticMarkup(after.card(13)), otherBefore);
  h.render(); h.render(); await tick();
  assert.deepEqual(api.writes().map(({ path, method }) => ({ path, method })), [{ path: "/bookings/cancel-booking/12", method: "POST" }]);
});

test("a fresh mount reads persisted cancelled state without cancelling again", async () => {
  const { api, h } = await loaded(); start(h); await tick(); h.render(); h.unmount();
  const revisited = harness(); revisited.render(); await tick(); assertCancelled(revisited.render());
  assert.equal(api.writes().length, 1);
});

test("cancelled and completed reservations have no actionable cancellation controls", async () => {
  const { api, view } = await loaded({ bookings: [{ ...original, status: "cancelled" }, { ...other, status: "completed" }], payments: [{ ...paid, payment_status: "refunded" }, fee] });
  assertCancelled(view); assert.match(text(view.card(13)), /completed/i);
  assert.equal(view.buttons("Cancel booking").length, 0); assert.equal(api.writes().length, 0);
});

test("original payment and the recorded pending cancellation charge have separate truthful labels", async () => {
  const { h } = await loaded(); start(h); await tick();
  const content = text(h.render().card(12));
  assert.match(content, /LikeHome booking payment: refunded \(162\.54 USD\)/i);
  assert.match(content, /LikeHome cancellation charge: pending \(30\.10 USD\)/i);
  assert.doesNotMatch(content, /cancellation charge: paid|refund (?:completed|processed)|money (?:returned|refunded)/i);
  assert.match(content, /internal.*(?:does not confirm|not confirmation|unverified).*external refund/i);
});

test("a fresh payment read displays the recorded fee status rather than assuming it is pending or paid", async (t) => {
  for (const status of ["pending", "paid", "failed", "refunded"]) await t.test(status, async () => {
    const { api, view } = await loaded({ bookings: [{ ...original, status: "cancelled" }], payments: [{ ...paid, payment_status: "refunded" }, { ...fee, amount: 17.43, payment_status: status }] });
    assert.match(text(view.card(12)), new RegExp(`LikeHome cancellation charge: ${status} \\(17\\.43 USD\\)`, "i"));
    assert.equal(api.writes().length, 0);
  });
});

test("no final state or success notice appears before the cancellation acknowledgement", async () => {
  const pending = deferred(); const { api, h } = await loaded({ cancel: () => pending.promise });
  start(h); let view = h.render();
  assert.match(text(view.card(12)), /confirmed/i); assert.doesNotMatch(view.html, /Cancellation recorded/);
  assert.equal(view.buttons("Cancelling…")[0].props.disabled, true);
  pending.resolve(receipt); await tick(); view = h.render(); assertCancelled(view);
  assert.equal(api.writes().length, 1);
});

test("failed or malformed cancellation does not invent a cancelled state or success", async (t) => {
  for (const error of [new ApiError(500), new TypeError("synthetic network failure"), null]) await t.test(error?.constructor.name ?? "malformed", async () => {
    const { api, h } = await loaded({ cancel: async () => { if (error) throw error; return { ...receipt, reservation_id: 999 }; } });
    start(h); await tick(); const view = h.render();
    assert.match(text(view.card(12)), /confirmed/i); assert.doesNotMatch(view.html, /Cancellation recorded/);
    assert.equal(buttonsIn(view.card(12), "Cancel booking").length, 1);
    assert.equal(api.writes().length, 1);
  });
});

test("successful cancellation survives list-refresh failure and retry performs only reads", async () => {
  const { api, h } = await loaded({ readBookings: async (count, state) => { if (count === 2) throw new ApiError(503); return state.bookings; } });
  start(h); await tick(); let view = h.render();
  assertCancelled(view); assert.match(view.html, /Cancellation recorded/);
  assert.doesNotMatch(view.html, /couldn.t cancel|cancellation failed/i);
  assert.match(view.html, /could not (?:refresh|reload)|couldn.t (?:refresh|reload)/i);
  assert.equal(view.buttons("Retry").length, 1);
  view.buttons("Retry")[0].props.onClick(); h.render(); await tick(); view = h.render();
  assertCancelled(view); assert.equal(api.writes().length, 1);
});

test("successful cancellation is not relabelled as failed when only the payment refresh fails", async () => {
  const { api, h } = await loaded({ readPayments: async (count, state) => { if (count === 2) throw new ApiError(503); return state.payments; } });
  start(h); await tick(); const view = h.render();
  assertCancelled(view); assert.match(view.html, /Cancellation recorded/);
  assert.match(text(view.card(12)), /cancellation charge: pending \(30\.10 USD\)/i);
  assert.doesNotMatch(view.html, /couldn.t cancel|cancellation failed/i);
  assert.equal(api.writes().length, 1);
});

test("delayed stale list and payment reads cannot restore an acknowledged cancelled row or its controls", async () => {
  const delayed = deferred();
  const { api, h } = await loaded({ readBookings: async (count, state) => count === 2 ? delayed.promise : state.bookings,
    readPayments: async () => [copy(paid), copy(otherPayment)] });
  start(h); await tick(); assertCancelled(h.render());
  delayed.resolve([copy(original), copy(other)]); await tick(); const view = h.render();
  assertCancelled(view); assert.match(text(view.card(12)), /booking payment: refunded/i);
  assert.match(text(view.card(12)), /cancellation charge: pending \(30\.10 USD\)/i);
  assert.match(text(view.card(13)), /confirmed/i); assert.equal(api.writes().length, 1);
});

test("an incomplete stale list does not erase a reservation whose cancellation was acknowledged", async () => {
  const { h } = await loaded({ readBookings: async (count, state) => count === 2 ? [copy(other)] : state.bookings });
  start(h); await tick(); assertCancelled(h.render());
});

test("already-cancelled conflict refreshes recorded state without claiming this request succeeded", async () => {
  const { api, h } = await loaded({ cancel: async (state) => { state.bookings[0].status = "cancelled"; state.payments = [{ ...paid, payment_status: "refunded" }, fee, otherPayment]; throw new ApiError(409); } });
  start(h); await tick(); const view = h.render();
  assertCancelled(view); assert.doesNotMatch(view.html, /Cancellation recorded/);
  assert.match(view.html, /can no longer be cancelled/); assert.equal(api.writes().length, 1);
});

test("expired authentication on cancellation or subsequent reads hides private final-state content", async (t) => {
  for (const stage of ["cancel", "bookings", "payments"]) await t.test(stage, async () => {
    const { api, h } = await loaded({
      cancel: stage === "cancel" ? async () => { throw new ApiError(401); } : undefined,
      readBookings: async (count, state) => { if (stage === "bookings" && count === 2) throw new ApiError(401); return state.bookings; },
      readPayments: async (count, state) => { if (stage === "payments" && count === 2) throw new ApiError(401); return state.payments; },
    });
    start(h); await tick(); const view = h.render();
    assert.doesNotMatch(view.html, /Harbor House|Garden Stay|162\.54|30\.10/);
    assert.equal(h.invalidations(), 1); assert.ok(h.navigation.length > 0);
    assert.ok(h.navigation.every((href) => href === "/login"));
    assert.equal(api.writes().length, 1);
  });
});

test("logout or unmount ignores a late cancellation response and does not update the abandoned view", async (t) => {
  for (const leave of ["logout", "unmount"]) await t.test(leave, async () => {
    const pending = deferred(); const { api, h } = await loaded({ cancel: () => pending.promise });
    start(h); h.render();
    if (leave === "logout") { h.auth.status = "unauthenticated"; h.render(); } else h.unmount();
    const writes = h.writes.length;
    pending.resolve(receipt); await tick();
    assert.equal(h.writes.length, writes, "late completion must not write final state into an abandoned session");
    assert.equal(api.writes().length, 1);
  });
});

test("switching booking details ignores a delayed response for the previous reservation", async () => {
  const delayed = deferred(); const { api, h } = await loaded({ readDetail: async (id, state) => id === 12 ? delayed.promise : state.bookings.find((b) => b.reservation_id === id) });
  buttonsIn(h.render().card(12), "View details")[0].props.onClick(); h.render();
  buttonsIn(h.render().card(13), "View details")[0].props.onClick(); h.render(); await tick();
  delayed.resolve({ ...original, hotel_description: "OBSOLETE DETAIL RESPONSE" }); await tick();
  const view = h.render(); assert.doesNotMatch(view.html, /OBSOLETE DETAIL RESPONSE/);
  assert.equal(buttonsIn(view.card(12), "Hide details").length, 0);
  assert.equal(buttonsIn(view.card(13), "Hide details").length, 1);
  assert.equal(api.writes().length, 0);
});

test("restoring or unauthenticated sessions do not load bookings or display private state", () => {
  const api = syntheticApi();
  for (const status of ["restoring", "unauthenticated"]) {
    const h = harness(status); assert.doesNotMatch(h.render().html, /Harbor House|Garden Stay/);
    h.unmount();
  }
  assert.deepEqual(api.requests, []);
});

test("reopening cancelled details cannot display a stale confirmed status", async () => {
  const { h } = await loaded({ readDetail: async () => copy(original) });
  start(h); await tick(); let view = h.render(); assertCancelled(view);
  buttonsIn(view.card(12), "View details")[0].props.onClick(); h.render(); await tick(); view = h.render();
  assert.match(text(view.card(12)), /Booking details/);
  assert.doesNotMatch(text(view.card(12)), /Statusconfirmed/i);
  assert.match(text(view.card(12)), /Statuscancelled/i);
});

test("a stale confirmed row cannot replace the acknowledged reservation's hotel, dates or recorded total", async () => {
  const stale = { ...original, hotel_name: "Obsolete Hotel", check_in_date: "2026-10-01", check_out_date: "2026-10-02", total_price: 0.01 };
  const { h } = await loaded({ readBookings: async (count, state) => count === 2 ? [stale, copy(other)] : state.bookings });
  start(h); await tick(); const view = h.render(); assertCancelled(view);
  assert.doesNotMatch(view.html, /Obsolete Hotel|2026-10-01|2026-10-02/);
});

test("a later fee read can show paid without claiming an external payment or repeating cancellation", async () => {
  const { api, h } = await loaded({ readPayments: async (count, state) => count === 2
    ? state.payments.map((p) => p.payment_id === fee.payment_id ? { ...p, payment_status: "paid" } : p) : state.payments });
  start(h); await tick(); const view = h.render(); assertCancelled(view);
  assert.match(text(view.card(12)), /cancellation charge: paid \(30\.10 USD\)/i);
  assert.doesNotMatch(view.html, /charge is pending|external (?:payment|refund) (?:completed|processed)/i);
  assert.equal(api.writes().length, 1);
});

test("an unpaid cancellation keeps the original payment pending and does not invent a refund", async () => {
  const pending = { ...paid, payment_status: "pending" };
  const unpaidReceipt = { ...receipt, booking_payment_status: "pending" };
  const { api, h } = await loaded({ payments: [pending, otherPayment], cancel: async (state) => {
    state.bookings[0].status = "cancelled"; state.payments.push(copy(fee)); return unpaidReceipt;
  } });
  start(h); await tick(); const view = h.render(); assertCancelled(view);
  assert.match(text(view.card(12)), /booking payment: pending \(162\.54 USD\)/i);
  assert.doesNotMatch(text(view.card(12)), /refunded/i); assert.equal(api.writes().length, 1);
});

test("repeated refresh failures keep the recorded final state and retry never submits another cancellation", async () => {
  const { api, h } = await loaded({ readBookings: async (count, state) => { if (count > 1) throw new ApiError(503); return state.bookings; } });
  start(h); await tick(); let view = h.render(); assertCancelled(view);
  view.buttons("Retry")[0].props.onClick(); h.render(); await tick(); view = h.render();
  assertCancelled(view); assert.match(view.html, /Cancellation recorded/);
  assert.equal(view.buttons("Retry").length, 1); assert.equal(api.writes().length, 1);
});

test("unmount during a delayed list refresh ignores the response without starting a payment refresh", async () => {
  const delayed = deferred();
  const { api, h } = await loaded({ readBookings: async (count, state) => count === 2 ? delayed.promise : state.bookings });
  start(h); await tick(); assertCancelled(h.render()); h.unmount();
  const writes = h.writes.length, requests = api.requests.length;
  delayed.resolve([{ ...original, status: "cancelled" }, other]); await tick();
  assert.equal(h.writes.length, writes); assert.equal(api.requests.length, requests);
  assert.equal(api.writes().length, 1);
});

test("a fresh cancelled detail response remains visible when the earlier list was still confirmed", async () => {
  const { h } = await loaded({ readDetail: async () => ({ ...original, status: "cancelled" }) });
  buttonsIn(h.render().card(12), "View details")[0].props.onClick(); h.render(); await tick();
  assert.match(text(h.render().card(12)), /Statuscancelled/i);
});
