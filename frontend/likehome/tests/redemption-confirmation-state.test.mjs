import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { test } from "node:test";
import { cloneElement, createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
import { ApiError } from "../lib/api.ts";
import * as routes from "../lib/booking-confirmation.ts";
import * as paymentLib from "../lib/payment.ts";
import * as redemption from "../lib/redemption-confirmation.ts";

const require = createRequire(import.meta.url);
const tick = () => new Promise(setImmediate);
const Link = ({ href, children, ...props }) => createElement("a", { href, ...props }, children);

function load(path, imports) {
  const { outputText } = ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  });
  const loaded = { exports: {} };
  new Function("require", "module", "exports", outputText)((name) => {
    if (name === "react/jsx-runtime") return require(name);
    if (Object.hasOwn(imports, name)) return imports[name];
    throw new Error("Unexpected dependency " + name);
  }, loaded, loaded.exports);
  return loaded.exports.default;
}

const State = load("../components/RedemptionConfirmationState.tsx", { "next/link": { default: Link } });
const show = (state) => renderToStaticMarkup(createElement(State, { state, onRefresh: () => {} }));
const booking = {
  reservation_id: 42, hotel_name: "First account hotel", room_type_name: "King room",
  hotel_address: "", hotel_phone: null, hotel_description: null, room_description: null,
  check_in_date: "2027-01-10", check_out_date: "2027-01-12", total_price: 283.50,
  price_per_night: 135, guest_full_name: "First Guest", guest_email: "first@example.com", status: "confirmed",
};
const paid = { reservation_id: 42, payment_id: 11, amount: 306.18, payment_type: "booking", payment_status: "paid" };

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function harness({ status = "authenticated", readBooking = async () => booking, readPayments = async () => [paid] } = {}) {
  const instances = new Map();
  const reads = [], redirects = [], lateWrites = [];
  let activeInstance, effects, visited, token = "first", invalidations = 0;
  const auth = {
    status, user: status === "authenticated" ? { user_id: 7 } : null,
    invalidateSession() {
      invalidations++;
      auth.status = "unauthenticated";
      auth.user = null;
      token = null;
    },
  };
  const router = { replace: (path) => redirects.push(path) };
  const hooks = {
    useState(initial) {
      const owner = activeInstance;
      const index = owner.index++;
      owner.slots[index] ??= { value: typeof initial === "function" ? initial() : initial };
      const slot = owner.slots[index];
      return [slot.value, (value) => {
        if (!owner.mounted) lateWrites.push(value);
        slot.value = typeof value === "function" ? value(slot.value) : value;
      }];
    },
    useEffect(effect, dependencies) {
      const owner = activeInstance;
      const index = owner.index++;
      owner.slots[index] ??= {};
      const slot = owner.slots[index];
      if (!slot.dependencies || dependencies.some((value, i) => !Object.is(value, slot.dependencies[i]))) {
        effects.push(() => { slot.cleanup?.(); slot.dependencies = dependencies; slot.cleanup = effect(); });
      }
    },
  };
  const Experience = load("../app/booking-confirmation/[reservationId]/booking-confirmation-experience.tsx", {
    react: hooks, "next/link": { default: Link }, "next/navigation": { useRouter: () => router },
    "@/components/AuthProvider": { useAuth: () => auth }, "@/lib/api": { ApiError },
    "@/lib/booking-confirmation": routes, "@/lib/payment": paymentLib,
    "@/lib/redemption-confirmation": redemption, "@/components/RedemptionConfirmationState": { default: State },
    "@/lib/token-storage": { getAccessToken: () => token },
    "@/lib/bookings": {
      getBookingDetails(id) { reads.push(["booking", id, token]); return readBooking(id, token); },
      getMyPayments() { reads.push(["payments", token]); return readPayments(token); },
    },
    "@/components/LoadingSkeletons": {
      BookingDetailsSkeleton: () => createElement("p", null, "Loading booking"),
      SessionLoadingSkeleton: () => createElement("p", null, "Checking session"),
    },
  });
  function expand(node, path) {
    if (Array.isArray(node)) return node.map((child, i) => {
      const element = expand(child, path + "/" + i);
      return element && typeof element === "object" && !Array.isArray(element) ? cloneElement(element, { key: i }) : element;
    });
    if (!node || typeof node !== "object") return node;
    if (typeof node.type === "function") {
      const key = path + "/" + node.type.name + "/" + (node.key ?? "");
      visited.add(key);
      if (!instances.has(key)) instances.set(key, { index: 0, slots: [], mounted: true });
      const prior = activeInstance;
      activeInstance = instances.get(key);
      activeInstance.index = 0;
      const element = node.type(node.props);
      activeInstance = prior;
      return expand(element, key);
    }
    return cloneElement(node, { children: expand(node.props.children, path + "/children") });
  }
  function remove(key, instance) {
    for (const slot of instance.slots) slot.cleanup?.();
    instance.mounted = false;
    instances.delete(key);
  }
  return {
    auth, reads, redirects, lateWrites,
    get invalidations() { return invalidations; },
    changeAccount(userId, nextToken) {
      auth.user = userId ? { user_id: userId } : null;
      auth.status = userId ? "authenticated" : "unauthenticated";
      token = nextToken;
    },
    replaceToken(nextToken) { token = nextToken; },
    unmount() { for (const [key, instance] of instances) remove(key, instance); },
    render(redemptionRequested = true, reservationId = "42") {
      effects = []; visited = new Set();
      const tree = expand(createElement(Experience, { reservationId, redemptionRequested }), "root");
      for (const [key, instance] of instances) if (!visited.has(key)) remove(key, instance);
      effects.forEach((effect) => effect());
      const buttons = [];
      function findButtons(node) {
        if (Array.isArray(node)) return node.forEach(findButtons);
        if (!node || typeof node !== "object") return;
        if (node.type === "button") buttons.push(node.props);
        findButtons(node.props.children);
      }
      findButtons(tree);
      return { html: renderToStaticMarkup(tree), buttons };
    },
  };
}

