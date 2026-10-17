import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import { ApiError } from "../lib/api.ts";
import { confirmReservationChange } from "../lib/bookings.ts";

const originals = { fetch: globalThis.fetch, window: globalThis.window, document: globalThis.document };
const token = "synthetic-confirmation-bearer";
const quoteId = "opaque-synthetic-confirmation-review";
const consoleMethods = ["log", "info", "warn", "error", "debug"];
const originalConsole = Object.fromEntries(consoleMethods.map((method) => [method, console[method]]));
let calls, writes, logs, entries;

beforeEach(() => {
  calls = []; writes = []; logs = [];
  entries = new Map([["likehome_access_token", token]]);
  const storage = (name, values) => ({
    getItem: (key) => values.get(key) ?? null,
    setItem: (...args) => writes.push([`${name}.setItem`, ...args]),
    removeItem: (...args) => writes.push([`${name}.removeItem`, ...args]),
    clear: () => writes.push([`${name}.clear`]),
  });
  globalThis.window = { sessionStorage: storage("session", entries), localStorage: storage("local", new Map()) };
  globalThis.document = { get cookie() { return ""; }, set cookie(value) { writes.push(["cookie", value]); } };
  globalThis.fetch = async (...args) => { calls.push(args); throw new Error("Unexpected network request"); };
  for (const method of consoleMethods) console[method] = (...args) => logs.push([method, ...args]);
});

afterEach(() => {
  for (const [key, value] of Object.entries(originals)) globalThis[key] = value;
  for (const method of consoleMethods) console[method] = originalConsole[method];
  assert.deepEqual(writes, [], "confirmation must not persist quotes or mutate authentication storage");
  assert.deepEqual(logs, [], "confirmation must not log quotes, bearer tokens, request bodies, or customer data");
});

function confirmation(overrides = {}) {
  return {
    check_in_date: "2096-11-20", check_out_date: "2096-11-22", quote_id: quoteId,
    accept_quote: true, price_per_night: 120, accepted_payment_amount: 272.16, ...overrides,
  };
}

function receipt(request = confirmation()) {
  return {
    change_id: 7, reservation_id: 42, revision: 1, room_type_id: 91,
    check_in_date: request.check_in_date, check_out_date: request.check_out_date,
    reservation_total: "252.00", payment_obligation: "272.16", previous_payment_obligation: "226.80",
    payment_difference: "45.36", booking_payment_id: 11, booking_payment_status: "pending", adjustment: null,
  };
}

function charge(request = confirmation()) {
  return { ...receipt(request), booking_payment_status: "paid",
    adjustment: { adjustment_id: 101, kind: "charge", amount: "45.36", status: "pending" } };
}

function credit(request = confirmation()) {
  return { ...receipt(request), reservation_total: "168.00", payment_obligation: "181.44",
    payment_difference: "-45.36", booking_payment_status: "paid",
    adjustment: { adjustment_id: 102, kind: "credit", amount: "45.36", status: "recorded" } };
}

function respond(value) {
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    return { ok: true, json: async () => value };
  };
}

function assertConfirmPost(expected = confirmation(), id = 42, index = 0) {
  const { url, init } = calls[index];
  const base = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
  assert.equal(url, `${base}/bookings/${id}/change-confirm`);
  assert.equal(init.method, "POST");
  assert.deepEqual(init.headers, { Authorization: `Bearer ${token}`, "Content-Type": "application/json" });
  assert.deepEqual(JSON.parse(init.body), expected);
  assert.ok(!url.includes(token) && !url.includes(expected.quote_id));
  assert.ok(!init.body.includes(token));
}

function assertOnlyConfirmation(expected = confirmation(), id = 42) {
  assert.equal(calls.length, 1, "one confirmation, no quote/summary/payment/cancellation endpoint or retry");
  assertConfirmPost(expected, id);
}

async function rejectsInput(request) {
  await assert.rejects(confirmReservationChange(42, request), { message: "Invalid reservation change confirmation" });
  assert.equal(calls.length, 0);
}

async function rejectsReceipt(value, request = confirmation()) {
  respond(value);
  await assert.rejects(confirmReservationChange(42, request), { message: "Reservation change confirmation returned an unexpected response" });
  assertOnlyConfirmation(request);
}

