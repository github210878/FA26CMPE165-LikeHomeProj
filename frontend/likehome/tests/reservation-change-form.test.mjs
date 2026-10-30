import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { createRequire } from "node:module";
import { afterEach, beforeEach, test } from "node:test";
import { cloneElement, createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

import { ApiError } from "../lib/api.ts";
import * as cancellation from "../lib/booking-cancellation.ts";
import { bookingPaymentForReservation, paymentHref } from "../lib/payment.ts";
import { getReservationChangeQuote } from "../lib/bookings.ts";

const require = createRequire(import.meta.url);
const tick = () => new Promise(setImmediate);
const originals = { fetch: globalThis.fetch, window: globalThis.window, document: globalThis.document };
const consoleMethods = ["log", "info", "warn", "error", "debug"];
const originalConsole = Object.fromEntries(consoleMethods.map((method) => [method, console[method]]));
let harnesses, persistence, logs, liveFetches, events;

function eventTarget(target) {
  return {
    addEventListener(name, fn) {
      const key = `${target}:${name}`;
      if (!events.has(key)) events.set(key, new Set());
      events.get(key).add(fn);
    },
    removeEventListener(name, fn) { events.get(`${target}:${name}`)?.delete(fn); },
  };
}

beforeEach(() => {
  harnesses = []; persistence = []; logs = []; liveFetches = []; events = new Map();
  const storage = {
    getItem: () => null,
    setItem: (...args) => persistence.push(["setItem", ...args]),
    removeItem: (...args) => persistence.push(["removeItem", ...args]),
    clear: () => persistence.push(["clear"]),
  };
  globalThis.window = { ...eventTarget("window"), localStorage: storage, sessionStorage: storage };
  window.history = Object.fromEntries(["pushState", "replaceState"].map((method) =>
    [method, (...args) => persistence.push([method, ...args])]));
  globalThis.document = { ...eventTarget("document"),
    get cookie() { return ""; }, set cookie(value) { persistence.push(["cookie", value]); } };
  globalThis.fetch = async (...args) => { liveFetches.push(args); throw new Error("Unexpected live fetch"); };
  for (const method of consoleMethods) console[method] = (...args) => logs.push([method, ...args]);
});

afterEach(() => {
  harnesses.forEach((h) => h.unmount());
  for (const [key, value] of Object.entries(originals)) globalThis[key] = value;
  for (const method of consoleMethods) console[method] = originalConsole[method];
  assert.deepEqual(liveFetches, []);
  assert.deepEqual(persistence, [], "quotes and auth secrets must not be persisted by the form");
  assert.deepEqual(logs, [], "quotes and auth secrets must not be logged");
  for (const h of harnesses) {
    assert.equal(h.calls.some((call) => ["confirmation", "settlement", "payment"].includes(call.operation)), false);
    if (!h.page) assert.ok(h.calls.every((call) => ["quote", "invalidate"].includes(call.operation)));
    assert.doesNotMatch(JSON.stringify(h.navigation), /synthetic-signed-secret|synthetic-auth-secret|synthetic-property-/);
  }
});

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

const bookings = [42, 43, 44, 45].map((id, i) => ({
  reservation_id: id, hotel_name: `Synthetic Hotel ${id}`, room_type_name: "Queen room for an unspecified party",
  hotel_address: "Synthetic address", hotel_phone: null, hotel_description: "Synthetic property description",
  room_description: "Room labels do not establish guest counts", check_in_date: "2096-02-28T00:00:00",
  check_out_date: "2096-03-01T00:00:00", price_per_night: 100, total_price: 210,
  status: ["confirmed", "confirmed", "cancelled", "completed"][i],
}));

function summary(id = 42) {
  return {
    reservation_id: id, reservation_revision: 0, reservation_status: "confirmed", currency: "USD",
    latest_change_id: null, current_reservation_total: 210, current_booking_obligation: 226.8,
    original_booking_payment: { payment_id: id + 100, reservation_id: id, amount: 226.8,
      payment_type: "booking", payment_status: "paid" },
    outstanding_booking_amount: 0, paid_additional_charges: 0, pending_additional_charges: 0,
    failed_additional_charges: 0, voided_additional_charges: 0, recorded_internal_credits: 0,
    outstanding_additional_amount: 0, adjustments: [], cancellation_reconciliations: [],
    reconciliation_credits: 0, reconciliation_debits: 0, cancellation_payment: null, outstanding_cancellation_amount: 0,
  };
}

function quote(id = 42, request = {}, expires = Date.now() + 600000) {
  return {
    reservation_id: id, quote_id: `synthetic-signed-secret-${id}`, expires_at: new Date(expires).toISOString(),
    quote: { property_token: `synthetic-property-${id}`, hotel_name: `Quoted Hotel ${id}`,
      check_in_date: request.check_in_date ?? "2096-02-28", check_out_date: request.check_out_date ?? "2096-03-01",
      adults: request.adults ?? 2, children: request.children ?? 1, currency: "USD", number_of_nights: 2,
      availability: "available", rate_rule: "lowest_eligible_provider_base_total", source: "Synthetic Provider",
      guest_capacity: 3, current_price_per_night: 125.5, provider_base_total: 251,
      provider_total_with_taxes_fees: 275, likehome_reservation_total: 263.55, likehome_payment_amount: 284.63,
      price_changed: null },
  };
}

function text(node) {
  if (Array.isArray(node)) return node.map(text).join("");
  if (node && typeof node === "object") return text(node.props?.children);
  return node === null || node === undefined || typeof node === "boolean" ? "" : String(node);
}

function loadComponent(path, imports, clock) {
  const { outputText } = ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  });
  const loaded = { exports: {} };
  new Function("require", "module", "exports", "Date", "setTimeout", "clearTimeout", outputText)(
    (name) => {
      if (Object.hasOwn(imports, name)) return imports[name];
      if (name === "react/jsx-runtime") return require(name);
      throw new Error(`Unexpected component dependency: ${name}`);
    }, loaded, loaded.exports,
    clock.Date, clock.setTimeout, clock.clearTimeout,
  );
  return loaded.exports.default;
}

