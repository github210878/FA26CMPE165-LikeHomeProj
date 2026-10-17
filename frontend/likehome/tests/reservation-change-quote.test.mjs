import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import { ApiError } from "../lib/api.ts";
import { getReservationChangeQuote } from "../lib/bookings.ts";
import { getLocalToday } from "../lib/search-validation.mjs";

const originalFetch = globalThis.fetch;
const originalWindow = globalThis.window;
const token = "synthetic-reservation-change-bearer";
const quoteId = "opaque-synthetic-review-artifact";
const consoleMethods = ["log", "info", "warn", "error", "debug"];
const originalConsole = Object.fromEntries(consoleMethods.map((method) => [method, console[method]]));
let calls;
let writes;
let logs;
let entries;

beforeEach(() => {
  calls = [];
  writes = [];
  logs = [];
  entries = new Map([["likehome_access_token", token]]);
  globalThis.window = {
    sessionStorage: {
      getItem: (key) => entries.get(key) ?? null,
      setItem: (...args) => writes.push(["session.setItem", ...args]),
      removeItem: (...args) => writes.push(["session.removeItem", ...args]),
      clear: () => writes.push(["session.clear"]),
    },
    localStorage: {
      getItem: () => null,
      setItem: (...args) => writes.push(["local.setItem", ...args]),
      removeItem: (...args) => writes.push(["local.removeItem", ...args]),
      clear: () => writes.push(["local.clear"]),
    },
  };
  globalThis.fetch = async (...args) => {
    calls.push(args);
    throw new Error("Unexpected network request");
  };
  for (const method of consoleMethods) console[method] = (...args) => logs.push([method, ...args]);
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  globalThis.window = originalWindow;
  for (const method of consoleMethods) console[method] = originalConsole[method];
  // Apply to successful, rejected, and network-error paths, including every subtest.
  assert.deepEqual(writes, [], "quote requests must not persist quotes or mutate authentication storage");
  assert.deepEqual(logs, [], "quote requests must not log bearer tokens, signed quotes, or payloads");
});

function review(overrides = {}) {
  return {
    check_in_date: "2096-02-28", check_out_date: "2096-03-01", q: "San Jose",
    adults: 2, children: 1, ...overrides,
  };
}

function response(request = review()) {
  return {
    reservation_id: 42, quote_id: quoteId, expires_at: new Date(Date.now() + 600000).toISOString(),
    quote: {
      property_token: "synthetic-owned-property", hotel_name: "Synthetic Hotel",
      check_in_date: request.check_in_date, check_out_date: request.check_out_date,
      adults: request.adults, children: request.children, currency: "USD",
      number_of_nights: (Date.parse(request.check_out_date) - Date.parse(request.check_in_date)) / 86400000,
      availability: "available", rate_rule: "lowest_eligible_provider_base_total", source: "Synthetic Provider",
      guest_capacity: request.adults + request.children, current_price_per_night: 100, provider_base_total: 200,
      provider_total_with_taxes_fees: 218, likehome_reservation_total: 210,
      likehome_payment_amount: 226.8, price_changed: null,
    },
  };
}

function respond(value) {
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    return { ok: true, json: async () => value };
  };
}

function assertQuotePost(expected = review(), reservationId = 42) {
  assert.equal(calls.length, 1, "exactly one quote request and no other endpoint or retry");
  const { url, init } = calls[0];
  const base = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
  assert.equal(url, `${base}/bookings/${reservationId}/change-quote`);
  assert.equal(init.method, "POST");
  assert.deepEqual(init.headers, { Authorization: `Bearer ${token}`, "Content-Type": "application/json" });
  assert.deepEqual(JSON.parse(init.body), { ...expected, q: expected.q.trim(), currency: "USD", gl: "us", hl: "en" });
  assert.ok(!url.includes(token) && !url.includes(quoteId));
  assert.ok(!init.body.includes(token) && !init.body.includes(quoteId));
}

test("returns an opaque review with one authenticated POST and exact normalized body", async () => {
  const request = Object.freeze(review({ q: "  San Jose  " }));
  const value = response(request);
  respond(value);
  assert.deepEqual(await getReservationChangeQuote(42, request), value);
  assertQuotePost(request);
  assert.equal(request.q, "  San Jose  ");
  assert.equal(entries.get("likehome_access_token"), token);
});