test("sends one authenticated confirmation with the exact six-field JSON body and returns an unchanged receipt", async () => {
  const request = Object.freeze(confirmation());
  const value = Object.freeze(receipt(request));
  respond(value);
  assert.strictEqual(await confirmReservationChange(42, request), value);
  assertOnlyConfirmation(request);
  assert.equal(entries.get("likehome_access_token"), token);
  assert.deepEqual(Object.keys(JSON.parse(calls[0].init.body)).sort(), Object.keys(request).sort());
});

test("supports no-adjustment, pending additional charge, and recorded internal credit historical receipts", async (t) => {
  const creditRequest = confirmation({ price_per_night: 80, accepted_payment_amount: 181.44 });
  const paidNoDifference = { ...receipt(), booking_payment_status: "paid", previous_payment_obligation: "272.16", payment_difference: "0.00" };
  const pendingDecrease = { ...credit(creditRequest), booking_payment_status: "pending", adjustment: null };
  for (const [name, request, value] of [
    ["pending booking with no adjustment", confirmation(), receipt()],
    ["paid booking with no price difference", confirmation(), paidNoDifference],
    ["pending booking repriced downward", creditRequest, pendingDecrease],
    ["pending additional charge", confirmation(), charge()],
    ["recorded internal credit", creditRequest, credit(creditRequest)],
  ]) {
    await t.test(name, async () => {
      respond(value);
      assert.strictEqual(await confirmReservationChange(42, request), value);
      assertOnlyConfirmation(request);
      for (const key of ["reservation_total", "payment_obligation", "previous_payment_obligation", "payment_difference"]) assert.equal(typeof value[key], "string");
      if (value.adjustment) assert.equal(typeof value.adjustment.amount, "string");
    });
  }
});

test("preserves exact cent strings beyond floating-point precision without parsing or recomputing them", async () => {
  const value = receipt();
  value.reservation_total = "9007199254740993.01";
  value.payment_obligation = "9007199254740993.09";
  value.previous_payment_obligation = "9007199254740993.10";
  value.payment_difference = "-0.01";
  respond(value);
  const result = await confirmReservationChange(42, confirmation());
  assert.strictEqual(result, value);
  assert.equal(result.payment_obligation, "9007199254740993.09");
  assertOnlyConfirmation();
});

test("uses the schema's two-decimal string formats without imposing numeric bounds or rewriting formatting", async () => {
  const value = receipt();
  value.reservation_total = "000252.00";
  value.payment_difference = "-0.00";
  respond(value);
  assert.strictEqual(await confirmReservationChange(42, confirmation()), value);
  assertOnlyConfirmation();
});

test("missing, server-side, and inaccessible authentication fail with 401 without a request", async (t) => {
  for (const mode of ["missing", "server", "blocked"]) {
    await t.test(mode, async () => {
      if (mode === "missing") entries.clear();
      if (mode === "server") globalThis.window = undefined;
      if (mode === "blocked") Object.defineProperty(globalThis.window, "sessionStorage", { get() { throw new Error("Blocked storage"); } });
      await assert.rejects(confirmReservationChange(42, confirmation()), (error) => error instanceof ApiError && error.status === 401);
      assert.equal(calls.length, 0);
    });
  }
});

test("rejects invalid reservation IDs before any request", async (t) => {
  for (const id of [0, -1, 0.5, Number.MAX_SAFE_INTEGER + 1, NaN, Infinity, "42", true, null, undefined]) {
    await t.test(String(id), async () => {
      await assert.rejects(confirmReservationChange(id, confirmation()), { message: "Invalid reservation ID" });
      assert.equal(calls.length, 0);
    });
  }
});

test("rejects malformed request shapes and every missing required field", async (t) => {
  const cases = { null: null, array: [], string: "confirm" };
  for (const key of Object.keys(confirmation())) {
    const request = confirmation(); delete request[key]; cases[`missing ${key}`] = request;
  }
  for (const [name, request] of Object.entries(cases)) await t.test(name, () => rejectsInput(request));
});

