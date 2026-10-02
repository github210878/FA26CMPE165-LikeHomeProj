import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { ApiError } from "../lib/api.ts";
import { getBookingDetails, getMyBookings } from "../lib/bookings.ts";
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

const booking = {
  reservation_id: 12,
  hotel_name: "Example Hotel",
  room_type_name: "Queen room",
  hotel_address: "123 Main St, San Jose, CA. 95112 USA",
  hotel_phone: null,
  hotel_description: null,
  room_description: "One queen bed",
  check_in_date: "2026-10-05T00:00:00",
  check_out_date: "2026-10-08T00:00:00",
  price_per_night: 125,
  total_price: 150.5,
  status: "confirmed",
};

test("booking list uses the exact current-user endpoint and Bearer header", async () => {
  mockSessionStorage();
  saveAccessToken("issued-token");
  let request;
  globalThis.fetch = async (url, init) => {
    request = { url, init };
    return new Response(JSON.stringify([booking]));
  };

  assert.deepEqual(await getMyBookings(), [booking]);
  const baseUrl = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
  assert.equal(request.url, `${baseUrl}/bookings/get-all-bookings`);
  assert.equal(request.init.headers.Authorization, "Bearer issued-token");
  assert.equal(request.init.cache, "no-store");
  assert.equal(request.init.method, undefined);
  assert.ok(!request.url.includes("issued-token"));
  assert.ok(!request.url.includes("user_id"));
  assert.ok(!request.url.includes("?"));
});

test("an empty booking list is a valid response", async () => {
  mockSessionStorage();
  saveAccessToken("issued-token");
  globalThis.fetch = async () => new Response("[]");
  assert.deepEqual(await getMyBookings(), []);
});

test("missing token rejects before requesting bookings", async () => {
  mockSessionStorage();
  let called = false;
  globalThis.fetch = async () => { called = true; throw new Error("Unexpected request"); };

  await assert.rejects(getMyBookings(), (error) => error instanceof ApiError && error.status === 401);
  assert.equal(called, false);
});

test("unauthorized and backend errors retain safe HTTP status", async () => {
  mockSessionStorage();
  saveAccessToken("issued-token");
  for (const status of [401, 503]) {
    globalThis.fetch = async () => new Response("private backend detail", { status });
    await assert.rejects(getMyBookings(), (error) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status, status);
      assert.ok(!error.message.includes("private backend detail"));
      return true;
    });
  }
});

test("malformed booking-list shapes are rejected before rendering", async () => {
  mockSessionStorage();
  saveAccessToken("issued-token");
  for (const payload of [
    {},
    { bookings: [booking] },
    [{ ...booking, reservation_id: "12" }],
    [{ ...booking, hotel_phone: undefined }],
    [{ ...booking, total_price: "150.50" }],
    [{ ...booking, check_in_date: null }],
    [{ ...booking, status: "unknown" }],
  ]) {
    globalThis.fetch = async () => new Response(JSON.stringify(payload));
    await assert.rejects(getMyBookings(), /unexpected response/);
  }
});

test("booking details use the owned reservation ID with Bearer auth", async () => {
  mockSessionStorage();
  saveAccessToken("issued-token");
  let request;
  globalThis.fetch = async (url, init) => {
    request = { url, init };
    return new Response(JSON.stringify(booking));
  };

  assert.deepEqual(await getBookingDetails(12), booking);
  const baseUrl = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
  assert.equal(request.url, `${baseUrl}/bookings/get-booking-details/12`);
  assert.equal(request.init.headers.Authorization, "Bearer issued-token");
  assert.equal(request.init.cache, "no-store");
  assert.ok(!request.url.includes("user_id"));
  assert.ok(!request.url.includes("issued-token"));
  assert.ok(!request.url.includes("?"));
});

test("missing and non-owned booking details are unavailable", async () => {
  mockSessionStorage();
  saveAccessToken("issued-token");
  globalThis.fetch = async () => new Response("null");
  assert.equal(await getBookingDetails(12), null);

  globalThis.fetch = async () => new Response("not found", { status: 404 });
  await assert.rejects(getBookingDetails(12), (error) => error instanceof ApiError && error.status === 404);
});

test("booking detail rejects missing auth and unauthorized responses", async () => {
  mockSessionStorage();
  let called = false;
  globalThis.fetch = async () => { called = true; throw new Error("Unexpected request"); };
  await assert.rejects(getBookingDetails(12), (error) => error instanceof ApiError && error.status === 401);
  assert.equal(called, false);

  saveAccessToken("issued-token");
  globalThis.fetch = async () => new Response("invalid token", { status: 401 });
  await assert.rejects(getBookingDetails(12), (error) => error instanceof ApiError && error.status === 401);
});

test("booking detail rejects malformed records and invalid reservation IDs", async () => {
  mockSessionStorage();
  saveAccessToken("issued-token");
  globalThis.fetch = async () => new Response(JSON.stringify({ ...booking, total_price: "150.50" }));
  await assert.rejects(getBookingDetails(12), /unexpected response/);
  await assert.rejects(getBookingDetails(0), /Invalid reservation ID/);
  await assert.rejects(getBookingDetails(1.5), /Invalid reservation ID/);
});

test("booking detail surfaces service and network failures without response details", async () => {
  mockSessionStorage();
  saveAccessToken("issued-token");
  globalThis.fetch = async () => new Response("private backend detail", { status: 503 });
  await assert.rejects(getBookingDetails(12), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 503);
    assert.ok(!error.message.includes("private backend detail"));
    return true;
  });

  globalThis.fetch = async () => { throw new TypeError("Failed to fetch"); };
  await assert.rejects(getBookingDetails(12), TypeError);
});