// Runs actual TSX event handlers and effect callbacks with the project's existing
// deterministic hook convention, then renders the host tree with React. This does
// not exercise a DOM, Next's chunk loader, native form validation, or React/browser
// scheduling. Synthetic timers let us check expiry callbacks and cleanup precisely.
function harness({ page = false, status = "authenticated", session, pendingPayment = false, records = bookings,
  readQuote = async (id, request) => quote(id, request) } = {}) {
  const instances = new Map(), timers = new Map();
  const calls = [], navigation = [], writes = [];
  let current, pendingEffects, seen, disposed = false, time = Date.now(), timerId = 0;
  const clock = {
    Date: class extends Date { static now() { return time; } },
    setTimeout(fn, delay) { const id = ++timerId; timers.set(id, { fn, due: time + delay }); return id; },
    clearTimeout(id) { timers.delete(id); },
  };
  const auth = session ?? { status, invalidateSession: () => { auth.status = "unauthenticated"; calls.push({ operation: "invalidate" }); } };
  const router = { replace: (href) => navigation.push(href) };
  const hooks = {
    useState(initial) {
      const instance = current, index = instance.cursor++;
      if (!(index in instance.slots)) instance.slots[index] = { value: typeof initial === "function" ? initial() : initial };
      const slot = instance.slots[index];
      return [slot.value, (value) => {
        writes.push({ mounted: instance.mounted });
        slot.value = typeof value === "function" ? value(slot.value) : value;
      }];
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
      if (!slot.dependencies || dependencies.some((value, i) => !Object.is(value, slot.dependencies[i]))) {
        pendingEffects.push(() => { slot.cleanup?.(); slot.dependencies = dependencies; slot.cleanup = effect(); });
      }
    },
  };
  const readers = {
    getReservationChangeQuote: (id, request) => { calls.push({ operation: "quote", id, request }); return readQuote(id, request); },
    getReservationFinancialSummary: async (id) => { calls.push({ operation: "summary", id }); return summary(id); },
    getMyBookings: async () => { calls.push({ operation: "bookings" }); return records; },
    getMyPayments: async () => { calls.push({ operation: "payments" }); return records.map((b) => ({
      ...summary(b.reservation_id).original_booking_payment, payment_status: pendingPayment ? "pending" : "paid",
    })); },
    getBookingDetails: async (id) => { calls.push({ operation: "details", id }); return records.find((b) => b.reservation_id === id); },
    cancelBookingAndRefresh: async (id, onCancelled) => {
      calls.push({ operation: "cancellation", id });
      onCancelled({ reservation_id: id, status: "cancelled" });
      return { kind: "refreshed", bookings: records.map((b) => b.reservation_id === id ? { ...b, status: "cancelled" } : b) };
    },
  };
  for (const [name, operation] of Object.entries({ confirmReservationChange: "confirmation",
    payReservationChangeAdjustment: "settlement", payBookingPayment: "payment" })) {
    readers[name] = () => { calls.push({ operation }); throw new Error(`Unexpected ${operation}`); };
  }
  function skeleton(label) {
    return function LoadingSkeleton() { return createElement("p", { role: "status" }, label); };
  }
  const imports = {
    react: hooks, "next/navigation": { useRouter: () => router },
    "next/link": { default: ({ children, ...props }) => createElement("a", props, children) },
    "@/components/AuthProvider": { useAuth: () => auth },
    "@/lib/api": { ApiError }, "@/lib/bookings": readers,
    "@/lib/booking-cancellation": cancellation,
    "@/lib/payment": { bookingPaymentForReservation, paymentHref },
    "@/components/LoadingSkeletons": {
      BookingDetailsSkeleton: skeleton("Loading booking details…"),
      BookingListSkeleton: skeleton("Loading your bookings…"),
      SessionLoadingSkeleton: skeleton("Checking your session…"),
    },
  };

  const Flow = loadComponent(
      "../components/ReservationChangeFlow.tsx",
      {
        ...imports,
        "@/components/ReservationChangeForm": {
          default: () => null,
        },
        "@/components/ReservationChangeConfirmation": {
          default: () => null,
        },
      },
      clock
  );

  imports["@/components/ReservationChangeFlow"] = {
    default: Flow,
  };
  const Form = loadComponent("../components/ReservationChangeForm.tsx", imports, clock);
  // Only this synthetic boundary mounts the dormant form. The actual current
  // booking page is tested separately and must never acquire a form import.
  function ReviewFixture({ visible = true, ...formProps }) {
    return visible ? createElement(Form, formProps) : null;
  }
  const Root = page ? loadComponent("../components/MyBookingsExperience.tsx", imports, clock) : ReviewFixture;
  let props = { reservationId: 42, checkInDate: bookings[0].check_in_date, checkOutDate: bookings[0].check_out_date };

  function unmount(instance) {
    instance.slots.forEach((slot) => slot.cleanup?.());
    instance.mounted = false;
  }
  function expand(node, path) {
    if (Array.isArray(node)) return node.map((child, i) => {
      const expanded = expand(child, `${path}/${child?.key ?? i}`);
      return expanded && typeof expanded === "object" && !Array.isArray(expanded)
        ? cloneElement(expanded, { key: child?.key ?? i }) : expanded;
    });
    if (!node || typeof node !== "object") return node;
    if (typeof node.type === "function") return renderComponent(node.type, node.props, `${path}/${node.type.name}/${node.key ?? ""}`);
    return cloneElement(node, { children: expand(node.props.children, `${path}/children`) });
  }
  function renderComponent(component, componentProps, path) {
    seen.add(path);
    if (!instances.has(path)) instances.set(path, { slots: [], mounted: true });
    const previous = current;
    current = instances.get(path); current.cursor = 0;
    const result = component(componentProps);
    current = previous;
    return expand(result, path);
  }
  const h = {
    page, calls, navigation, auth, writes, timers,
    now: () => time,
    jump(ms) { time += ms; },
    advance(ms) {
      time += ms;
      for (const [id, timer] of [...timers]) if (timer.due <= time) { timers.delete(id); timer.fn(); }
    },
    fire(target, name) { for (const fn of [...(events.get(`${target}:${name}`) ?? [])]) fn(); },
    render(nextProps = props) {
      assert.equal(disposed, false);
      props = nextProps; seen = new Set(); pendingEffects = [];
      const tree = renderComponent(Root, props, "root");
      for (const [path, instance] of instances) if (!seen.has(path)) { unmount(instance); instances.delete(path); }
      const nodes = [];
      function visit(node) {
        if (Array.isArray(node)) return node.forEach(visit);
        if (!node || typeof node !== "object") return;
        nodes.push(node); visit(node.props.children);
      }
      visit(tree);
      const rows = new Map();
      for (const node of nodes) {
        const children = node.props.children;
        if (node.type === "div" && Array.isArray(children) && children[0]?.type === "dt") rows.set(text(children[0]), text(children[1]));
      }
      const html = renderToStaticMarkup(tree);
      assert.doesNotMatch(html, /synthetic-signed-secret|synthetic-auth-secret|synthetic-property-/);
      const view = { html, nodes, rows,
        buttons: (label) => nodes.filter((n) => n.type === "button" && text(n) === label),
        input: (name) => nodes.find((n) => n.type === "input" && n.props.name === name),
        form: nodes.find((n) => n.type === "form"),
      };
      pendingEffects.forEach((effect) => effect());
      return view;
    },
    edit(name, value) { h.render().input(name).props.onChange({ target: { value } }); return h.render(); },
    submit() { h.render().form.props.onSubmit({ preventDefault() {} }); return h.render(); },
    show(visible) { return h.render({ ...props, visible }); },
    unmount() { if (!disposed) { instances.forEach(unmount); instances.clear(); disposed = true; } },
  };
  harnesses.push(h);
  return h;
}

