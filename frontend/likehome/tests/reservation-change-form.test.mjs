import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { afterEach, beforeEach, test } from "node:test";
import { cloneElement, createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

import { ApiError } from "../lib/api.ts";
import * as cancellation from "../lib/booking-cancellation.ts";
import { bookingPaymentForReservation, paymentHref } from "../lib/payment.ts";
import { changeReservationDates } from "../lib/bookings.ts";

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
  assert.deepEqual(persistence, [], "booking and auth data must not be persisted by the form");
  assert.deepEqual(logs, [], "booking and auth data must not be logged");
  for (const h of harnesses) {
    assert.equal(h.calls.some((call) => ["confirmation", "settlement", "payment"].includes(call.operation)), false);
    if (!h.page) assert.ok(h.calls.every((call) => ["save", "invalidate"].includes(call.operation)));
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

const newDates = { check_in_date: "2096-03-02", check_out_date: "2096-03-04" };

function saved(id, request) {
  return {
    ...request, reservation_id: id, booking_reference: "LH-" + String(id).padStart(8, "0"),
    payment_id: id + 100, total_price: 200, payment_amount: 216, changed: true,
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
  saveDates = async (id, request) => saved(id, request) } = {}) {
  const instances = new Map(), timers = new Map();
  const calls = [], navigation = [], writes = [];
  let currentBookings = records, currentPayments;
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
    changeReservationDates: (id, request) => { calls.push({ operation: "save", id, request }); return saveDates(id, request); },
    getReservationFinancialSummary: async (id) => { calls.push({ operation: "summary", id }); return summary(id); },
    getMyBookings: async () => { calls.push({ operation: "bookings" }); return currentBookings; },
    getMyPayments: async () => { calls.push({ operation: "payments" }); return currentPayments ?? currentBookings.map((b) => ({
      ...summary(b.reservation_id).original_booking_payment, payment_status: pendingPayment ? "pending" : "paid",
    })); },
    getBookingDetails: async (id) => { calls.push({ operation: "details", id }); return records.find((b) => b.reservation_id === id); },
    getCancellationCharge: async (id) => {
      calls.push({ operation: "cancellation-charge", id });
      return { cancellation_charge: 20 };
    },
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

  imports["@/components/CancelBookingDialog"] = {
    default: loadComponent("../components/CancelBookingDialog.tsx", imports, clock),
  };
  const Form = loadComponent("../components/ReservationChangeForm.tsx", imports, clock);
  const Flow = loadComponent(
      "../components/ReservationChangeFlow.tsx",
      {
        ...imports,
        "@/components/ReservationChangeForm": {
          default: Form,
        },
      },
      clock
  );

  imports["@/components/ReservationChangeFlow"] = {
    default: Flow,
  };
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
    refreshTo(bookings, payments) { currentBookings = bookings; currentPayments = payments; },
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


const saveCalls = (h) => h.calls.filter((call) => call.operation === "save");

test("prefills exactly two labeled date inputs and retains the responsive form layout", () => {
  const h = harness();
  const view = h.render();
  assert.equal(view.input("check_in_date").props.value, "2096-02-28");
  assert.equal(view.input("check_out_date").props.value, "2096-03-01");
  const inputs = view.nodes.filter((node) => node.type === "input");
  assert.deepEqual(inputs.map((input) => input.props.name), ["check_in_date", "check_out_date"]);
  assert.ok(inputs.every((input) => input.props.type === "date" && input.props.required));
  assert.equal(view.nodes.filter((node) => node.type === "label").length, 2);
  assert.match(view.html, /sm:grid-cols-2/);
  assert.match(view.buttons("Save reservation changes")[0].props.className, /min-h-11/);
  assert.doesNotMatch(view.html, /Request a quote|Adults|Children|Destination/);
  assert.equal(saveCalls(h).length, 0);
});

test("one explicit save uses only dates and renders committed dates and amounts", async () => {
  const h = harness();
  h.render();
  h.edit("check_in_date", newDates.check_in_date);
  h.edit("check_out_date", newDates.check_out_date);
  const view = h.submit();
  assert.equal(view.form.props["aria-busy"], true);
  h.submit();
  assert.deepEqual(saveCalls(h), [{ operation: "save", id: 42, request: newDates }]);
  assert.doesNotMatch(view.html, /Reservation dates saved/);
  await tick();
  assert.match(h.render().html, /Reservation dates saved[\s\S]*LH-00000042[\s\S]*2096-03-04[\s\S]*\$200.00[\s\S]*\$216.00/);
});

test("invalid calendar, past or non-increasing dates cannot reach the API", async () => {
  for (const date of ["2000-01-01", "2096-02-30", "2096-03-01", "2096-3-01"]) {
    const h = harness({ saveDates: changeReservationDates });
    h.render();
    h.edit("check_in_date", date);
    h.submit();
    await tick();
    const view = h.render();
    assert.equal(view.input("check_in_date").props.value, date);
    assert.match(view.html, /role="alert"/);
    assert.match(view.html, /Enter valid check-in and check-out dates/);
    assert.match(view.form.props["aria-describedby"], /change-dates-error-42/);
  }
});

test("active 401 redirects once while an unmounted save ignores the response", async () => {
  const first = harness({ saveDates: async () => { throw new ApiError(401); } });
  first.render(); first.submit(); await tick();
  assert.deepEqual(first.navigation, ["/login"]);
  const pending = deferred();
  const next = harness({ saveDates: () => pending.promise });
  next.render(); next.submit(); next.show(false);
  pending.reject(new ApiError(401));
  await tick();
  assert.deepEqual(next.navigation, []);
  assert.equal(next.writes.some((entry) => !entry.mounted), false);
});

test("MyBookings preserves original booking after a rejected save and refreshes after committed save", async () => {
  const pending = deferred();
  const h = harness({ page: true, pendingPayment: true, saveDates: () => pending.promise });
  h.render(); await tick();
  h.render().buttons("Change Booking")[0].props.onClick();
  h.edit("check_in_date", newDates.check_in_date);
  h.edit("check_out_date", newDates.check_out_date);
  h.submit();
  assert.match(h.render().html, /2096-02-28/);

  const result = saved(42, newDates);
  const updated = [{ ...bookings[0], ...newDates, total_price: result.total_price }, ...bookings.slice(1)];
  h.refreshTo(updated, updated.map((booking) => ({
    ...summary(booking.reservation_id).original_booking_payment,
    amount: booking.reservation_id === 42 ? result.payment_amount : 226.8,
    payment_status: "pending",
  })));
  pending.resolve(result);
  await tick();
  const view = h.render();
  assert.match(view.html, /Reservation dates saved/);
  assert.match(view.html, /<time dateTime="2096-03-02">2096-03-02<\/time>/);
  assert.equal(h.calls.filter((call) => call.operation === "bookings").length, 2);
  assert.equal(h.calls.filter((call) => call.operation === "payments").length, 2);
  assert.equal(view.buttons("Cancel booking").length, 2);
  assert.match(view.html, /href="\/payment\/142"/);
  view.buttons("Cancel booking")[0].props.onClick();
  h.render(); await tick();
  const dialog = h.render();
  assert.match(dialog.html, /Cancel this booking[?]/);
  assert.match(dialog.html, /Cancellation charge: <strong>20.00 USD/);
  dialog.buttons("Keep booking")[0].props.onClick();
  assert.doesNotMatch(h.render().html, /Cancel this booking[?]/);
  assert.equal(h.calls.filter((call) => call.operation === "cancellation").length, 0);

  const rejected = harness({ page: true, saveDates: async () => { throw new ApiError(409, "dates_overlap"); } });
  rejected.render(); await tick();
  rejected.render().buttons("Change Booking")[0].props.onClick();
  rejected.edit("check_in_date", newDates.check_in_date);
  rejected.edit("check_out_date", newDates.check_out_date);
  rejected.submit(); await tick();
  const original = rejected.render();
  assert.match(original.html, /These dates overlap with another reservation. Please select different dates./);
  assert.match(original.html, /<time dateTime="2096-02-28T00:00:00">2096-02-28<\/time>/);
  assert.doesNotMatch(original.html, /Reservation dates saved/);
  assert.equal(rejected.calls.filter((call) => call.operation === "bookings").length, 1);
});

test("refresh failure preserves the committed acknowledgement without another save", async () => {
  const h = harness();
  h.render({ reservationId: 42, checkInDate: newDates.check_in_date, checkOutDate: newDates.check_out_date,
    onDatesSaved: async () => { throw new Error("read failed"); } });
  h.submit();
  await tick();
  const view = h.render();
  assert.match(view.html, /Reservation dates saved/);
  assert.match(view.html, /Reload MyBookings to refresh/);
  assert.equal(saveCalls(h).length, 1);
});

test("mount, rerender, focus and visibility changes never submit dates", async () => {
  const h = harness();
  h.render();
  h.fire("window", "focus");
  h.fire("document", "visibilitychange");
  h.render();
  await tick();
  assert.deepEqual(h.calls, []);
  assert.deepEqual(h.navigation, []);
});

test("restoring or signed-out sessions show no date form and make no save request", () => {
  for (const status of ["restoring", "unauthenticated"]) {
    const h = harness({ status, saveDates: changeReservationDates });
    assert.equal(h.render().form, undefined);
    assert.deepEqual(h.calls, []);
    assert.doesNotMatch(h.render().html, /2096-02-28|LH-00000042/);
  }
});

test("missing stored authentication rejects a valid date save before fetch", async () => {
  await assert.rejects(changeReservationDates(42, newDates), (error) =>
    error instanceof ApiError && error.status === 401);
});

test("logout drops a pending save and hides private dates when its success arrives", async () => {
  const pending = deferred();
  const acknowledgements = [];
  const h = harness({ saveDates: () => pending.promise });
  h.auth.user = { user_id: 1 };
  h.render({ reservationId: 42, checkInDate: "2096-02-28", checkOutDate: "2096-03-01",
    onDatesSaved: async (value) => acknowledgements.push(value) });
  h.edit("check_in_date", newDates.check_in_date);
  h.edit("check_out_date", newDates.check_out_date);
  h.submit();
  h.auth.user = null;
  h.auth.status = "unauthenticated";
  assert.equal(h.render().form, undefined);
  pending.resolve(saved(42, newDates));
  await tick();
  assert.doesNotMatch(h.render().html, /Reservation dates saved|LH-00000042/);
  assert.deepEqual(acknowledgements, []);
  assert.equal(h.writes.some((entry) => !entry.mounted), false);
});

test("switching reservations drops an old 401 and initializes the new reservation dates", async () => {
  const pending = deferred();
  const h = harness({ saveDates: () => pending.promise });
  h.render();
  h.submit();
  const current = h.render({ reservationId: 43, checkInDate: "2096-05-02", checkOutDate: "2096-05-04" });
  assert.equal(current.input("check_in_date").props.value, "2096-05-02");
  assert.equal(current.input("check_out_date").props.value, "2096-05-04");
  pending.reject(new ApiError(401));
  await tick();
  assert.deepEqual(h.navigation, []);
  assert.equal(h.writes.some((entry) => !entry.mounted), false);
  assert.equal(h.render().input("check_in_date").props.value, "2096-05-02");
});

test("account switching while saving immediately hides the previous MyBookings rows", async () => {
  const pending = deferred();
  const h = harness({ page: true, pendingPayment: true, saveDates: () => pending.promise });
  h.auth.user = { user_id: 1 };
  h.render(); await tick();
  h.render().buttons("Change Booking")[0].props.onClick();
  h.submit();
  h.refreshTo([{ ...bookings[1], hotel_name: "Second customer hotel" }]);
  h.auth.user = { user_id: 2 };
  const switching = h.render();
  assert.doesNotMatch(switching.html, /Synthetic Hotel|Save reservation changes/);
  pending.reject(new ApiError(401));
  await tick();
  const secondAccount = h.render();
  assert.match(secondAccount.html, /Second customer hotel/);
  assert.doesNotMatch(secondAccount.html, /Synthetic Hotel|LH-00000042/);
  assert.deepEqual(h.navigation, []);
});

test("a late post-save refresh cannot replace another account's MyBookings", async () => {
  const response = deferred();
  const h = harness({ page: true, pendingPayment: true });
  h.auth.user = { user_id: 1 };
  h.render(); await tick();
  h.render().buttons("Change Booking")[0].props.onClick();
  h.refreshTo(response.promise, []);
  h.submit(); await tick();
  assert.match(h.render().html, /Reservation dates saved/);

  h.refreshTo([{ ...bookings[1], hotel_name: "Replacement account hotel" }]);
  h.auth.user = { user_id: 2 };
  h.render(); await tick();
  response.resolve(bookings);
  await tick();
  const newAccount = h.render();
  assert.match(newAccount.html, /Replacement account hotel/);
  assert.doesNotMatch(newAccount.html, /Synthetic Hotel|Reservation dates saved|LH-00000042/);
  assert.equal(h.writes.some((entry) => !entry.mounted), false);
});

test("date save rejects malformed and mismatched API acknowledgements", async () => {
  window.sessionStorage.getItem = () => "synthetic-auth-secret";
  const good = saved(42, newDates);
  const responses = [
    null, { ...good, booking_reference: "LH-00000043" }, { ...good, reservation_id: 43 },
    { ...good, check_in_date: "2096-03-03" }, { ...good, payment_id: 0 },
    { ...good, changed: "true" }, { ...good, total_price: 200.005 },
    { ...good, payment_amount: undefined },
  ];
  for (const response of responses) {
    const requests = [];
    globalThis.fetch = async (url, init) => {
      requests.push({ path: new URL(url).pathname, method: init.method,
        bearer: init.headers.Authorization, body: JSON.parse(init.body) });
      return Response.json(response);
    };
    await assert.rejects(changeReservationDates(42, newDates), /unexpected response/);
    assert.deepEqual(requests, [{ path: "/bookings/42/change-dates", method: "POST",
      bearer: "Bearer synthetic-auth-secret", body: newDates }]);
  }
  globalThis.fetch = async () => new Response("invalid JSON");
  await assert.rejects(changeReservationDates(42, newDates), /invalid JSON response/);
});

test("an uncertain network failure keeps the entered dates and requires another explicit save", async () => {
  window.sessionStorage.getItem = () => "synthetic-auth-secret";
  const requests = [];
  globalThis.fetch = async (_url, init) => {
    requests.push(JSON.parse(init.body));
    throw new TypeError("synthetic internal network details");
  };
  const h = harness({ saveDates: changeReservationDates });
  h.render();
  h.edit("check_in_date", newDates.check_in_date);
  h.edit("check_out_date", newDates.check_out_date);
  h.submit();
  await tick();
  h.fire("window", "focus");
  h.fire("document", "visibilitychange");
  await tick();
  const failed = h.render();
  assert.match(failed.html, /We could not confirm whether your dates were saved. Reload MyBookings/);
  assert.doesNotMatch(failed.html, /synthetic internal network details|Reservation dates saved/);
  assert.equal(failed.input("check_in_date").props.value, newDates.check_in_date);
  assert.equal(failed.input("check_out_date").props.value, newDates.check_out_date);
  assert.deepEqual(requests, [newDates]);
});

test("a save response cannot overwrite another reservation's pending payment", async () => {
  const h = harness({ page: true, pendingPayment: true, saveDates: async (id, request) =>
    ({ ...saved(id, request), payment_id: 143 }) });
  h.render(); await tick();
  h.render().buttons("Change Booking")[0].props.onClick();
  h.refreshTo(Promise.reject(new Error("refresh unavailable")), []);
  h.submit(); await tick();
  const view = h.render();
  assert.doesNotMatch(view.html, /216.00 USD/);
  assert.match(view.html, /226.80 USD/);
});