test("rejects forbidden identity, review-context, revision, reward, and arbitrary adjustment fields", async (t) => {
  for (const key of ["user_id", "customer_id", "hotel_id", "property_token", "q", "adults", "children", "currency", "gl", "hl",
    "reservation_revision", "revision", "adjustment_amount", "reward_points", "expires_at", "toJSON"]) {
    await t.test(key, () => rejectsInput(confirmation({ [key]: "untrusted" })));
  }
});

test("requires explicit boolean true acceptance and never supplies a default for callers", async (t) => {
  for (const accept_quote of [undefined, null, false, 1, 0, "true", "false", {}, []]) {
    await t.test(`${typeof accept_quote}: ${String(accept_quote)}`, () => rejectsInput(confirmation({ accept_quote })));
  }
});

test("rejects invalid opaque quote IDs according to the backend length constraint", async (t) => {
  for (const quote_id of [undefined, null, "", " \n\t", 1, true, {}, [], "x".repeat(16385), "🌍".repeat(16385)]) {
    await t.test(`${typeof quote_id} length ${quote_id?.length}`, () => rejectsInput(confirmation({ quote_id })));
  }
});

test("preserves opaque quote bytes, including whitespace and maximum Unicode character length", async (t) => {
  for (const quote_id of ["  opaque.signed.review  ", "x".repeat(16384), "🌍".repeat(16384)]) {
    await t.test(`length ${quote_id.length}`, async () => {
      const request = confirmation({ quote_id }); respond(receipt(request));
      await confirmReservationChange(42, request);
      assertOnlyConfirmation(request);
      assert.equal(JSON.parse(calls[0].init.body).quote_id, quote_id);
    });
  }
});

test("rejects noncanonical, impossible, equal, and reversed stay dates without imposing today", async (t) => {
  for (const [name, changes] of Object.entries({
    nonLeap: { check_in_date: "2095-02-29" }, impossibleDay: { check_out_date: "2096-11-31" },
    badMonth: { check_in_date: "2096-13-01" }, zeroDay: { check_in_date: "2096-11-00" },
    yearZero: { check_in_date: "0000-01-01" }, yearOverflow: { check_out_date: "10000-01-01" },
    unpadded: { check_in_date: "2096-1-20" }, timestamp: { check_in_date: "2096-11-20T00:00:00Z" },
    trailingNewline: { check_in_date: "2096-11-20\n" }, checkoutNewline: { check_out_date: "2096-11-22\n" },
    whitespace: { check_out_date: " 2096-11-22" }, missing: { check_in_date: "" },
    dateObject: { check_in_date: new Date() }, nonString: { check_out_date: 20961122 },
    equal: { check_out_date: "2096-11-20" }, reversed: { check_out_date: "2096-11-19" },
  })) await t.test(name, () => rejectsInput(confirmation(changes)));
});

test("rejects nonnumeric, nonfinite, nonpositive, and out-of-range accepted prices", async (t) => {
  for (const key of ["price_per_night", "accepted_payment_amount"]) {
    for (const value of [undefined, null, "120.00", true, false, 0, -0.01, NaN, Infinity, -Infinity, 100000000, {}, []]) {
      await t.test(`${key}: ${typeof value} ${String(value)}`, () => rejectsInput(confirmation({ [key]: value })));
    }
  }
});

test("preserves accepted-price precision and backend-supported positive boundaries without rounding", async (t) => {
  for (const amount of [0.001, 120.005, 99999999.99]) {
    await t.test(String(amount), async () => {
      const request = confirmation({ price_per_night: amount, accepted_payment_amount: amount });
      respond(receipt(request)); await confirmReservationChange(42, request); assertOnlyConfirmation(request);
    });
  }
});

test("accepts historical calendar dates and an opaque token with expired claims for backend receipt recognition", async (t) => {
  // Synthetic, unsigned fixture: the adapter must not decode or regenerate it.
  const expired = `e30.${Buffer.from(JSON.stringify({ exp: 1 })).toString("base64url")}.synthetic`;
  for (const [check_in_date, check_out_date] of [["2000-01-01", "2000-01-03"], ["0001-01-01", "0001-01-02"], ["2096-02-29", "2096-03-01"]]) {
    await t.test(check_in_date, async () => {
      const request = confirmation({ check_in_date, check_out_date, quote_id: expired });
      respond(receipt(request)); await confirmReservationChange(42, request); assertOnlyConfirmation(request);
    });
  }
});