function fill(h) {
  for (const [name, value] of Object.entries({ check_in_date: "2096-02-28", check_out_date: "2096-03-01", q: "San Jose", adults: "2", children: "1" })) h.edit(name, value);
  return h.render();
}

async function openPage(h, index = 0) {
  h.render(); await tick();
  h.render().buttons("View details")[index].props.onClick();
  h.render(); await tick(); h.render(); await tick();
  return h.render();
}

const quoteCalls = (h) => h.calls.filter((c) => c.operation === "quote");

test("module import alone runs no hook, quote request, timer, storage write, or navigation", () => {
  const unexpected = () => { assert.fail("import must not start component work"); };
  const component = loadComponent("../components/ReservationChangeForm.tsx", {
    react: { useEffect: unexpected, useRef: unexpected, useState: unexpected },
    "next/navigation": { useRouter: unexpected },
    "@/components/AuthProvider": { useAuth: unexpected },
    "@/lib/api": { ApiError }, "@/lib/bookings": { getReservationChangeQuote: unexpected },
  }, { Date, setTimeout: unexpected, clearTimeout: unexpected });
  assert.equal(typeof component, "function");
  assert.equal(events.size, 0);
});


test("only ReservationChangeFlow directly imports the reservation change form and the form uses the quote adapter", () => {
  const references = [];
  function inspect(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const url = new URL(entry.name + (entry.isDirectory() ? "/" : ""), directory);
      if (entry.isDirectory()) inspect(url);
      else if (/\.(?:[cm]?[jt]sx?)$/.test(entry.name) && entry.name !== "ReservationChangeForm.tsx" &&
        /ReservationChangeForm|reservation-change-form/.test(readFileSync(url, "utf8"))) references.push(url.pathname);
    }
  }
  for (const directory of ["app", "components", "lib", "constants"]) inspect(new URL(`../${directory}/`, import.meta.url));
  assert.deepEqual(
      references.map((path) => path.split("/").pop()),
      ["ReservationChangeFlow.tsx"]
  );
  const source = readFileSync(new URL("../components/ReservationChangeForm.tsx", import.meta.url), "utf8");
  const parsed = ts.createSourceFile("ReservationChangeForm.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const adapters = parsed.statements.filter((node) => ts.isImportDeclaration(node) && node.moduleSpecifier.text === "@/lib/bookings")
    .flatMap((node) => node.importClause.namedBindings.elements.map((name) => name.name.text));
  assert.deepEqual(adapters, ["getReservationChangeQuote"]);
  assert.doesNotMatch(source, /confirmReservationChange|payReservationChangeAdjustment|ConfirmationReceipt|onRefreshCurrent/);
});