test("confirmed presentation displays only supplied reference, stay and funding amounts", () => {
  const html = show({
    kind: "confirmed", bookingReference: "LH-00000042", hotelName: "Fixture Hotel",
    checkInDate: "2027-01-10", checkOutDate: "2027-01-12", pointsRedeemed: 30618,
    pointsFundedValueCents: 30618, remainingCashDueCents: 0,
  });
  for (const pattern of [/Reward redemption confirmed/, /LH-00000042/, /Fixture Hotel/,
    /2027-01-10/, /2027-01-12/, /30,618/, /\$306\.18/, /\$0\.00/, /href="\/my-bookings"/,
    /sm:grid-cols-2/, /min-h-11/, /focus-visible:outline-2/]) {
    assert.match(html, pattern);
  }
});

test("loading, rejected and unavailable states use meaningful status and alert messages", () => {
  assert.match(show({ kind: "loading" }), /role="status".*Checking redemption confirmation/);
  assert.match(show({ kind: "authentication-required" }), /role="status".*Sign in to check/);
  assert.match(show({ kind: "rejected", reason: "insufficient_points" }), /role="alert".*did not have enough points/);
  assert.match(show({ kind: "rejected", reason: "not_eligible" }), /role="alert".*ineligible/);
  assert.match(show({ kind: "unavailable", cancelled: true }), /role="alert".*Reservation cancelled/);
  assert.doesNotMatch(show({ kind: "rejected", reason: "insufficient_points" }), /<button|Points redeemed/);
});

test("ordinary and intent-only paid confirmations reuse the same booking reads", async () => {
  const h = harness();
  assert.match(h.render(false).html, /Loading booking/);
  await tick();
  const ordinary = h.render(false).html;
  assert.match(ordinary, /Booking payment recorded/);
  assert.match(ordinary, /First Guest|First account hotel/);
  assert.doesNotMatch(ordinary, /Redemption not yet verified|Reward redemption confirmed/);
  const intended = h.render().html;
  assert.match(intended, /Booking payment recorded/);
  assert.match(intended, /Redemption not yet verified/);
  assert.match(intended, /does not identify how it was funded/);
  assert.doesNotMatch(intended, /Points redeemed|Reward redemption confirmed/);
  assert.deepEqual(h.reads, [["booking", 42, "first"], ["payments", "first"]]);
});

test("pending intent displays the unverified request and ordinary pending retains its payment link", async () => {
  const h = harness({ readPayments: async () => [{ ...paid, payment_status: "pending" }] });
  h.render();
  await tick();
  assert.match(h.render().html, /Reward redemption requested/);
  assert.doesNotMatch(h.render().html, /Complete payment|Reward redemption confirmed/);
  assert.match(h.render(false).html, /href="\/payment\/11"/);
});

test("malformed read communicates uncertainty and manual retry only reads status", async () => {
  let count = 0;
  const h = harness({ readBooking: async () => {
    if (++count === 1) throw new Error("malformed private response");
    return booking;
  } });
  h.render(); await tick();
  const unavailable = h.render();
  assert.match(unavailable.html, /role="alert".*Redemption status unavailable/);
  assert.doesNotMatch(unavailable.html, /malformed private response|Reward redemption confirmed/);
  assert.equal(unavailable.buttons[0].type, "button");
  unavailable.buttons[0].onClick();
  assert.match(h.render().html, /Checking redemption confirmation/);
  await tick();
  assert.match(h.render().html, /Redemption not yet verified/);
  assert.deepEqual(h.reads, [["booking", 42, "first"], ["payments", "first"], ["booking", 42, "first"], ["payments", "first"]]);
});