test("exact caller-initiated retries send identical bytes and preserve an immutable historical receipt", async () => {
  const request = Object.freeze(confirmation({ check_in_date: "2000-01-01", check_out_date: "2000-01-03" }));
  const value = Object.freeze({ ...charge(request), adjustment: Object.freeze(charge(request).adjustment) });
  respond(value);
  assert.strictEqual(await confirmReservationChange(42, request), value);
  assert.strictEqual(await confirmReservationChange(42, request), value);
  assert.equal(calls.length, 2); assert.equal(calls[0].init.body, calls[1].init.body);
  assertConfirmPost(request, 42, 0); assertConfirmPost(request, 42, 1);
  assert.equal(value.adjustment.status, "pending", "historical receipt is not reinterpreted as current settlement status");
});

test("network ambiguity is propagated without retry, while a later explicit identical call remains possible", async () => {
  const request = Object.freeze(confirmation()); const failure = new TypeError("Synthetic response lost after possible commit");
  let attempt = 0;
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    if (++attempt === 1) throw failure;
    return { ok: true, json: async () => receipt(request) };
  };
  await assert.rejects(confirmReservationChange(42, request), (error) => error === failure);
  assertOnlyConfirmation(request);
  await confirmReservationChange(42, request);
  assert.equal(calls.length, 2); assert.equal(calls[0].init.body, calls[1].init.body);
  assertConfirmPost(request, 42, 1);
});

test("caller edits during fetch cannot change the accepted snapshot or receipt-date checks", async () => {
  const request = confirmation(); const accepted = { ...request }; const value = receipt(request);
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init }); request.check_in_date = "2096-12-01"; request.accepted_payment_amount = 999;
    return { ok: true, json: async () => value };
  };
  assert.strictEqual(await confirmReservationChange(42, request), value);
  assertOnlyConfirmation(accepted);
});

test("rejects malformed envelopes, missing required fields, and unexpected receipt fields", async (t) => {
  const cases = { null: null, array: [], string: "receipt", empty: {}, extra: { ...receipt(), quote_id: quoteId } };
  for (const key of Object.keys(receipt())) { const value = receipt(); delete value[key]; cases[`missing ${key}`] = value; }
  for (const [name, value] of Object.entries(cases)) await t.test(name, () => rejectsReceipt(value));
});

