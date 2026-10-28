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
  assert.deepEqual(persistence, [], "quotes and auth secrets must not be persisted by confirmation");
  assert.deepEqual(logs, [], "quotes and auth secrets must not be logged");
  for (const h of harnesses) {
    assert.equal(h.calls.some((call) => ["quote", "settlement", "payment"].includes(call.operation)), false);
    if (!h.page) assert.ok(h.calls.every((call) => ["confirm", "current-read", "invalidate"].includes(call.operation)));
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
  reviewedQuote = quote(), acceptedRequest = accepted(reviewedQuote), readConfirm = async (id, request) => receipt(id, request),
  readCurrent = async () => {}, enableRefresh = true } = {}) {
  const instances = new Map(), timers = new Map();
  const calls = [], navigation = [], writes = [];
  let current, pendingEffects, seen, disposed = false, time = Date.now(), timerId = 0, rendering = false, renderDirty = false;
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
        if (rendering) renderDirty = true;
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
    confirmReservationChange: (id, request) => { calls.push({ operation: "confirm", id, request }); return readConfirm(id, request); },
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
  for (const [name, operation] of Object.entries({ getReservationChangeQuote: "quote",
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
  const Confirmation = loadComponent("../components/ReservationChangeConfirmation.tsx", imports, clock);
  // Only this synthetic boundary mounts confirmation. The actual current
  // booking page is tested separately and must never acquire a form import.
  function ReviewFixture({ visible = true, ...formProps }) {
    return visible ? createElement(Confirmation, formProps) : null;
  }
  const Root = page ? loadComponent("../components/MyBookingsExperience.tsx", imports, clock) : ReviewFixture;
  let props = { reservationId: reviewedQuote.reservation_id, reviewedQuote, acceptedRequest,
    ...(enableRefresh ? { onRefreshCurrent: (id) => { calls.push({ operation: "current-read", id }); return readCurrent(id); } } : {}) };

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
      props = nextProps;
      let tree, renders = 0;
      do {
        assert.ok(++renders < 10, "render-phase state must stabilize");
        seen = new Set(); pendingEffects = []; renderDirty = false; rendering = true;
        tree = renderComponent(Root, props, "root");
        rendering = false;
      } while (renderDirty);
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
    get props() { return props; },
    accept(checked = true) { h.render().input("accept_quote").props.onChange({ target: { checked } }); return h.render(); },
    click(label) { h.render().buttons(label)[0].props.onClick(); return h.render(); },
    replaceQuote(value, request = accepted(value)) { return h.render({ ...props, reviewedQuote: value, acceptedRequest: request }); },
    show(visible) { return h.render({ ...props, visible }); },
    unmount() { if (!disposed) { instances.forEach(unmount); instances.clear(); disposed = true; } },
  };
  harnesses.push(h);
  return h;
}

function accepted(review) {
  return { check_in_date: review.quote.check_in_date, check_out_date: review.quote.check_out_date,
    quote_id: review.quote_id, accept_quote: true, price_per_night: review.quote.current_price_per_night,
    accepted_payment_amount: review.quote.likehome_payment_amount };
}

function receipt(id = 42, request = {}, adjustment = null) {
  return { change_id: 7, reservation_id: id, revision: 1, room_type_id: 91,
    check_in_date: request.check_in_date ?? "2096-02-28", check_out_date: request.check_out_date ?? "2096-03-01",
    reservation_total: "263.55", payment_obligation: "284.63", previous_payment_obligation: "226.80",
    payment_difference: "57.83", booking_payment_id: 142, booking_payment_status: adjustment ? "paid" : "pending", adjustment };
}

const confirms = (h) => h.calls.filter((call) => call.operation === "confirm");
function confirm(h) { return h.click("Confirm reservation change"); }
function changedQuote(review = quote()) {
  return { ...review, quote_id: "synthetic-signed-secret-replacement",
    quote: { ...review.quote, current_price_per_night: 150.25, likehome_payment_amount: 340.77 } };
}

test("module import alone starts no hook, timer, network request, storage write, or navigation", () => {
  const unexpected = () => { assert.fail("import must not perform confirmation work"); };
  const component = loadComponent("../components/ReservationChangeConfirmation.tsx", {
    react: { useEffect: unexpected, useRef: unexpected, useState: unexpected },
    "next/navigation": { useRouter: unexpected }, "@/components/AuthProvider": { useAuth: unexpected },
    "@/lib/api": { ApiError }, "@/lib/bookings": { confirmReservationChange: unexpected },
  }, { Date, setTimeout: unexpected, clearTimeout: unexpected });
  assert.equal(typeof component, "function"); assert.equal(events.size, 0);
});

test("only ReservationChangeFlow directly imports confirmation and confirmation uses its adapter", () => {
  const references = [];
  function inspect(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const path = new URL(entry.name + (entry.isDirectory() ? "/" : ""), directory);
      if (entry.isDirectory()) inspect(path);
      else if (/\.(?:[cm]?[jt]sx?)$/.test(entry.name) && entry.name !== "ReservationChangeConfirmation.tsx" &&
        /ReservationChangeConfirmation|reservation-change-confirmation-ui/.test(readFileSync(path, "utf8"))) references.push(path.pathname);
    }
  }
  for (const directory of ["app", "components", "lib", "constants"]) inspect(new URL(`../${directory}/`, import.meta.url));
  assert.deepEqual(
      references.map((path) => path.split("/").pop()),
      ["ReservationChangeFlow.tsx"]
  );
  const source = readFileSync(new URL("../components/ReservationChangeConfirmation.tsx", import.meta.url), "utf8");
  const parsed = ts.createSourceFile("ReservationChangeConfirmation.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const adapters = parsed.statements.filter((node) => ts.isImportDeclaration(node) && node.moduleSpecifier.text === "@/lib/bookings")
    .flatMap((node) => node.importClause.namedBindings.elements.map((name) => name.name.text));
  assert.deepEqual(adapters, ["confirmReservationChange"]);
  assert.doesNotMatch(source, /payReservationChangeAdjustment|payBookingPayment|cancelBooking|localStorage|sessionStorage/);
});

test("acceptance and a separate confirmation action are required; mount, rerenders, and replacement never confirm", async () => {
  const h = harness(); let view = h.render();
  assert.equal(view.input("accept_quote").props.checked, false);
  assert.equal(view.buttons("Confirm reservation change")[0].props.disabled, true);
  confirm(h); assert.equal(confirms(h).length, 0);
  view = h.accept(); assert.equal(view.buttons("Confirm reservation change")[0].props.disabled, false);
  h.accept(false); assert.equal(h.render().buttons("Confirm reservation change")[0].props.disabled, true);
  h.render(); h.fire("window", "focus"); h.fire("document", "visibilitychange"); await tick();
  h.replaceQuote(changedQuote()); assert.deepEqual(h.calls, []);
  assert.equal(h.render().input("accept_quote").props.checked, false);
  const standalone = harness({ enableRefresh: false }); standalone.accept(); confirm(standalone); await tick();
  assert.match(standalone.render().html, /Reservation change confirmed/);
  assert.deepEqual(standalone.calls.map((c) => c.operation), ["confirm"]);
});

test("confirmation sends the frozen exact snapshot once, disables conflicting actions, and consumes acceptance on success", async () => {
  const pending = deferred(); const h = harness({ readConfirm: () => pending.promise });
  const button = h.accept().buttons("Confirm reservation change")[0];
  button.props.onClick(); button.props.onClick(); let view = h.render();
  assert.match(view.html, /Confirming reservation change/); assert.equal(view.input("accept_quote"), undefined);
  assert.equal(view.buttons("Confirm reservation change").length, 0);
  assert.equal(confirms(h).length, 1); assert.equal(confirms(h)[0].id, 42);
  const request = confirms(h)[0].request;
  assert.deepEqual(request, { check_in_date: "2096-02-28", check_out_date: "2096-03-01",
    quote_id: "synthetic-signed-secret-42", accept_quote: true, price_per_night: 125.5, accepted_payment_amount: 284.63 });
  assert.ok(Object.isFrozen(request)); assert.notStrictEqual(request, h.props.acceptedRequest);
  assert.throws(() => { request.accepted_payment_amount = 1; }, TypeError);
  pending.resolve(receipt()); await tick(); view = h.render();
  assert.match(view.html, /Reservation change confirmed/); assert.equal(view.buttons("Confirm reservation change").length, 0);
  button.props.onClick(); assert.equal(confirms(h).length, 1);
  assert.deepEqual(h.calls.map((c) => c.operation), ["confirm", "current-read"]);
  assert.equal(h.calls.find((c) => c.operation === "current-read").id, 42);
});

test("accepted prices are displayed and submitted verbatim without recalculation or rounding", async () => {
  const reviewedQuote = quote(); reviewedQuote.quote.current_price_per_night = 125.005; reviewedQuote.quote.likehome_payment_amount = 284.635;
  const h = harness({ reviewedQuote });
  assert.equal(h.render().rows.get("Accepted nightly price"), "125.005 USD");
  assert.equal(h.render().rows.get("Accepted payment obligation (including tax)"), "284.635 USD");
  h.accept(); confirm(h); await tick();
  assert.equal(confirms(h)[0].request.price_per_night, 125.005); assert.equal(confirms(h)[0].request.accepted_payment_amount, 284.635);
});

test("replacing any displayed or accepted quote value clears acceptance and disables a captured old handler", async (t) => {
  const changes = {
    check_in_date: (q) => { q.quote.check_in_date = "2096-04-01"; },
    check_out_date: (q) => { q.quote.check_out_date = "2096-04-03"; },
    hotel: (q) => { q.quote.hotel_name = "Another reviewed hotel"; },
    adults: (q) => { q.quote.adults = 3; }, children: (q) => { q.quote.children = 0; },
    quote_id: (q) => { q.quote_id = "synthetic-signed-secret-new"; },
    expiry: (q) => { q.expires_at = new Date(Date.parse(q.expires_at) + 60000).toISOString(); },
    nightly_price: (q) => { q.quote.current_price_per_night = 200; },
    payment_amount: (q) => { q.quote.likehome_payment_amount = 400; },
    reservation_total: (q) => { q.quote.likehome_reservation_total = 300; },
  };
  for (const [name, change] of Object.entries(changes)) {
    await t.test(name, () => {
      const h = harness(); const old = h.accept().buttons("Confirm reservation change")[0];
      const replacement = structuredClone(h.props.reviewedQuote); change(replacement);
      const view = h.replaceQuote(replacement); old.props.onClick();
      assert.equal(confirms(h).length, 0); assert.equal(view.input("accept_quote").props.checked, false);
      assert.match(view.html, /The reviewed quote changed\. Review these values and accept again\./);
      assert.equal(view.buttons("Confirm reservation change")[0].props.disabled, true);
      assert.equal(h.timers.size, 1);
    });
  }
});

test("mismatched identity, dates, quote ID, prices, or acknowledgement cannot authorize a confirmation", async (t) => {
  const cases = {
    reservation: (p) => { p.reservationId = 43; }, quote_reservation: (p) => { p.reviewedQuote.reservation_id = 43; },
    check_in_date: (p) => { p.acceptedRequest.check_in_date = "2096-04-01"; },
    check_out_date: (p) => { p.acceptedRequest.check_out_date = "2096-04-03"; },
    quote_id: (p) => { p.acceptedRequest.quote_id = "different-signed-token"; },
    nightly_price: (p) => { p.acceptedRequest.price_per_night = 1; },
    payment_amount: (p) => { p.acceptedRequest.accepted_payment_amount = 1; },
    acceptance: (p) => { p.acceptedRequest.accept_quote = false; },
    extra_field: (p) => { p.acceptedRequest.extra = "not part of the public contract"; },
    malformed_expiry: (p) => { p.reviewedQuote.expires_at = "not a timestamp"; },
    invalid_identity: (p) => { p.reservationId = p.reviewedQuote.reservation_id = NaN; },
  };
  for (const [name, change] of Object.entries(cases)) {
    await t.test(name, () => {
      const h = harness(); const props = structuredClone({ reservationId: 42, reviewedQuote: h.props.reviewedQuote, acceptedRequest: h.props.acceptedRequest });
      change(props); const view = h.render(props);
      assert.match(view.html, /reviewed quote and accepted request do not match/);
      assert.equal(view.input("accept_quote"), undefined); assert.equal(view.buttons("Confirm reservation change").length, 0);
      assert.deepEqual(h.calls, []);
    });
  }
});

test("immediate expiry checks prevent a first submission even before the scheduled callback fires", () => {
  const h = harness(); const old = h.accept().buttons("Confirm reservation change")[0];
  h.jump(700000); old.props.onClick(); const view = h.render();
  assert.equal(confirms(h).length, 0); assert.match(view.html, /This quote has expired/);
  assert.equal(view.input("accept_quote"), undefined); assert.equal(view.buttons("Confirm reservation change").length, 0);
});

test("timer, focus, visibility, and already-expired quotes never trigger confirmation", async (t) => {
  for (const action of ["timer", "focus", "visibilitychange", "already-expired"]) {
    await t.test(action, () => {
      const h = harness({ reviewedQuote: quote(42, {}, action === "already-expired" ? Date.now() - 1 : Date.now() + 1000) });
      h.render();
      if (action !== "already-expired") {
        h.accept();
        if (action === "timer") h.advance(1001);
        else { h.jump(1001); h.fire(action === "focus" ? "window" : "document", action); }
      }
      assert.match(h.render().html, /This quote has expired/); assert.equal(confirms(h).length, 0);
      assert.equal(h.timers.size, 0);
    });
  }
});

test("success preserves historical receipt values and distinguishes pending charges and recorded credits from settlement", async (t) => {
  for (const adjustment of [null,
    { adjustment_id: 101, kind: "charge", amount: "57.83", status: "pending" },
    { adjustment_id: 102, kind: "credit", amount: "45.36", status: "recorded" },
  ]) {
    await t.test(adjustment?.kind ?? "none", async () => {
      const h = harness({ readConfirm: async (id, request) => {
        const value = receipt(id, request, adjustment);
        if (adjustment?.kind === "credit") { value.reservation_total = "168.00"; value.payment_obligation = "181.44"; value.payment_difference = "-45.36"; }
        return value;
      } });
      h.accept(); confirm(h); await tick(); const view = h.render();
      assert.match(view.html, /role="status"[^>]*>Reservation change confirmed/);
      assert.equal(view.rows.get("Confirmed reservation ID"), "42"); assert.equal(view.rows.get("Change ID"), "7");
      assert.equal(view.rows.get("Confirmed revision"), "1"); assert.equal(view.rows.get("Confirmed check-in"), "2096-02-28");
      assert.equal(view.rows.get("Confirmed check-out"), "2096-03-01"); assert.match(view.html, /historical confirmation receipt/);
      assert.equal(view.rows.get("Confirmed payment obligation (including tax)"), adjustment?.kind === "credit" ? "181.44 USD" : "284.63 USD");
      if (!adjustment) assert.match(view.html, /No adjustment was recorded at confirmation/);
      else if (adjustment.kind === "charge") { assert.match(view.html, /pending additional internal charge/); assert.match(view.html, /No separate payment was submitted/); }
      else { assert.match(view.html, /recorded internal credit/); assert.match(view.html, /not an external cash refund/); }
      assert.deepEqual(h.calls.map((c) => c.operation), ["confirm", "current-read"]);
      assert.doesNotMatch(view.html, /Pay adjustment|Settle charge|confirmation failed/i);
    });
  }
});

test("receipt decimal strings are rendered verbatim without floating-point conversion", async () => {
  const h = harness({ readConfirm: async (id, request) => ({ ...receipt(id, request),
    reservation_total: "9007199254740993.01", payment_obligation: "9007199254740993.09", payment_difference: "-0.01" }) });
  h.accept(); confirm(h); await tick(); const view = h.render();
  assert.equal(view.rows.get("Confirmed reservation total (before tax)"), "9007199254740993.01 USD");
  assert.equal(view.rows.get("Confirmed payment obligation (including tax)"), "9007199254740993.09 USD");
  assert.equal(view.rows.get("Payment difference at confirmation"), "-0.01 USD");
});

test("confirmed receipt survives a pending or failed authoritative refresh and read-only retry", async () => {
  const pending = deferred(); let attempts = 0;
  const h = harness({ readCurrent: () => ++attempts === 1 ? pending.promise : Promise.resolve() });
  h.accept(); confirm(h); await tick(); let view = h.render();
  assert.match(view.html, /Reservation change confirmed/); assert.match(view.html, /Reloading current booking and financial information/);
  assert.equal(view.buttons("Check current booking information")[0].props.disabled, true);
  pending.reject(new Error("private refresh payload")); await tick(); view = h.render();
  assert.match(view.html, /Your confirmed receipt is preserved/); assert.doesNotMatch(view.html, /private refresh payload|Confirmation status uncertain/);
  const retry = view.buttons("Retry current booking refresh")[0]; retry.props.onClick(); retry.props.onClick();
  await tick(); view = h.render();
  assert.match(view.html, /information reloaded/); assert.equal(confirms(h).length, 1);
  assert.equal(view.rows.get("Confirmed payment obligation (including tax)"), "284.63 USD");
  assert.equal(h.calls.filter((c) => c.operation === "current-read").length, 2);
});

test("network, server, and malformed-success outcomes remain uncertain without automatic retry, re-quote, or read", async (t) => {
  for (const error of [new TypeError("private network data"), new ApiError(500), new ApiError(502), new ApiError(504),
    new Error("Reservation change confirmation returned an unexpected response"), new Error("API returned an invalid JSON response")]) {
    await t.test(error instanceof ApiError ? String(error.status) : error.message, async () => {
      const h = harness({ readConfirm: async () => { throw error; } });
      h.accept(); confirm(h); await tick(); let view = h.render();
      assert.match(view.html, /Confirmation status uncertain/); assert.match(view.html, /reservation may already have changed/);
      assert.doesNotMatch(view.html, /change failed|private network data|API request failed|unexpected response|invalid JSON/);
      assert.equal(view.input("accept_quote"), undefined); assert.equal(view.buttons("Confirm reservation change").length, 0);
      h.render(); h.fire("window", "focus"); h.fire("document", "visibilitychange"); await tick(); view = h.render();
      assert.deepEqual(h.calls.map((c) => c.operation), ["confirm"]);
      assert.equal(view.buttons("Retry identical confirmation").length, 1);
      h.click("Check current booking information"); await tick(); view = h.render();
      assert.match(view.html, /Confirmation status uncertain/); assert.match(view.html, /does not establish whether this exact request committed/);
      assert.equal(confirms(h).length, 1);
    });
  }
});

test("explicit identical retry preserves the same frozen request after quote and stay expiry", async () => {
  const retry = deferred(); let attempts = 0;
  const h = harness({ readConfirm: () => ++attempts === 1 ? Promise.reject(new ApiError(504)) : retry.promise });
  h.accept(); confirm(h); await tick();
  const original = confirms(h)[0].request; assert.ok(Object.isFrozen(original));
  h.advance(Date.parse("2097-01-01T00:00:00Z") - h.now());
  const button = h.render().buttons("Retry identical confirmation")[0]; button.props.onClick(); button.props.onClick(); h.render();
  assert.equal(confirms(h).length, 2); assert.strictEqual(confirms(h)[1].request, original);
  assert.equal(confirms(h)[1].id, 42);
  retry.resolve(receipt(42, original)); await tick(); const view = h.render();
  assert.match(view.html, /Reservation change confirmed/); button.props.onClick();
  assert.equal(confirms(h).length, 2); assert.equal(h.calls.filter((c) => c.operation === "current-read").length, 1);
});

test("caller mutation and new quotes cannot replace or recalculate an in-flight or uncertain accepted snapshot", async () => {
  const pending = deferred(); let attempts = 0;
  const h = harness({ readConfirm: (id, request) => ++attempts === 1 ? pending.promise : Promise.resolve(receipt(id, request)) });
  h.accept(); confirm(h); const original = confirms(h)[0].request;
  h.props.acceptedRequest.price_per_night = 999; h.props.acceptedRequest.quote_id = "caller-mutated-token";
  h.props.reviewedQuote.quote.likehome_payment_amount = 999;
  h.render(); h.replaceQuote(changedQuote());
  assert.equal(h.render().rows.get("Accepted nightly price"), "125.5 USD");
  assert.equal(h.render().rows.get("Accepted payment obligation (including tax)"), "284.63 USD");
  assert.equal(original.price_per_night, 125.5); assert.equal(original.quote_id, "synthetic-signed-secret-42");
  pending.reject(new ApiError(504)); await tick();
  assert.match(h.render().html, /Confirmation status uncertain/);
  assert.equal(h.render().input("accept_quote"), undefined);
  h.click("Retry identical confirmation"); await tick();
  assert.strictEqual(confirms(h)[1].request, original); assert.equal(confirms(h)[1].id, confirms(h)[0].id);
  assert.match(h.render().html, /Reservation change confirmed/);
});

test("current-information reads prevent a conflicting retry and duplicate reads while pending", async () => {
  const read = deferred(); const h = harness({ readConfirm: async () => { throw new ApiError(500); }, readCurrent: () => read.promise });
  h.accept(); confirm(h); await tick(); let view = h.render();
  const retry = view.buttons("Retry identical confirmation")[0], check = view.buttons("Check current booking information")[0];
  check.props.onClick(); check.props.onClick(); retry.props.onClick(); view = h.render();
  assert.equal(view.buttons("Retry identical confirmation")[0].props.disabled, true);
  assert.equal(confirms(h).length, 1); assert.equal(h.calls.filter((c) => c.operation === "current-read").length, 1);
  read.resolve(); await tick(); assert.match(h.render().html, /Confirmation status uncertain/);
});

test("definitive errors discard acceptance and require explicit fresh review without automatic activity", async (t) => {
  for (const [status, message] of [[400, /cannot be accepted as reviewed/], [422, /cannot be accepted as reviewed/],
    [404, /unavailable or cannot be accessed/], [409, /may conflict/]]) {
    await t.test(String(status), async () => {
      const h = harness({ readConfirm: async () => { throw new ApiError(status); } });
      h.accept(); confirm(h); await tick(); let view = h.render();
      assert.match(view.html, message); assert.match(view.html, /role="alert"/);
      assert.equal(view.input("accept_quote"), undefined); assert.equal(view.buttons("Retry identical confirmation").length, 0);
      assert.deepEqual(h.calls.map((c) => c.operation), ["confirm"]);
      h.replaceQuote(changedQuote()); assert.equal(h.render().input("accept_quote"), undefined);
      view = h.click("Review updated quote");
      assert.equal(view.input("accept_quote").props.checked, false); assert.equal(confirms(h).length, 1);
      assert.equal(view.buttons("Confirm reservation change")[0].props.disabled, true);
    });
  }
});

test("active 401 invalidates the shared session once, hides protected content, and redirects", async () => {
  const h = harness({ readConfirm: async () => { throw new ApiError(401); } });
  const page = harness({ page: true, session: h.auth }); page.render(); await tick(); page.render();
  h.accept(); confirm(h); await tick(); assert.equal(h.render().html, "");
  assert.equal(h.auth.status, "unauthenticated"); assert.deepEqual(h.navigation, ["/login"]);
  assert.equal(h.calls.filter((c) => c.operation === "invalidate").length, 1);
  const view = page.render(); assert.match(view.html, /Redirecting to sign in/);
  assert.doesNotMatch(view.html, /Synthetic Hotel|Financial summary|284\.63|Confirmed revision/);
});

test("401 during a post-confirmation read hides the receipt without treating confirmation as rejected", async () => {
  const h = harness({ readCurrent: async () => { throw new ApiError(401); } });
  h.accept(); confirm(h); await tick(); assert.equal(h.render().html, "");
  assert.equal(h.auth.status, "unauthenticated"); assert.deepEqual(h.navigation, ["/login"]);
  assert.equal(confirms(h).length, 1);
});

test("unauthenticated and restoring instances perform no work or expose protected quotes", () => {
  for (const status of ["unauthenticated", "restoring"]) {
    const h = harness({ status }); assert.equal(h.render().html, ""); assert.deepEqual(h.calls, []);
  }
});

test("parent removal, reservation switch, logout, and unmount ignore late success or 401 without reads or reopening", async (t) => {
  for (const action of ["close", "collapse", "switch", "logout", "unmount"]) {
    for (const late401 of [false, true]) {
      await t.test(`${action}: ${late401 ? "401" : "success"}`, async () => {
        const pending = deferred(); const h = harness({ readConfirm: () => pending.promise });
        h.accept(); confirm(h);
        if (action === "close" || action === "collapse") h.show(false);
        if (action === "switch") { const q = quote(43); h.render({ ...h.props, reservationId: 43, reviewedQuote: q, acceptedRequest: accepted(q) }); }
        if (action === "logout") { h.auth.status = "unauthenticated"; h.render(); }
        if (action === "unmount") h.unmount();
        const before = h.writes.length, callsBefore = h.calls.length;
        if (late401) pending.reject(new ApiError(401)); else pending.resolve(receipt());
        await tick();
        assert.equal(h.writes.length, before); assert.equal(h.calls.length, callsBefore);
        assert.equal(h.calls.some((c) => c.operation === "invalidate"), false);
        if (action !== "unmount") assert.doesNotMatch(h.render().html, /Reservation change confirmed|Confirmation status uncertain/);
      });
    }
  }
});

test("closing an uncertain instance clears its retry reference and disables captured handlers after reopening", async () => {
  const h = harness({ readConfirm: async () => { throw new ApiError(504); } });
  h.accept(); confirm(h); await tick(); const old = h.render().buttons("Retry identical confirmation")[0];
  h.show(false); const view = h.show(true); old.props.onClick();
  assert.equal(confirms(h).length, 1); assert.equal(view.input("accept_quote").props.checked, false);
  assert.equal(view.buttons("Retry identical confirmation").length, 0);
});

test("unmount during refresh ignores late fulfillment and 401 without navigation or state writes", async (t) => {
  for (const late401 of [false, true]) {
    await t.test(late401 ? "401" : "success", async () => {
      const pending = deferred(); const h = harness({ readCurrent: () => pending.promise });
      h.accept(); confirm(h); await tick(); assert.match(h.render().html, /Reservation change confirmed/);
      h.unmount(); const writes = h.writes.length, calls = h.calls.length;
      if (late401) pending.reject(new ApiError(401)); else pending.resolve();
      await tick(); assert.equal(h.writes.length, writes); assert.equal(h.calls.length, calls); assert.deepEqual(h.navigation, []);
    });
  }
});

test("every authoritative read failure preserves the historical receipt with explicit recovery", async (t) => {
  for (const failure of ["bookings", "details", "payments", "summary"]) {
    await t.test(failure, async () => {
      const h = harness({ readCurrent: async () => { throw new Error(`private ${failure} error`); } });
      h.accept(); confirm(h); await tick(); const view = h.render();
      assert.match(view.html, /Reservation change confirmed/); assert.match(view.html, /Your confirmed receipt is preserved/);
      assert.doesNotMatch(view.html, /private .* error|Confirmation status uncertain/);
      assert.equal(view.buttons("Retry current booking refresh").length, 1); assert.equal(confirms(h).length, 1);
    });
  }
});

test("quote replacement after success preserves the receipt and never creates fresh confirmation controls", async () => {
  const h = harness(); h.accept(); confirm(h); await tick();
  h.replaceQuote(changedQuote()); const view = h.render();
  assert.equal(view.rows.get("Confirmed payment obligation (including tax)"), "284.63 USD");
  assert.equal(view.rows.get("Accepted payment obligation (including tax)"), "284.63 USD");
  assert.equal(view.input("accept_quote"), undefined); assert.equal(view.buttons("Confirm reservation change").length, 0);
  assert.equal(confirms(h).length, 1);
});

test("standalone confirmation cannot mutate or activate the existing booking page", async () => {
  const page = harness({ page: true, pendingPayment: true }); page.render(); await tick();
  page.render().buttons("View details")[0].props.onClick(); page.render(); await tick();
  const before = page.render(); const h = harness(); h.accept(); confirm(h); await tick();
  const after = page.render(); assert.equal(after.html, before.html);
  assert.equal(after.buttons("Cancel booking").length, 2);
  assert.equal(after.nodes.filter((n) => n.type === "a" && text(n) === "Complete payment").length, 2);
  assert.doesNotMatch(after.html, /Review confirmation|Reservation change confirmed|Confirm reservation change/);
  assert.deepEqual(page.calls.map((c) => c.operation), ["bookings", "payments", "details"]);
});

test("acceptance and receipts retain accessible labels and responsive wrapping without asserting browser layout", async () => {
  const q = quote(); q.quote.hotel_name = "A long reviewed hotel name ".repeat(8);
  const h = harness({ reviewedQuote: q }); let view = h.render();
  assert.equal(view.nodes.filter((n) => n.type === "label").length, 1);
  assert.match(view.html, /sm:grid-cols-2|min-w-0/); assert.match(view.html, /break-words/);
  assert.match(view.buttons("Confirm reservation change")[0].props.className, /min-h-11/);
  h.accept(); confirm(h); await tick(); view = h.render();
  assert.match(view.html, /historical confirmation receipt/); assert.doesNotMatch(view.html, /<table|min-w-\[|overflow-x/);
  assert.ok([...events.values()].every((listeners) => listeners.size === 0));
});