test("synthetic authenticated mounting, rerenders, focus, and visibility never submit automatically", async () => {
  const h = harness();
  for (let i = 0; i < 3; i++) {
    const view = h.render();
    assert.doesNotMatch(view.html, /Price quote \(USD\)|Quoted Hotel|role="alert"/);
    h.fire("window", "focus"); h.fire("document", "visibilitychange");
    await tick();
  }
  assert.deepEqual(h.calls, []);
  assert.equal(h.timers.size, 0);
});

test("current booking details keep the quote form dormant for every reservation status", async (t) => {
  for (const status of ["confirmed", "cancelled", "completed"]) {
    await t.test(status, async () => {
      const h = harness({ page: true, records: [{ ...bookings[0], status }] });
      h.render(); await tick();
      assert.equal(h.render().buttons("Review a reservation change").length, 0);
      const view = await openPage(h);
      assert.equal(view.buttons("Review a reservation change").length, 0);
      assert.equal(quoteCalls(h).length, 0);
      assert.match(view.html, /Booking details|Synthetic property description/);
      assert.doesNotMatch(view.html, /Request a change quote|Financial summary|Price quote \(USD\)/);
      assert.deepEqual(h.calls.map((c) => c.operation), ["bookings", "payments", "details"]);
    });
  }
});

test("controlled labelled fields initialize only valid booking dates and leave reconfirmation fields empty", () => {
  const h = harness(); let view = h.render();
  assert.equal(view.input("check_in_date").props.value, "2096-02-28");
  assert.equal(view.input("check_out_date").props.value, "2096-03-01");
  for (const name of ["q", "adults", "children"]) assert.equal(view.input(name).props.value, "");
  assert.match(view.html, /Reconfirm your destination and both guest counts/);
  assert.equal(view.nodes.filter((n) => n.type === "label").length, 5);
  for (const name of ["check_in_date", "check_out_date"]) assert.equal(view.input(name).props.type, "date");
  for (const name of ["adults", "children"]) assert.equal(view.input(name).props.type, "number");
  view = h.render({ reservationId: 43, checkInDate: "2095-02-29", checkOutDate: "nonsense" });
  assert.equal(view.input("check_in_date").props.value, ""); assert.equal(view.input("check_out_date").props.value, "");
  assert.equal(quoteCalls(h).length, 0);
});

test("explicit submission sends only customer-entered review context with supported internal defaults", async () => {
  const h = harness(); fill(h);
  assert.equal(quoteCalls(h).length, 0);
  const view = h.submit();
  assert.equal(view.form.props["aria-busy"], true);
  assert.match(view.html, /Requesting price quote/);
  assert.deepEqual(quoteCalls(h), [{ operation: "quote", id: 42, request: {
    check_in_date: "2096-02-28", check_out_date: "2096-03-01", q: "San Jose", adults: 2, children: 1,
    currency: "USD", gl: "us", hl: "en",
  } }]);
  await tick(); h.render();
  assert.deepEqual(h.calls.map((c) => c.operation), ["quote"]);
  assert.deepEqual(h.navigation, []);
});