test("rejects wrong reservation identities and unsafe record IDs", async (t) => {
  for (const reservation_id of [43, "42", null, 0]) await t.test(`reservation ${String(reservation_id)}`, () => rejectsReceipt({ ...receipt(), reservation_id }));
  for (const key of ["change_id", "room_type_id", "booking_payment_id"]) {
    for (const value of [0, -1, 1.5, "7", true, null, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
      await t.test(`${key}: ${String(value)}`, () => rejectsReceipt({ ...receipt(), [key]: value }));
    }
  }
});

test("accepts safe ID and revision upper boundaries", async () => {
  const value = { ...receipt(), reservation_id: Number.MAX_SAFE_INTEGER, change_id: Number.MAX_SAFE_INTEGER,
    room_type_id: Number.MAX_SAFE_INTEGER, booking_payment_id: Number.MAX_SAFE_INTEGER, revision: 4294967295 };
  respond(value);
  assert.strictEqual(await confirmReservationChange(Number.MAX_SAFE_INTEGER, confirmation()), value);
  assertOnlyConfirmation(confirmation(), Number.MAX_SAFE_INTEGER);
});

test("rejects invalid revisions and unsupported payment statuses", async (t) => {
  for (const revision of [0, -1, 1.5, "1", true, null, Infinity, 4294967296]) await t.test(`revision ${String(revision)}`, () => rejectsReceipt({ ...receipt(), revision }));
  for (const booking_payment_status of [undefined, null, "failed", "refunded", "cancelled", "PAID", true]) {
    await t.test(`payment ${String(booking_payment_status)}`, () => rejectsReceipt({ ...receipt(), booking_payment_status }));
  }
});

test("receipt dates must be valid canonical dates matching exactly the accepted request", async (t) => {
  for (const changes of [
    { check_in_date: "2096-11-21" }, { check_out_date: "2096-11-23" },
    { check_in_date: "2095-02-29" }, { check_out_date: "2096-11-31" },
    { check_in_date: "2096-11-20T00:00:00Z" }, { check_out_date: "2096-11-22\n" },
    { check_in_date: "2096-1-20" }, { check_in_date: null },
  ]) await t.test(JSON.stringify(changes), () => rejectsReceipt({ ...receipt(), ...changes }));
});

test("validates every receipt money field as a required canonical two-decimal string with the correct sign policy", async (t) => {
  const invalid = [undefined, null, 0, 252, true, "", "252", "252.0", "252.000", ".25", "1e2", "NaN", "Infinity",
    "+252.00", "$252.00", "1,252.00", " 252.00", "252.00 ", "252.00\n", "252.0x"];
  for (const key of ["reservation_total", "payment_obligation", "previous_payment_obligation", "payment_difference"]) {
    for (const [index, value] of invalid.entries()) await t.test(`${key}: invalid ${index}`, () => rejectsReceipt({ ...receipt(), [key]: value }));
    if (key !== "payment_difference") await t.test(`${key}: negative`, () => rejectsReceipt({ ...receipt(), [key]: "-1.00" }));
  }
});

test("requires complete optional adjustment structures, canonical unsigned amounts, and confirmation-time kind/status pairs", async (t) => {
  const cases = { array: [], string: "adjustment", missing: {},
    extra: { ...charge().adjustment, settled_at: null },
    chargeRecorded: { ...charge().adjustment, status: "recorded" },
    creditPending: { ...credit().adjustment, status: "pending" },
    paid: { ...charge().adjustment, status: "paid" },
    failed: { ...charge().adjustment, status: "failed" },
    voided: { ...charge().adjustment, status: "voided" },
    refund: { ...credit().adjustment, kind: "refund" },
    missingOptional: undefined,
  };
  for (const key of Object.keys(charge().adjustment)) {
    const value = { ...charge().adjustment }; delete value[key]; cases[`missing ${key}`] = value;
  }
  for (const amount of [undefined, null, 45.36, "-45.36", "45.3", "45.360", "+45.36", "45.36\n", "1e2"]) {
    cases[`amount ${String(amount)}`] = { ...charge().adjustment, amount };
  }
  for (const adjustment_id of [0, -1, 0.5, "101", true, null, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
    cases[`ID ${String(adjustment_id)}`] = { ...charge().adjustment, adjustment_id };
  }
  for (const [name, adjustment] of Object.entries(cases)) await t.test(name, () => rejectsReceipt({ ...charge(), adjustment }));
});

test("HTTP error statuses propagate unchanged without reading unsafe bodies, retries, or clearing a valid token", async (t) => {
  for (const status of [400, 401, 404, 409, 422, 500, 502, 504]) {
    await t.test(String(status), async () => {
      globalThis.fetch = async (url, init) => {
        calls.push({ url, init });
        return { ok: false, status, json: async () => { throw new Error("Error payload must not be read"); } };
      };
      await assert.rejects(confirmReservationChange(42, confirmation()), (error) =>
        error instanceof ApiError && error.status === status && error.message === `API request failed with status ${status}`);
      assertOnlyConfirmation(); assert.equal(entries.get("likehome_access_token"), token);
    });
  }
});

test("invalid JSON is a controlled error and is never retried or replaced with a fake receipt", async () => {
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    return { ok: true, json: async () => { throw new Error(`${quoteId} ${token} private body`); } };
  };
  await assert.rejects(confirmReservationChange(42, confirmation()), { message: "API returned an invalid JSON response" });
  assertOnlyConfirmation();
});

test("a malformed success after a possible commit is not retried or hidden by a refresh", async () => {
  await rejectsReceipt({ ...receipt(), payment_obligation: 272.16 });
  assert.equal(entries.get("likehome_access_token"), token);
});