test("accepts explicit supported context and nullable/boolean revalidation fields", async (t) => {
  for (const changed of [null, false, true]) {
    await t.test(String(changed), async () => {
      const request = review({ currency: "USD", gl: "us", hl: "en" });
      const value = response(request);
      value.quote.price_changed = changed;
      value.quote.provider_total_with_taxes_fees = null;
      respond(value);
      assert.deepEqual(await getReservationChangeQuote(42, request), value);
      assertQuotePost(request);
    });
  }
});

test("accepts backend guest boundaries without imposing a combined 20-guest limit", async (t) => {
  for (const [adults, children] of [[1, 0], [20, 20]]) {
    await t.test(`${adults} adults and ${children} children`, async () => {
      const request = review({ adults, children });
      const value = response(request);
      respond(value);
      assert.deepEqual(await getReservationChangeQuote(42, request), value);
      assertQuotePost(request);
    });
  }
});

test("accepts Unicode destination length as backend characters rather than UTF-16 units", async () => {
  const request = review({ q: "🌍".repeat(255) });
  respond(response(request));
  await getReservationChangeQuote(42, request);
  assertQuotePost(request);
});

test("accepts check-in today, leap days, and DST-spanning stays using calendar nights", async (t) => {
  const today = getLocalToday();
  const tomorrow = new Date(`${today}T00:00:00Z`);
  tomorrow.setUTCDate(tomorrow.getUTCDate() + 1);
  for (const dates of [
    [today, tomorrow.toISOString().slice(0, 10)],
    ["2096-02-29", "2096-03-01"], ["2096-03-10", "2096-03-13"],
  ]) {
    await t.test(dates.join(" to "), async () => {
      const request = review({ check_in_date: dates[0], check_out_date: dates[1] });
      const value = response(request);
      respond(value);
      assert.deepEqual(await getReservationChangeQuote(42, request), value);
      assertQuotePost(request);
    });
  }
});

test("validates against its own copied request even if the caller edits the original during fetch", async () => {
  const request = review();
  const value = response(request);
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    request.check_in_date = "2096-04-01";
    request.adults = 20;
    return { ok: true, json: async () => value };
  };
  assert.deepEqual(await getReservationChangeQuote(42, request), value);
  assertQuotePost();
});

test("missing or inaccessible token fails with 401 before any request", async (t) => {
  for (const mode of ["missing", "server", "blocked"]) {
    await t.test(mode, async () => {
      if (mode === "missing") entries.clear();
      if (mode === "server") globalThis.window = undefined;
      if (mode === "blocked") Object.defineProperty(globalThis.window, "sessionStorage", {
        get() { throw new Error("Storage unavailable"); },
      });
      await assert.rejects(getReservationChangeQuote(42, review()), (error) => error instanceof ApiError && error.status === 401);
      assert.equal(calls.length, 0);
    });
  }
});

test("rejects invalid reservation IDs before any request", async (t) => {
  for (const id of [0, -1, 1.5, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1, "42", null, undefined, true]) {
    await t.test(String(id), async () => {
      await assert.rejects(getReservationChangeQuote(id, review()), { message: "Invalid reservation ID" });
      assert.equal(calls.length, 0);
    });
  }
});

test("rejects malformed request shape and omitted required fields", async (t) => {
  const cases = { null: null, array: [], string: "review" };
  for (const key of ["check_in_date", "check_out_date", "q", "adults", "children"]) {
    const request = review();
    delete request[key];
    cases[`missing ${key}`] = request;
  }
  for (const [name, request] of Object.entries(cases)) {
    await t.test(name, async () => {
      await assert.rejects(getReservationChangeQuote(42, request), { message: "Invalid reservation change review" });
      assert.equal(calls.length, 0);
    });
  }
});

test("rejects extra identity, pricing, quote, and mutation fields rather than serializing them", async (t) => {
  for (const key of ["user_id", "customer_id", "hotel_id", "property_token", "price_per_night", "displayed_price_per_night",
    "likehome_payment_amount", "quote_id", "reservation_id", "confirm", "toJSON"]) {
    await t.test(key, async () => {
      await assert.rejects(getReservationChangeQuote(42, review({ [key]: "untrusted" })), { message: "Invalid reservation change review" });
      assert.equal(calls.length, 0);
    });
  }
});