test("missing or wrong booking records do not expose private reservation data", async () => {
  for (const response of [null, { ...booking, reservation_id: 41 }]) {
    const h = harness({ readBooking: async () => response });
    h.render(); await tick();
    assert.match(h.render().html, /Reservation unavailable/);
    assert.doesNotMatch(h.render().html, /First account hotel|First Guest|Booking payment recorded/);
  }
});

test("cancelled reservations retain their status without payment or redemption success copy", async () => {
  const h = harness({ readBooking: async () => ({ ...booking, status: "cancelled" }) });
  h.render(); await tick();
  const html = h.render().html;
  assert.match(html, /Reservation cancelled/);
  assert.match(html, /Reservation details/);
  assert.doesNotMatch(html, /Booking payment recorded|Reward redemption confirmed/);
});

test("expired authentication clears private state, while unauthenticated visits make no reads", async () => {
  const h = harness({ readBooking: async () => { throw new ApiError(401); } });
  h.render(); await tick();
  assert.equal(h.invalidations, 1);
  assert.ok(h.redirects.every((path) => path === "/login"));
  assert.match(h.render().html, /Sign in to check redemption/);
  assert.doesNotMatch(h.render().html, /First account hotel|First Guest/);
  const signedOut = harness({ status: "unauthenticated" });
  assert.match(signedOut.render().html, /Sign in to check redemption/);
  assert.deepEqual(signedOut.reads, []);
});

test("logout and unmount ignore late protected read responses", async () => {
  for (const logout of [true, false]) {
    const held = deferred();
    const h = harness({ readBooking: () => held.promise });
    h.render();
    if (logout) {
      h.changeAccount(null, null);
      assert.match(h.render().html, /Sign in to check redemption/);
    } else h.unmount();
    held.resolve(booking);
    await tick();
    assert.deepEqual(h.lateWrites, []);
    if (logout) assert.doesNotMatch(h.render().html, /First account hotel|First Guest/);
  }
});

test("an account switch immediately hides previous data and suppresses a stale 401", async () => {
  const held = deferred();
  const h = harness({ readBooking: async (_id, token) => token === "first" ? held.promise :
    { ...booking, hotel_name: "Second account hotel", guest_full_name: null, guest_email: null } });
  h.render();
  h.changeAccount(8, "second");
  assert.match(h.render().html, /Checking redemption confirmation/);
  held.reject(new ApiError(401));
  await tick();
  const html = h.render().html;
  assert.match(html, /Second account hotel/);
  assert.doesNotMatch(html, /First account hotel|First Guest/);
  assert.equal(h.invalidations, 0);
  assert.deepEqual(h.redirects, []);
});

test("a late 401 after token replacement cannot invalidate the new session before rerender", async () => {
  const held = deferred();
  const h = harness({ readBooking: () => held.promise });
  h.render();
  h.replaceToken("second");
  held.reject(new ApiError(401));
  await tick();
  assert.equal(h.invalidations, 0);
  assert.deepEqual(h.redirects, []);
});

test("switching reservations drops the earlier read and displays only the selected booking", async () => {
  const held = deferred();
  const h = harness({
    readBooking: async (id) => id === 42 ? held.promise :
      { ...booking, reservation_id: id, hotel_name: "Selected hotel", guest_full_name: null },
    readPayments: async () => [paid, { ...paid, reservation_id: 43, payment_id: 12 }],
  });
  h.render();
  h.render(true, "43");
  held.resolve(booking);
  await tick();
  assert.match(h.render(true, "43").html, /Selected hotel/);
  assert.doesNotMatch(h.render(true, "43").html, /First account hotel/);
  assert.deepEqual(h.lateWrites, []);
});

test("an account switch removes an already displayed reservation before the next read resolves", async () => {
  const next = deferred();
  const h = harness({ readBooking: async (_id, token) => token === "first" ? booking : next.promise });
  h.render();
  await tick();
  assert.match(h.render().html, /First account hotel/);
  h.changeAccount(8, "second");
  const loading = h.render().html;
  assert.match(loading, /Checking redemption confirmation/);
  assert.doesNotMatch(loading, /First account hotel|First Guest|Booking payment recorded/);
  next.resolve(null);
  await tick();
  assert.match(h.render().html, /Reservation unavailable/);
});