test("leaves blank occupancy invalid rather than inventing defaults and delegates rules to the adapter", async () => {
  const h = harness({ readQuote: async () => { throw new Error("Invalid reservation change review"); } });
  h.render(); h.edit("q", "San Jose"); h.submit(); await tick();
  const request = quoteCalls(h)[0].request;
  assert.ok(Number.isNaN(request.adults)); assert.ok(Number.isNaN(request.children));
  const view = h.render();
  assert.match(view.html, /role="alert"/); assert.match(view.html, /Check your dates, destination, and whole-number guest counts/);
  assert.equal(view.input("adults").props.value, "");
  assert.match(view.form.props["aria-describedby"], /change-review-error-42/);
});

test("form values reach the existing adapter's date, destination, and occupancy validation without a network call", async (t) => {
  const cases = [
    ["blank check-in", "check_in_date", ""], ["malformed check-in", "check_in_date", "2096-2-28"],
    ["impossible date", "check_in_date", "2096-02-30"], ["non-leap date", "check_in_date", "2095-02-29"],
    ["past date", "check_in_date", "2000-01-01"], ["blank check-out", "check_out_date", ""],
    ["impossible check-out", "check_out_date", "2096-04-31"],
    ["equal dates", "check_out_date", "2096-02-28"], ["reversed dates", "check_out_date", "2096-02-27"],
    ["blank destination", "q", ""], ["whitespace destination", "q", "   "], ["long destination", "q", "x".repeat(256)],
    ["blank adults", "adults", ""], ["zero adults", "adults", "0"], ["negative adults", "adults", "-1"],
    ["fractional adults", "adults", "1.5"], ["too many adults", "adults", "21"], ["invalid adults", "adults", "abc"],
    ["blank children", "children", ""], ["negative children", "children", "-1"],
    ["fractional children", "children", "0.5"], ["too many children", "children", "21"],
  ];
  for (const [label, name, value] of cases) {
    await t.test(label, async () => {
      const h = harness({ readQuote: getReservationChangeQuote });
      fill(h); h.edit(name, value); h.submit(); await tick();
      const view = h.render();
      assert.match(view.html, /role="alert"/);
      assert.match(view.html, /Check your dates, destination, and whole-number guest counts/);
      assert.doesNotMatch(view.html, /Price quote \(USD\)|Quoted Hotel/);
      assert.equal(view.input(name).props.value, value);
      assert.equal(quoteCalls(h).length, 1);
      assert.equal(liveFetches.length, 0);
      assert.equal(h.auth.status, "authenticated");
      assert.deepEqual(h.navigation, []);
    });
  }
});

test("explicitly reconfirmed zero children remains zero without borrowing historical occupancy", async () => {
  const h = harness(); fill(h); h.edit("children", "0"); h.submit(); await tick();
  assert.equal(quoteCalls(h)[0].request.children, 0);
  assert.equal(h.render().rows.get("Children"), "0");
});

test("the existing adapter's missing-authentication error redirects safely before fetch", async () => {
  const h = harness({ readQuote: getReservationChangeQuote });
  fill(h); h.submit(); await tick();
  assert.equal(h.auth.status, "unauthenticated");
  assert.equal(h.calls.filter((call) => call.operation === "invalidate").length, 1);
  assert.deepEqual(h.navigation, ["/login"]);
  assert.equal(h.render().html, "");
  assert.equal(liveFetches.length, 0);
});

test("blocks same-tick duplicate submits, disables pending fields, and keeps a clear loading state", async () => {
  const pending = deferred(); const h = harness({ readQuote: () => pending.promise });
  const form = fill(h).form;
  form.props.onSubmit({ preventDefault() {} }); form.props.onSubmit({ preventDefault() {} });
  let view = h.render();
  assert.equal(quoteCalls(h).length, 1);
  assert.equal(view.buttons("Requesting quote…")[0].props.disabled, true);
  assert.equal(view.nodes.find((n) => n.type === "fieldset").props.disabled, true);
  h.edit("q", "Attempted edit while disabled");
  assert.equal(h.render().input("q").props.value, "San Jose");
  h.submit(); assert.equal(quoteCalls(h).length, 1);
  pending.resolve(quote()); await tick(); view = h.render();
  assert.equal(view.form.props["aria-busy"], false);
  assert.equal(view.nodes.find((n) => n.type === "fieldset").props.disabled, false);
});

test("preview shows validated hotel, dates, guests, independent USD prices, and aware expiry without mutation controls", async () => {
  const h = harness(); fill(h); h.submit(); await tick(); const view = h.render();
  assert.equal(view.rows.get("Hotel"), "Quoted Hotel 42");
  assert.equal(view.rows.get("Proposed check-in"), "2096-02-28");
  assert.equal(view.rows.get("Proposed check-out"), "2096-03-01");
  assert.equal(view.rows.get("Number of nights"), "2");
  assert.equal(view.rows.get("Adults"), "2"); assert.equal(view.rows.get("Children"), "1");
  assert.equal(view.rows.get("Current nightly price"), "$125.50");
  assert.equal(view.rows.get("Proposed reservation total (before tax)"), "$263.55");
  assert.equal(view.rows.get("LikeHome payment amount (including tax)"), "$284.63");
  assert.ok(view.nodes.find((n) => n.type === "time").props.dateTime.endsWith("Z"));
  assert.match(view.html, /This is a price quote only\. Your reservation has not been changed\./);
  assert.doesNotMatch(view.html, /refund|additional charge|difference|Confirm change|Settle|Pay adjustment/i);
  assert.equal(view.nodes.filter((n) => n.type === "button").length, 1);
  assert.deepEqual(h.calls.map((c) => c.operation), ["quote"]);
});