test("rejects invalid, past, equal, and reversed calendar dates", async (t) => {
  for (const [name, changes] of Object.entries({
    nonLeap: { check_in_date: "2095-02-29" }, impossible: { check_out_date: "2096-04-31" },
    badMonth: { check_in_date: "2096-13-01" }, zeroDay: { check_in_date: "2096-02-00" },
    yearZero: { check_in_date: "0000-01-01" }, shortYear: { check_in_date: "96-02-28" },
    unpadded: { check_in_date: "2096-2-28" }, timestamp: { check_in_date: "2096-02-28T00:00:00Z" },
    whitespace: { check_in_date: " 2096-02-28" }, empty: { check_out_date: "" },
    trailingNewline: { check_in_date: "2096-02-28\n" }, trailingCheckoutNewline: { check_out_date: "2096-03-01\n" },
    nonString: { check_in_date: new Date() }, past: { check_in_date: "2000-01-01" },
    equal: { check_out_date: "2096-02-28" }, reversed: { check_out_date: "2096-02-27" },
  })) {
    await t.test(name, async () => {
      await assert.rejects(getReservationChangeQuote(42, review(changes)), { message: "Invalid reservation change review" });
      assert.equal(calls.length, 0);
    });
  }
});

test("rejects invalid destinations, strict guest counts, and unsupported context", async (t) => {
  const cases = [];
  for (const q of ["", " \t\n ", "x".repeat(256), "🌍".repeat(256), null, 42]) cases.push({ q });
  for (const adults of [0, -1, 21, 1.5, "2", true, null, NaN, Infinity]) cases.push({ adults });
  for (const children of [-1, 21, 0.5, "0", false, null, NaN, Infinity]) cases.push({ children });
  for (const [key, invalid] of [["currency", "EUR"], ["gl", "US"], ["hl", "es"]]) {
    cases.push({ [key]: invalid }, { [key]: null }, { [key]: "" });
  }
  for (const [index, changes] of cases.entries()) {
    await t.test(`${index}: ${Object.keys(changes)[0]}`, async () => {
      await assert.rejects(getReservationChangeQuote(42, review(changes)), { message: "Invalid reservation change review" });
      assert.equal(calls.length, 0);
    });
  }
});

test("rejects missing or malformed envelopes, mismatched reservation IDs, and signed quote constraints", async (t) => {
  const cases = { null: null, array: [], string: "quote", missing: {},
    wrongReservation: { ...response(), reservation_id: 43 },
    stringReservation: { ...response(), reservation_id: "42" },
  };
  for (const quote_id of [undefined, null, "", " \n\t", 7, {}, "x".repeat(16385)]) {
    cases[`signed quote ${typeof quote_id} length ${quote_id?.length}`] = { ...response(), quote_id };
  }
  for (const [name, value] of Object.entries(cases)) {
    await t.test(name, async () => {
      respond(value);
      await assert.rejects(getReservationChangeQuote(42, review()), { message: "Reservation change quote returned an unexpected response" });
      assertQuotePost();
    });
  }
});

test("retains maximum-length opaque quotes and aware timestamp offsets without decoding or trimming", async () => {
  const value = response();
  value.quote_id = ` ${"x".repeat(16382)} `;
  value.expires_at = "2096-02-29T23:59:59.123456-08:00";
  respond(value);
  assert.deepEqual(await getReservationChangeQuote(42, review()), value);
  assertQuotePost();
});

test("measures the backend quote-length constraint in Unicode characters while preserving opaque bytes", async () => {
  const value = response();
  value.quote_id = "🌍".repeat(16384);
  respond(value);
  assert.equal((await getReservationChangeQuote(42, review())).quote_id, value.quote_id);
  assertQuotePost();
});

test("rejects missing, malformed, naive, impossible, and expired expiration timestamps", async (t) => {
  for (const expires_at of [undefined, null, 0, "", "soon", "2096-02-29", "2096-02-29T12:00:00",
    "2095-02-29T12:00:00Z", "2096-02-30T12:00:00Z", "2096-02-29T24:00:00Z",
    "2096-02-29T12:60:00Z", "2096-02-29T12:00:60Z", "2096-02-29T12:00:00+24:00",
    "2096-02-29T12:00:00Z\n",
    "2000-01-01T00:00:00Z", new Date(Date.now() - 1000).toISOString()]) {
    await t.test(String(expires_at), async () => {
      respond({ ...response(), expires_at });
      await assert.rejects(getReservationChangeQuote(42, review()), { message: "Reservation change quote returned an unexpected response" });
      assertQuotePost();
    });
  }
});

test("requires every nested revalidation field, including explicit nullable values", async (t) => {
  for (const key of Object.keys(response().quote)) {
    await t.test(`missing ${key}`, async () => {
      const value = response();
      delete value.quote[key];
      respond(value);
      await assert.rejects(getReservationChangeQuote(42, review()), { message: "Reservation change quote returned an unexpected response" });
      assertQuotePost();
    });
  }
});

