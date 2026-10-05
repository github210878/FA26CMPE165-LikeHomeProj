import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { ApiError } from "../lib/api.ts";
import { createBooking } from "../lib/bookings.ts";
import { bookingRequestFromQuote, createBookingSubmissionGuard, revalidateHotel, submitAcceptedQuote } from "../lib/checkout.ts";
import { checkoutHref, parseCheckoutSelection, safeCheckoutReturnTo } from "../lib/checkout-selection.ts";
import { saveAccessToken } from "../lib/token-storage.ts";

const originalFetch = globalThis.fetch;
const originalWindow = globalThis.window;
afterEach(() => {
  globalThis.fetch = originalFetch;
  globalThis.window = originalWindow;
});

function storage() {
  const entries = new Map();
  globalThis.window = { sessionStorage: {
    getItem: (key) => entries.get(key) ?? null,
    setItem: (key, value) => entries.set(key, value),
    removeItem: (key) => entries.delete(key),
  } };
}

const selection = {
  property_token: "property-123", q: "San Jose hotels",
  check_in_date: "2026-11-01", check_out_date: "2026-11-03",
  adults: 3, children: 0, currency: "USD", gl: "us", hl: "en",
  displayed_price_per_night: 150,
};
const quote = {
  property_token: "property-123", hotel_name: "Hotel A",
  check_in_date: "2026-11-01", check_out_date: "2026-11-03",
  adults: 3, children: 0, currency: "USD", number_of_nights: 2,
  availability: "available", rate_rule: "lowest_eligible_provider_base_total",
  source: "Provider A", guest_capacity: 3, current_price_per_night: 165,
  provider_base_total: 330, provider_total_with_taxes_fees: 350,
  likehome_reservation_total: 346.5, likehome_payment_amount: 374.22,
  price_changed: true,
};
const bookingResponse = { user_id: 7, hotel_id: 8, room_type_id: 9, reservation_id: 10, payment_id: 11 };
const baseUrl = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");

test("selection link preserves only non-secret stay context and rejects incomplete navigation", () => {
  const href = checkoutHref({ destination: " San Jose hotels ", checkIn: "2026-11-01", checkOut: "2026-11-03", guests: "3" },
    { name: "Hotel A", property_token: "property-123", price_per_night: 150, rating: null, amenities: null });
  assert.ok(href.startsWith("/checkout?"));
  assert.deepEqual(parseCheckoutSelection(Object.fromEntries(new URL(href, "https://likehome.test").searchParams)), selection);
  assert.ok(!href.includes("Bearer"));
  assert.ok(!href.includes("api_key"));
  assert.equal(parseCheckoutSelection({ ...selection, q: undefined }), null);
  assert.equal(parseCheckoutSelection({ ...selection, children: undefined }), null);
  assert.equal(parseCheckoutSelection({ ...selection, currency: "EUR" }), null);
  assert.equal(parseCheckoutSelection({ ...selection, property_token: "legacy:1" }), null);
  assert.equal(checkoutHref({ destination: "San Jose", checkIn: "2026-11-01", checkOut: "2026-11-03", guests: "3" },
    { name: "No token", property_token: null, price_per_night: 150, rating: null, amenities: null }), null);
  assert.equal(safeCheckoutReturnTo(href), href);
  assert.equal(safeCheckoutReturnTo("//evil.example"), null);
  assert.equal(safeCheckoutReturnTo("/my-bookings"), null);
});

test("revalidation POST uses exact selection body and validates normalized quote", async () => {
  let observed;
  globalThis.fetch = async (url, init) => {
    observed = { url, init };
    return new Response(JSON.stringify(quote));
  };
  assert.deepEqual(await revalidateHotel(selection), quote);
  assert.equal(observed.url, `${baseUrl}/hotels/revalidate`);
  assert.equal(observed.init.method, "POST");
  assert.deepEqual(JSON.parse(observed.init.body), selection);
  assert.equal(observed.init.headers.Authorization, undefined);
  assert.ok(!observed.url.includes("property-123"));
  assert.ok(!observed.url.includes("api_key"));
});