test("editing any review field immediately discards the old preview and requires another explicit request", async (t) => {
  for (const [name, value] of Object.entries({ check_in_date: "2096-02-29", check_out_date: "2096-03-02", q: "Palo Alto", adults: "3", children: "0" })) {
    await t.test(name, async () => {
      const h = harness(); fill(h); h.submit(); await tick(); h.render();
      assert.equal(h.timers.size, 1);
      let view = h.edit(name, value);
      assert.doesNotMatch(view.html, /Price quote \(USD\)|Quoted Hotel|284\.63/);
      assert.equal(h.timers.size, 0); assert.equal(quoteCalls(h).length, 1);
      h.submit(); await tick(); view = h.render();
      assert.equal(quoteCalls(h).length, 2);
      assert.equal(quoteCalls(h)[1].request[name], ["adults", "children"].includes(name) ? Number(value) : value);
      assert.match(view.html, /Price quote \(USD\)/);
    });
  }
});

test("HTTP and transport errors use safe messages without automatic retry or losing form values", async (t) => {
  const cases = [
    [new ApiError(400), /overlap another booking/], [new ApiError(404), /unavailable or cannot be accessed/],
    [new ApiError(409), /has changed or cannot support/], [new ApiError(422), /Check your dates/],
    [new ApiError(502), /provider is unavailable/], [new ApiError(504), /took too long/],
    [new ApiError(500), /could not request a price quote/], [new TypeError("private network secret"), /valid, current price quote/],
    [new Error("Reservation change quote returned an unexpected response"), /valid, current price quote/],
    [new Error("API returned an invalid JSON response"), /valid, current price quote/],
  ];
  for (const [error, message] of cases) {
    await t.test(error instanceof ApiError ? String(error.status) : error.message, async () => {
      const h = harness({ readQuote: async () => { throw error; } });
      fill(h); h.submit(); await tick(); let view = h.render();
      assert.match(view.html, message); assert.match(view.html, /role="alert"/);
      assert.doesNotMatch(view.html, /private network secret|API request failed|unexpected response|invalid JSON/);
      assert.equal(view.input("q").props.value, "San Jose");
      h.render(); await tick(); view = h.render();
      assert.equal(quoteCalls(h).length, 1); assert.equal(h.auth.status, "authenticated");
      assert.equal(h.navigation.length, 0);
      assert.equal(view.nodes.filter((n) => n.type === "button" && !n.props.disabled).length, 1);
    });
  }
});

test("explicit retry makes one fresh quote request and suppresses duplicate retries", async () => {
  const pending = deferred(); let attempts = 0;
  const h = harness({ readQuote: () => ++attempts === 1 ? Promise.reject(new ApiError(504)) : pending.promise });
  fill(h); h.submit(); await tick(); let view = h.render();
  assert.equal(view.buttons("Retry quote").length, 1);
  const form = view.form; form.props.onSubmit({ preventDefault() {} }); form.props.onSubmit({ preventDefault() {} });
  view = h.render(); assert.match(view.html, /Requesting price quote/);
  assert.equal(quoteCalls(h).length, 2);
  pending.resolve(quote()); await tick(); assert.match(h.render().html, /Price quote \(USD\)/);
});

test("already expired or malformed expirations never become a valid preview even with a mocked adapter", async (t) => {
  for (const expires_at of ["2000-01-01T00:00:00Z", "not a timestamp"]) {
    await t.test(expires_at, async () => {
      const h = harness({ readQuote: async () => ({ ...quote(), expires_at }) });
      fill(h); h.submit(); await tick(); const view = h.render();
      assert.match(view.html, /valid, current price quote/);
      assert.doesNotMatch(view.html, /Quoted Hotel|284\.63/);
      assert.equal(h.timers.size, 0); assert.equal(quoteCalls(h).length, 1);
    });
  }
});

test("expiry timer removes the active price preview and offers a fresh explicit request without auto-fetching", async () => {
  let h;
  h = harness({ readQuote: async (id, request) => quote(id, request, h.now() + 1000) });
  fill(h); h.submit(); await tick(); assert.match(h.render().html, /Price quote \(USD\)/);
  h.advance(1001); let view = h.render();
  assert.match(view.html, /This quote has expired/); assert.doesNotMatch(view.html, /Quoted Hotel|284\.63/);
  assert.equal(view.buttons("Request a fresh quote").length, 1);
  assert.equal(h.timers.size, 0); assert.equal(quoteCalls(h).length, 1);
  h.submit(); await tick(); view = h.render();
  assert.match(view.html, /Price quote \(USD\)/); assert.equal(quoteCalls(h).length, 2);
});