test("rejects invalid nested identity, dates, occupancy, availability, and rate metadata", async (t) => {
  const changes = [
    { property_token: "" }, { property_token: " \t" }, { property_token: 42 }, { property_token: "x".repeat(256) },
    { hotel_name: "" }, { hotel_name: "  " }, { hotel_name: null }, { hotel_name: "x".repeat(256) },
    { check_in_date: "2096-02-29" }, { check_out_date: "2096-03-02" }, { check_in_date: "2096-02-28T00:00:00Z" },
    { adults: 1 }, { adults: "2" }, { children: 0 }, { children: "1" }, { currency: "EUR" },
    { number_of_nights: 1 }, { number_of_nights: 0 }, { number_of_nights: 2.5 }, { number_of_nights: "2" },
    { availability: "unavailable" }, { availability: true }, { rate_rule: "cheapest" },
    { source: " \n" }, { source: 1 }, { guest_capacity: 2 }, { guest_capacity: 3.5 },
    { guest_capacity: "3" }, { guest_capacity: Infinity }, { guest_capacity: Number.MAX_SAFE_INTEGER + 1 },
    { price_changed: "false" }, { price_changed: 0 },
  ];
  for (const [index, change] of changes.entries()) {
    await t.test(`${index}: ${Object.keys(change)[0]}`, async () => {
      const value = response();
      Object.assign(value.quote, change);
      respond(value);
      await assert.rejects(getReservationChangeQuote(42, review()), { message: "Reservation change quote returned an unexpected response" });
      assertQuotePost();
    });
  }
  for (const quote of [null, [], "quote"]) {
    await t.test(`invalid quote ${String(quote)}`, async () => {
      respond({ ...response(), quote });
      await assert.rejects(getReservationChangeQuote(42, review()), { message: "Reservation change quote returned an unexpected response" });
      assertQuotePost();
    });
  }
});

test("rejects missing, nonnumeric, nonfinite, and nonpositive prices without substituting zero", async (t) => {
  for (const key of ["current_price_per_night", "provider_base_total", "provider_total_with_taxes_fees",
    "likehome_reservation_total", "likehome_payment_amount"]) {
    const invalid = [undefined, "100", true, 0, -1, NaN, Infinity, -Infinity];
    if (key !== "provider_total_with_taxes_fees") invalid.push(null);
    for (const [index, amount] of invalid.entries()) {
      await t.test(`${key}: invalid amount ${index}`, async () => {
        const value = response();
        value.quote[key] = amount;
        respond(value);
        await assert.rejects(getReservationChangeQuote(42, review()), { message: "Reservation change quote returned an unexpected response" });
        assertQuotePost();
      });
    }
  }
});

test("preserves authoritative prices instead of recomputing provider totals or LikeHome fees", async () => {
  const value = response();
  value.quote.current_price_per_night = 99.99;
  value.quote.provider_base_total = 200.01;
  value.quote.likehome_reservation_total = 210.01;
  value.quote.likehome_payment_amount = 226.81;
  respond(value);
  assert.deepEqual(await getReservationChangeQuote(42, review()), value);
  assertQuotePost();
});

test("propagates HTTP status without retry, token removal, or server-body disclosure", async (t) => {
  for (const status of [400, 401, 404, 409, 422, 502, 504, 500]) {
    await t.test(String(status), async () => {
      globalThis.fetch = async (url, init) => {
        calls.push({ url, init });
        return { ok: false, status, json: async () => { throw new Error("Error bodies must not be read"); } };
      };
      await assert.rejects(getReservationChangeQuote(42, review()), (error) =>
        error instanceof ApiError && error.status === status && error.message === `API request failed with status ${status}`);
      assertQuotePost();
      assert.equal(entries.get("likehome_access_token"), token);
    });
  }
});

test("propagates a network failure unchanged with exactly one request", async () => {
  const failure = new TypeError("Synthetic network failure");
  globalThis.fetch = async (url, init) => { calls.push({ url, init }); throw failure; };
  await assert.rejects(getReservationChangeQuote(42, review()), (error) => error === failure);
  assertQuotePost();
});

test("invalid JSON uses the existing safe API error without exposing the response body", async () => {
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    return { ok: true, json: async () => { throw new Error(`${quoteId} ${token}`); } };
  };
  await assert.rejects(getReservationChangeQuote(42, review()), { message: "API returned an invalid JSON response" });
  assertQuotePost();
});
