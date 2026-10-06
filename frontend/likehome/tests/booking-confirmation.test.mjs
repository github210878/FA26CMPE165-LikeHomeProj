import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { ApiError } from "../lib/api.ts";
import { bookingConfirmationHref, parseReservationId } from "../lib/booking-confirmation.ts";
import { getBookingDetails, getMyPayments, getPaymentDetails, payBookingPayment } from "../lib/bookings.ts";
import { bookingPaymentForReservation, paymentHref } from "../lib/payment.ts";
import { submitAcceptedQuote } from "../lib/checkout.ts";
import { saveAccessToken } from "../lib/token-storage.ts";

const originalFetch = globalThis.fetch;
const originalWindow = globalThis.window;
afterEach(() => {
  globalThis.fetch = originalFetch;
  globalThis.window = originalWindow;
});

function session() {
  const entries = new Map();
  globalThis.window = { sessionStorage: {
    getItem: (key) => entries.get(key) ?? null,
    setItem: (key, value) => entries.set(key, value),
    removeItem: (key) => entries.delete(key),
  } };
  saveAccessToken("private-test-token");
}

const selection = {
  property_token: "property-123", q: "San Jose hotels",
  check_in_date: "2026-11-01", check_out_date: "2026-11-03",
  adults: 2, children: 0, currency: "USD", gl: "us", hl: "en",
};
const quote = {
  current_price_per_night: 165, likehome_payment_amount: 374.22,
};
const created = { user_id: 7, hotel_id: 8, room_type_id: 9, reservation_id: 42, payment_id: 11 };
const guest = { guest_full_name: "Person Example", guest_email: "person@example.com" };
const persisted = {
  reservation_id: 42, hotel_name: "Example Hotel", room_type_name: "Queen room",
  ...guest,
  hotel_address: "123 Main St, San Jose, CA", hotel_phone: null,
  hotel_description: null, room_description: "One queen bed",
  check_in_date: "2026-11-01", check_out_date: "2026-11-03",
  price_per_night: 165, total_price: 346.5, status: "confirmed",
};

test("creation opens payment review; only paid persisted state supports confirmation", async () => {
  session();
  const requests = [];
  const pendingPayment = { payment_id: 11, reservation_id: 42, amount: 374.22,
    payment_type: "booking", payment_status: "pending" };
  const paidPayment = { ...pendingPayment, payment_status: "paid" };
  globalThis.fetch = async (url, init) => {
    requests.push({ url, init });
    if (url.endsWith("/bookings/create")) return new Response(JSON.stringify(created));
    if (url.endsWith("/bookings/get-payment-details/11")) return new Response(JSON.stringify(pendingPayment));
    if (url.endsWith("/bookings/pay/11")) return new Response(JSON.stringify(paidPayment));
    if (url.endsWith("/bookings/get-booking-details/42")) return new Response(JSON.stringify(persisted));
    if (url.endsWith("/bookings/get-all-payments")) return new Response(JSON.stringify([paidPayment]));
    throw new Error("Unexpected request");
  };

  const result = await submitAcceptedQuote(selection, quote, guest, () => assert.fail("Unexpected conflict"));
  assert.equal(result.kind, "created");
  assert.equal(paymentHref(result.booking.payment_id), "/payment/11");
  assert.deepEqual(await getPaymentDetails(result.booking.payment_id), pendingPayment);
  assert.deepEqual(await payBookingPayment(result.booking.payment_id), paidPayment);
  const href = bookingConfirmationHref(result.booking);
  assert.equal(href, "/booking-confirmation/42");
  assert.equal(parseReservationId(href.split("/").at(-1)), 42);
  assert.ok(!href.includes("private-test-token"));
  assert.ok(!href.includes("payment_id"));
  assert.ok(!href.includes(guest.guest_email));

  // Reopen using only the URL identifier and the authenticated session.
  assert.deepEqual(await getBookingDetails(parseReservationId("42")), persisted);
  assert.deepEqual(bookingPaymentForReservation(await getMyPayments(), 42), paidPayment);
  assert.deepEqual(requests.map(({ url }) => new URL(url).pathname), [
    "/bookings/create", "/bookings/get-payment-details/11", "/bookings/pay/11",
    "/bookings/get-booking-details/42", "/bookings/get-all-payments",
  ]);
  assert.equal(requests[3].init.headers.Authorization, "Bearer private-test-token");
  assert.equal(requests[3].init.cache, "no-store");
  assert.equal(requests[3].init.body, undefined);
  assert.ok(!requests[3].url.includes("user_id"));
  assert.ok(!requests[3].url.includes("private-test-token"));
});

test("failed creation and quote conflict cannot supply a confirmation route", async () => {
  session();
  globalThis.fetch = async () => new Response("failure", { status: 500 });
  await assert.rejects(submitAcceptedQuote(selection, quote, guest, () => {}), (error) => error instanceof ApiError && error.status === 500);

  const newerQuote = {
    ...quote, ...selection, hotel_name: "Example Hotel", number_of_nights: 2,
    availability: "available", rate_rule: "lowest_eligible_provider_base_total",
    source: "Provider A", guest_capacity: 2, provider_base_total: 330,
    provider_total_with_taxes_fees: null, likehome_reservation_total: 346.5,
    price_changed: true,
  };
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(new URL(url).pathname);
    if (url.endsWith("/bookings/create")) return new Response("conflict", { status: 409 });
    return new Response(JSON.stringify(newerQuote));
  };
  const result = await submitAcceptedQuote(selection, quote, guest, () => {});
  assert.equal(result.kind, "changed");
  assert.deepEqual(calls, ["/bookings/create", "/hotels/revalidate"]);
});

test("route IDs reject malformed input and detail failures can be retried without provider calls", async () => {
  session();
  for (const value of ["0", "-1", "1x", "1?user_id=7", "9007199254740992"]) {
    assert.equal(parseReservationId(value), null);
  }
  assert.equal(parseReservationId("42"), 42);

  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(new URL(url).pathname);
    if (calls.length === 1) return new Response("temporary failure", { status: 503 });
    return new Response(JSON.stringify(persisted));
  };
  await assert.rejects(getBookingDetails(42), (error) => error instanceof ApiError && error.status === 503);
  assert.deepEqual(await getBookingDetails(42), persisted);
  assert.deepEqual(calls, ["/bookings/get-booking-details/42", "/bookings/get-booking-details/42"]);
});

test("null, 404, and 401 details remain distinct and do not trigger revalidation", async () => {
  session();
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(new URL(url).pathname);
    return new Response("null");
  };
  assert.equal(await getBookingDetails(42), null);
  for (const status of [404, 401]) {
    globalThis.fetch = async (url) => {
      calls.push(new URL(url).pathname);
      return new Response("private detail", { status });
    };
    await assert.rejects(getBookingDetails(42), (error) => error instanceof ApiError && error.status === status && !error.message.includes("private detail"));
  }
  assert.deepEqual(calls, Array(3).fill("/bookings/get-booking-details/42"));
});

test("legacy booking detail can have null guest fields", async () => {
  session();
  const legacy = { ...persisted, guest_full_name: null, guest_email: null };
  globalThis.fetch = async () => new Response(JSON.stringify(legacy));
  assert.deepEqual(await getBookingDetails(42), legacy);
});
