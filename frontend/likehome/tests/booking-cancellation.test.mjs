import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { ApiError } from "../lib/api.ts";
import { canCancelBooking, cancellationErrorMessage, createCancellationSubmissionGuard,
  keepBooking, requestCancellation, startCancellation } from "../lib/booking-cancellation.ts";
import { cancelBooking, cancelBookingAndRefresh } from "../lib/bookings.ts";
import { saveAccessToken } from "../lib/token-storage.ts";

const originalFetch = globalThis.fetch;
const originalWindow = globalThis.window;
afterEach(() => {
  globalThis.fetch = originalFetch;
  globalThis.window = originalWindow;
});

function mockSessionStorage() {
  const entries = new Map();
  globalThis.window = {
    sessionStorage: {
      getItem: (key) => entries.get(key) ?? null,
      setItem: (key, value) => entries.set(key, value),
      removeItem: (key) => entries.delete(key),
    },
  };
}

const response = {
  reservation_id: 12,
  status: "cancelled",
  booking_payment_id: 19,
  booking_payment_status: "refunded",
  cancellation_payment_id: 20,
  cancellation_amount: 30.1,
  cancellation_payment_status: "pending",
};

test("cancelling an unpaid booking preserves pending payment wording", async () => {
  mockSessionStorage();
  saveAccessToken("issued-token");
  const unpaidCancellation = { ...response, booking_payment_status: "pending" };
  globalThis.fetch = async () => new Response(JSON.stringify(unpaidCancellation));
  assert.deepEqual(await cancelBooking(12), unpaidCancellation);
});

const cancelledBooking = {
  reservation_id: 12,
  hotel_name: "Example Hotel",
  room_type_name: "Queen room",
  hotel_address: "",
  hotel_phone: null,
  hotel_description: null,
  room_description: null,
  check_in_date: "2026-10-05T00:00:00",
  check_out_date: "2026-10-08T00:00:00",
  price_per_night: 125,
  total_price: 150.5,
  status: "cancelled",
};

test("confirmation and keep-booking leave the network untouched", () => {
  let requests = 0;
  globalThis.fetch = async () => { requests += 1; throw new Error("Unexpected request"); };
  assert.equal(canCancelBooking("confirmed"), true);
  assert.equal(canCancelBooking("cancelled"), false);
  assert.equal(canCancelBooking("completed"), false);

  const confirming = requestCancellation({ kind: "idle" }, 12, "confirmed");
  assert.deepEqual(confirming, { kind: "confirming", reservationId: 12 });
  assert.deepEqual(keepBooking(confirming), { kind: "idle" });
  assert.deepEqual(requestCancellation({ kind: "idle" }, 12, "cancelled"), { kind: "idle" });
  assert.deepEqual(requestCancellation({ kind: "idle" }, 12, "completed"), { kind: "idle" });
  assert.equal(requests, 0);
});

test("confirming sends one authorized bodyless POST, then the updated list can be refetched", async () => {
  mockSessionStorage();
  saveAccessToken("issued-token");
  const requests = [];
  const events = [];
  globalThis.fetch = async (url, init) => {
    requests.push({ url, init });
    events.push(url.endsWith("/cancel-booking/12") ? "post" : "refetch");
    return url.endsWith("/cancel-booking/12")
      ? new Response(JSON.stringify(response))
      : new Response(JSON.stringify([cancelledBooking]));
  };

  const confirming = requestCancellation({ kind: "idle" }, 12, "confirmed");
  assert.equal(requests.length, 0);
  assert.deepEqual(startCancellation(confirming, 12), { kind: "submitting", reservationId: 12 });
  assert.equal(requests.length, 0);
  const result = await cancelBookingAndRefresh(12, (cancellation) => {
    assert.deepEqual(cancellation, response);
    events.push("cancelled");
  });
  assert.equal(result.kind, "refreshed");
  assert.equal(result.bookings[0].status, "cancelled");
  assert.equal(canCancelBooking(result.bookings[0].status), false);
  assert.deepEqual(events, ["post", "cancelled", "refetch"]);

  const baseUrl = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
  assert.equal(requests.length, 2);
  assert.equal(requests[0].url, `${baseUrl}/bookings/cancel-booking/12`);
  assert.equal(requests[0].init.method, "POST");
  assert.equal(requests[0].init.headers.Authorization, "Bearer issued-token");
  assert.equal(requests[0].init.body, undefined);
  assert.equal(requests[0].init.headers["Content-Type"], undefined);
  assert.ok(!requests[0].url.includes("user_id"));
  assert.ok(!requests[0].url.includes("issued-token"));
  assert.equal(requests[1].url, `${baseUrl}/bookings/get-all-bookings`);
});

test("a failed refresh preserves knowledge that cancellation succeeded", async () => {
  mockSessionStorage();
  saveAccessToken("issued-token");
  globalThis.fetch = async (url) => url.endsWith("/cancel-booking/12")
    ? new Response(JSON.stringify(response))
    : new Response("service unavailable", { status: 500 });
  let confirmed = false;
  const result = await cancelBookingAndRefresh(12, () => { confirmed = true; });
  assert.equal(confirmed, true);
  assert.equal(result.kind, "refresh-error");
  assert.ok(result.error instanceof ApiError);
  assert.equal(result.error.status, 500);
});

test("submission guard rejects duplicate starts until the request finishes", () => {
  const guard = createCancellationSubmissionGuard();
  assert.equal(guard.tryStart(12), true);
  assert.equal(guard.tryStart(12), false);
  assert.equal(guard.tryStart(13), false);
  guard.finish();
  assert.equal(guard.tryStart(12), true);
});

test("missing token and invalid reservation IDs never send a request", async () => {
  mockSessionStorage();
  let requests = 0;
  globalThis.fetch = async () => { requests += 1; throw new Error("Unexpected request"); };
  await assert.rejects(cancelBooking(12), (error) => error instanceof ApiError && error.status === 401);
  await assert.rejects(cancelBooking(0), /Invalid reservation ID/);
  await assert.rejects(cancelBooking(1.5), /Invalid reservation ID/);
  assert.equal(requests, 0);
});

test("401, 404, 409, 500, and network failures keep safe status or wording", async () => {
  mockSessionStorage();
  saveAccessToken("issued-token");
  for (const status of [401, 404, 409, 500]) {
    globalThis.fetch = async () => new Response("private backend details", { status });
    await assert.rejects(cancelBooking(12), (error) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status, status);
      assert.ok(!error.message.includes("private"));
      if (status !== 401) {
        assert.ok(!cancellationErrorMessage(error).includes("private"));
      }
      return true;
    });
  }
  assert.match(cancellationErrorMessage(new ApiError(404)), /could not be found or is no longer available/);
  assert.match(cancellationErrorMessage(new ApiError(409)), /can no longer be cancelled/);
  assert.match(cancellationErrorMessage(new ApiError(500)), /Please try again/);

  globalThis.fetch = async () => { throw new TypeError("private network detail"); };
  await assert.rejects(cancelBooking(12), (error) => {
    assert.match(cancellationErrorMessage(error), /Please try again/);
    assert.ok(!cancellationErrorMessage(error).includes("private"));
    return true;
  });
});

test("malformed cancellation responses are rejected before showing success", async () => {
  mockSessionStorage();
  saveAccessToken("issued-token");
  for (const payload of [
    { ...response, reservation_id: 13 },
    { ...response, cancellation_amount: "30.10" },
    { ...response, cancellation_payment_status: "paid" },
  ]) {
    globalThis.fetch = async () => new Response(JSON.stringify(payload));
    await assert.rejects(cancelBooking(12), /unexpected response/);
  }
});