test("focus and visibility changes recheck expiry after suspension or a clock jump", async (t) => {
  for (const [target, event] of [["window", "focus"], ["document", "visibilitychange"]]) {
    await t.test(event, async () => {
      const h = harness(); fill(h); h.submit(); await tick(); h.render();
      h.jump(700000); h.fire(target, event);
      const view = h.render();
      assert.match(view.html, /This quote has expired/); assert.doesNotMatch(view.html, /284\.63/);
      assert.equal(quoteCalls(h).length, 1);
    });
  }
});

test("a synthetic parent closing the form ignores late success or 401 and reopening starts empty", async (t) => {
  for (const late401 of [false, true]) {
    await t.test(late401 ? "late 401" : "late success", async () => {
      const pending = deferred(); const h = harness({ readQuote: () => pending.promise });
      const oldForm = fill(h).form; h.submit();
      h.show(false); const before = h.writes.length;
      oldForm.props.onSubmit({ preventDefault() {} });
      if (late401) pending.reject(new ApiError(401)); else pending.resolve(quote());
      await tick(); let view = h.render();
      assert.equal(h.writes.length, before); assert.equal(h.auth.status, "authenticated");
      assert.deepEqual(h.navigation, []); assert.doesNotMatch(view.html, /Quoted Hotel|Price quote \(USD\)/);
      view = h.show(true);
      assert.equal(view.input("q").props.value, ""); assert.equal(view.input("children").props.value, "");
      assert.equal(quoteCalls(h).length, 1);
    });
  }
});

test("synthetic parent removal discards unresolved review without updating inactive form state", async () => {
  const pending = deferred(); const h = harness({ readQuote: () => pending.promise });
  fill(h); h.submit();
  h.show(false); const before = h.writes.length;
  pending.resolve(quote()); await tick(); const view = h.render();
  assert.equal(h.writes.length, before); assert.equal(view.html, "");
  assert.equal(quoteCalls(h).length, 1);
});

test("switching reservations cannot display a late quote or invalidate the current session", async (t) => {
  for (const late401 of [false, true]) {
    await t.test(late401 ? "late 401" : "late success", async () => {
      const first = deferred(), second = deferred();
      const h = harness({ readQuote: (id) => id === 42 ? first.promise : second.promise });
      fill(h); h.submit();
      h.render({ reservationId: 43, checkInDate: bookings[1].check_in_date, checkOutDate: bookings[1].check_out_date });
      fill(h); h.submit();
      if (late401) first.reject(new ApiError(401)); else first.resolve(quote(42));
      await tick(); let view = h.render();
      assert.match(view.html, /Requesting price quote/); assert.doesNotMatch(view.html, /Quoted Hotel 42/);
      assert.equal(h.auth.status, "authenticated"); assert.deepEqual(h.navigation, []);
      second.resolve(quote(43)); await tick(); view = h.render();
      assert.match(view.html, /Quoted Hotel 43/); assert.doesNotMatch(view.html, /Quoted Hotel 42/);
      assert.deepEqual(quoteCalls(h).map((c) => c.id), [42, 43]);
    });
  }
});

test("unmount ignores a pending failure and cancels success expiry timers and event listeners", async () => {
  const pending = deferred(); const h = harness({ readQuote: () => pending.promise });
  fill(h); h.submit(); h.unmount(); const before = h.writes.length;
  pending.reject(new ApiError(401)); await tick();
  assert.equal(h.writes.length, before); assert.deepEqual(h.navigation, []);
  const success = harness(); fill(success); success.submit(); await tick(); success.render();
  assert.equal(success.timers.size, 1); success.unmount();
  assert.equal(success.timers.size, 0);
  assert.ok([...events.values()].every((listeners) => listeners.size === 0));
});

test("active 401 invalidates the session once, redirects, and removes booking and financial data", async () => {
  const h = harness({ readQuote: async () => { throw new ApiError(401); } });
  const page = harness({ page: true, session: h.auth });
  await openPage(page); fill(h); h.submit(); await tick();
  assert.equal(h.render().html, "");
  const view = page.render();
  assert.equal(h.auth.status, "unauthenticated");
  assert.equal(h.calls.filter((c) => c.operation === "invalidate").length, 1);
  assert.ok(h.navigation.includes("/login")); assert.match(view.html, /Redirecting to sign in/);
  assert.doesNotMatch(view.html, /Synthetic Hotel|Quoted Hotel|Financial summary|226\.80|284\.63/);
});