test("quote API preserves unavailable and provider error statuses safely", async () => {
  for (const status of [409, 502, 504, 500]) {
    globalThis.fetch = async () => new Response(JSON.stringify({ detail: "private provider detail" }), { status });
    await assert.rejects(revalidateHotel(selection), (error) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status, status);
      assert.ok(!error.message.includes("private"));
      return true;
    });
  }
  globalThis.fetch = async () => new Response(JSON.stringify({ ...quote, likehome_payment_amount: "374.22" }));
  await assert.rejects(revalidateHotel(selection), /unexpected response/);
});

test("booking sends only selected stay and accepted server quote using Bearer auth", async () => {
  storage();
  saveAccessToken("test-user-token");
  const request = bookingRequestFromQuote(selection, quote);
  assert.deepEqual(request, {
    hotel_token: "property-123", q: "San Jose hotels",
    check_in_date: "2026-11-01", check_out_date: "2026-11-03",
    adults: 3, children: 0, currency: "USD", gl: "us", hl: "en",
    price_per_night: 165, accepted_payment_amount: 374.22,
  });
  let observed;
  globalThis.fetch = async (url, init) => {
    observed = { url, init };
    return new Response(JSON.stringify(bookingResponse));
  };
  assert.deepEqual(await createBooking(request), bookingResponse);
  assert.equal(observed.url, `${baseUrl}/bookings/create`);
  assert.equal(observed.init.headers.Authorization, "Bearer test-user-token");
  assert.deepEqual(JSON.parse(observed.init.body), request);
  assert.ok(!("user_id" in request));
  assert.ok(!("total_price" in request));
  assert.ok(!observed.url.includes("test-user-token"));
  assert.ok(!observed.init.body.includes("test-user-token"));
  assert.ok(!observed.init.body.includes("api_key"));
});

test("missing or rejected user session cannot create a booking", async () => {
  storage();
  let calls = 0;
  globalThis.fetch = async () => { calls++; return new Response("unauthorized", { status: 401 }); };
  await assert.rejects(createBooking(bookingRequestFromQuote(selection, quote)), (error) => error instanceof ApiError && error.status === 401);
  assert.equal(calls, 0);
  saveAccessToken("expired-token");
  await assert.rejects(createBooking(bookingRequestFromQuote(selection, quote)), (error) => error instanceof ApiError && error.status === 401);
  assert.equal(calls, 1);
});

test("booking quote conflict fetches a new quote and never submits a second booking", async () => {
  storage();
  saveAccessToken("test-user-token");
  const newerQuote = { ...quote, current_price_per_night: 170, provider_base_total: 340, likehome_payment_amount: 385.56 };
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    if (url.endsWith("/bookings/create")) return new Response("conflict", { status: 409 });
    if (url.endsWith("/hotels/revalidate")) return new Response(JSON.stringify(newerQuote));
    throw new Error("Unexpected request");
  };
  let conflictNotices = 0;
  const result = await submitAcceptedQuote(selection, quote, () => { conflictNotices++; });
  assert.deepEqual(result, { kind: "changed", quote: newerQuote });
  assert.equal(conflictNotices, 1);
  assert.deepEqual(calls.map((call) => new URL(call.url).pathname), ["/bookings/create", "/hotels/revalidate"]);
  assert.equal(JSON.parse(calls[0].init.body).price_per_night, 165);
  assert.equal(JSON.parse(calls[0].init.body).accepted_payment_amount, 374.22);
});

test("successful confirmation creates one booking without another frontend quote call", async () => {
  storage();
  saveAccessToken("test-user-token");
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(new URL(url).pathname);
    return new Response(JSON.stringify(bookingResponse));
  };
  const result = await submitAcceptedQuote(selection, quote, () => { throw new Error("Unexpected conflict"); });
  assert.deepEqual(result, { kind: "created", booking: bookingResponse });
  assert.deepEqual(calls, ["/bookings/create"]);
});

test("submission guard prevents duplicate pending confirmation", () => {
  const guard = createBookingSubmissionGuard();
  assert.equal(guard.tryStart(), true);
  assert.equal(guard.tryStart(), false);
  guard.finish();
  assert.equal(guard.tryStart(), true);
});