test("logout removes both pending and successful reviews and ignores a later protected response", async (t) => {
  for (const ready of [false, true]) {
    await t.test(ready ? "successful review" : "pending review", async () => {
      const pending = deferred(); const h = harness({ readQuote: () => pending.promise });
      const page = harness({ page: true, session: h.auth });
      await openPage(page); fill(h); h.submit();
      if (ready) { pending.resolve(quote()); await tick(); h.render(); }
      h.auth.status = "unauthenticated"; let view = h.render(); const before = h.writes.length;
      if (!ready) { pending.resolve(quote()); await tick(); view = h.render(); }
      assert.equal(h.writes.length, before); assert.equal(h.timers.size, 0);
      assert.doesNotMatch(view.html, /Synthetic Hotel|Quoted Hotel|Financial summary|284\.63/);
      assert.equal(view.html, "");
      assert.match(page.render().html, /Redirecting to sign in/);
    });
  }
});

test("unauthenticated or restoring standalone forms render no protected content or requests", () => {
  for (const status of ["restoring", "unauthenticated"]) {
    const h = harness({ status }); assert.equal(h.render().html, ""); assert.deepEqual(h.calls, []);
  }
});

test("reservation prop changes reset quote and all reconfirmation fields immediately", async () => {
  const h = harness(); fill(h); h.submit(); await tick(); h.render();
  const view = h.render({ reservationId: 43, checkInDate: "2096-04-01", checkOutDate: "2096-04-03" });
  assert.equal(view.input("q").props.value, ""); assert.equal(view.input("adults").props.value, "");
  assert.equal(view.input("check_in_date").props.value, "2096-04-01");
  assert.doesNotMatch(view.html, /Quoted Hotel|284\.63/); assert.equal(h.timers.size, 0);
  assert.equal(quoteCalls(h).length, 1);
});

test("synthetic quote success leaves the dormant booking page, payment links, and cancellation behavior unchanged", async () => {
  const page = harness({ page: true, pendingPayment: true });
  const before = await openPage(page);
  const h = harness(); fill(h); h.submit(); await tick();
  assert.equal(h.render().rows.get("LikeHome payment amount (including tax)"), "$284.63");
  let view = page.render();
  assert.equal(view.html, before.html);
  assert.match(view.html, /Synthetic property description/);
  assert.doesNotMatch(view.html, /Financial summary|Request a change quote|Price quote \(USD\)/);
  const links = view.nodes.filter((n) => n.type === "a" && text(n) === "Complete payment");
  assert.equal(links.length, 2); assert.equal(links[0].props.href, paymentHref(142));
  assert.equal(view.buttons("Cancel booking").length, 2);
  assert.equal(page.calls.some((c) => c.operation === "cancellation"), false);
  assert.deepEqual(page.calls.map((c) => c.operation), ["bookings", "payments", "details"]);
  assert.deepEqual(h.calls.map((c) => c.operation), ["quote"]);
  view.buttons("Cancel booking")[0].props.onClick(); view = page.render();
  assert.equal(view.buttons("Confirm cancellation").length, 1);
  view.buttons("Confirm cancellation")[0].props.onClick(); await tick(); view = page.render();
  assert.equal(page.calls.filter((c) => c.operation === "cancellation").length, 1);
  assert.equal(page.calls.filter((c) => c.operation === "payments").length, 2);
  assert.match(view.html, /Cancellation recorded/); assert.doesNotMatch(view.html, /Price quote \(USD\)/);
});

test("synthetic quote failure leaves the dormant booking page and existing controls intact", async () => {
  const page = harness({ page: true, pendingPayment: true });
  const before = await openPage(page);
  const h = harness({ readQuote: async () => { throw new ApiError(409); } });
  fill(h); h.submit(); await tick();
  assert.match(h.render().html, /has changed or cannot support/);
  const view = page.render();
  assert.equal(view.html, before.html);
  assert.match(view.html, /Synthetic property description/);
  assert.equal(view.buttons("Cancel booking").length, 2); assert.equal(view.buttons("Hide details").length, 1);
  assert.equal(view.nodes.filter((n) => n.type === "a" && text(n) === "Complete payment").length, 2);
  assert.deepEqual(page.calls.map((c) => c.operation), ["bookings", "payments", "details"]);
  assert.deepEqual(h.calls.map((c) => c.operation), ["quote"]);
});

test("form markup has labelled required inputs, accessible errors, responsive widths, and practical touch targets", async () => {
  const h = harness(); const view = fill(h);
  for (const node of view.nodes.filter((n) => n.type === "input")) {
    assert.equal(node.props.required, true);
    assert.match(node.props.className, /min-h-11/); assert.match(node.props.className, /w-full min-w-0 max-w-full/);
  }
  assert.equal(view.input("adults").props.min, 1); assert.equal(view.input("children").props.min, 0);
  assert.equal(view.input("adults").props.step, 1); assert.equal(view.input("children").props.max, 20);
  assert.match(view.html, /sm:grid-cols-2/); assert.match(view.html, /min-w-0/);
  assert.equal(view.form.props["aria-label"], "Reservation change quote");
  assert.equal(view.nodes.filter((n) => n.type === "input").length, 5);
  assert.match(view.buttons("Request a quote")[0].props.className, /min-h-11/);
  assert.doesNotMatch(view.html, /<table|min-w-\[|w-\[[0-9]|overflow-x|name="currency"|name="gl"|name="hl"/);
});
