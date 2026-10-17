import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import { ApiError } from "../lib/api.ts";
import { payReservationChangeAdjustment } from "../lib/bookings.ts";

const originals = { fetch: globalThis.fetch, window: globalThis.window, document: globalThis.document };
const token = "synthetic-adjustment-settlement-bearer";
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
  assert.deepEqual(writes, [], "settlement must not persist request details or mutate authentication storage");
  assert.deepEqual(logs, [], "settlement must not log bearer tokens, request bodies, or customer data");
});

function acknowledgement(overrides = {}) {
  return { accepted_amount: 81.44, reservation_revision: 1, accept_payment: true, ...overrides };
}

function settlement(amount = 81.44) {
  return { adjustment_id: 101, change_id: 7, reservation_id: 42, currency: "USD", entry_role: "price_change",
    reconciles_adjustment_id: null, kind: "charge", amount, status: "paid", settled_at: "2026-10-17T12:30:45.123456+00:00" };
}

function respond(value) {
  globalThis.fetch = async (url, init) => { calls.push({ url, init }); return { ok: true, json: async () => value }; };
}

function assertSettlementPost(expected = acknowledgement(), reservationId = 42, adjustmentId = 101, index = 0) {
  const { url, init } = calls[index];
  const base = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
  assert.equal(url, `${base}/bookings/${reservationId}/adjustments/${adjustmentId}/pay`);
  assert.equal(init.method, "POST");
  assert.deepEqual(init.headers, { Authorization: `Bearer ${token}`, "Content-Type": "application/json" });
  assert.deepEqual(JSON.parse(init.body), expected);
  assert.deepEqual(Object.keys(JSON.parse(init.body)).sort(), ["accept_payment", "accepted_amount", "reservation_revision"]);
  assert.ok(!url.includes(token) && !init.body.includes(token));
}

function assertOnlySettlement(expected = acknowledgement(), reservationId = 42, adjustmentId = 101) {
  assert.equal(calls.length, 1, "one settlement, no booking-payment/confirmation/cancellation/quote/summary endpoint or retry");
  assertSettlementPost(expected, reservationId, adjustmentId);
}

async function rejectsRequest(request) {
  await assert.rejects(payReservationChangeAdjustment(42, 101, request), { message: "Invalid adjustment settlement request" });
  assert.equal(calls.length, 0);
}

async function rejectsResponse(value, request = acknowledgement()) {
  respond(value);
  await assert.rejects(payReservationChangeAdjustment(42, 101, request), { message: "Adjustment settlement returned an unexpected response" });
  assertOnlySettlement(request);
}

test("sends the exact authenticated settlement POST once and returns the unchanged numeric response", async () => {
  const request = Object.freeze(acknowledgement()); const value = Object.freeze(settlement()); respond(value);
  assert.strictEqual(await payReservationChangeAdjustment(42, 101, request), value);
  assertOnlySettlement(request); assert.equal(typeof value.amount, "number");
  assert.equal(entries.get("likehome_access_token"), token);
});

test("validates nullable reconciliation identifiers according to the inherited Pydantic field", async (t) => {
  // The model permits null or an identifier. Persisted relationship eligibility
  // is the backend's responsibility; this adapter must not invent a ledger rule.
  for (const reconciles_adjustment_id of [null, 9, Number.MAX_SAFE_INTEGER]) {
    await t.test(String(reconciles_adjustment_id), async () => {
      const value = { ...settlement(), reconciles_adjustment_id }; respond(value);
      assert.strictEqual(await payReservationChangeAdjustment(42, 101, acknowledgement()), value);
      assertOnlySettlement();
    });
  }
});

test("missing or inaccessible authentication fails with 401 before fetching", async (t) => {
  for (const mode of ["missing", "server", "blocked"]) {
    await t.test(mode, async () => {
      if (mode === "missing") entries.clear();
      if (mode === "server") globalThis.window = undefined;
      if (mode === "blocked") Object.defineProperty(globalThis.window, "sessionStorage", { get() { throw new Error("Blocked storage"); } });
      await assert.rejects(payReservationChangeAdjustment(42, 101, acknowledgement()), (error) => error instanceof ApiError && error.status === 401);
      assert.equal(calls.length, 0);
    });
  }
});

test("both path IDs must be positive safe integers", async (t) => {
  for (const value of [0, -1, 1.5, "42", true, null, undefined, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
    for (const target of ["reservation", "adjustment"]) {
      await t.test(`${target}: ${String(value)}`, async () => {
        await assert.rejects(payReservationChangeAdjustment(target === "reservation" ? value : 42,
          target === "adjustment" ? value : 101, acknowledgement()),
        { message: target === "reservation" ? "Invalid reservation ID" : "Invalid adjustment ID" });
        assert.equal(calls.length, 0);
      });
    }
  }
});

test("rejects malformed request shapes and every missing required field", async (t) => {
  const cases = { null: null, array: [], string: "pay", number: 1 };
  for (const key of Object.keys(acknowledgement())) { const request = acknowledgement(); delete request[key]; cases[`missing ${key}`] = request; }
  for (const [name, request] of Object.entries(cases)) await t.test(name, () => rejectsRequest(request));
});

test("acceptance must be explicit boolean true, never supplied or coerced by the adapter", async (t) => {
  for (const accept_payment of [undefined, null, false, 0, 1, "true", "false", {}, []]) {
    await t.test(`${typeof accept_payment}: ${String(accept_payment)}`, () => rejectsRequest(acknowledgement({ accept_payment })));
  }
});

test("rejects extra customer/property/quote/reward/amount/state fields rather than serializing them", async (t) => {
  for (const key of ["user_id", "customer_id", "property_token", "hotel_id", "quote_id", "reward_points", "amount", "adjustment_amount",
    "adjustment_id", "reservation_id", "status", "kind", "currency", "toJSON"]) {
    await t.test(key, () => rejectsRequest(acknowledgement({ [key]: "untrusted" })));
  }
});

test("accepted amount must be numeric, finite, positive, and no greater than the backend monetary bound", async (t) => {
  for (const accepted_amount of [undefined, null, "81.44", true, false, 0, -1, NaN, Infinity, -Infinity, 100000000, {}, []]) {
    await t.test(`${typeof accepted_amount}: ${String(accepted_amount)}`, () => rejectsRequest(acknowledgement({ accepted_amount })));
  }
});

test("revision must be a nonnegative integer in the backend uint32 range", async (t) => {
  for (const reservation_revision of [undefined, null, "1", true, -1, 1.5, NaN, Infinity, 4294967296, Number.MAX_SAFE_INTEGER]) {
    await t.test(String(reservation_revision), () => rejectsRequest(acknowledgement({ reservation_revision })));
  }
});

test("revision zero and max uint32 remain structurally valid without guessing the current revision", async (t) => {
  for (const reservation_revision of [0, 4294967295]) {
    await t.test(String(reservation_revision), async () => {
      const request = acknowledgement({ reservation_revision }); const value = settlement(); respond(value);
      assert.strictEqual(await payReservationChangeAdjustment(42, 101, request), value); assertOnlySettlement(request);
    });
  }
});

test("safe path and change IDs may reach the JS safe-integer boundary and need not be distinct across tables", async () => {
  const value = { ...settlement(), reservation_id: Number.MAX_SAFE_INTEGER, adjustment_id: Number.MAX_SAFE_INTEGER, change_id: Number.MAX_SAFE_INTEGER };
  respond(value);
  assert.strictEqual(await payReservationChangeAdjustment(Number.MAX_SAFE_INTEGER, Number.MAX_SAFE_INTEGER, acknowledgement()), value);
  assertOnlySettlement(acknowledgement(), Number.MAX_SAFE_INTEGER, Number.MAX_SAFE_INTEGER);
});

test("cent comparisons match decimal half-up while preserving accepted numbers and response objects", async (t) => {
  for (const [accepted_amount, amount] of [
    [81.44 + 1e-12, 81.44], [0.010000000000001, 0.01], [0.1 + 0.2, 0.3],
    [1.005, 1.01], [10.075, 10.08], [2.675, 2.68], [1.0049, 1],
    [1.0149, 1.01], [1.015, 1.02], [0.005, 0.01], [0.0099, 0.01],
    [99999999.985, 99999999.99], [99999999.984, 99999999.98], [99999999.99, 99999999.99],
  ]) {
    await t.test(`${accepted_amount} acknowledged as ${amount}`, async () => {
      const request = Object.freeze(acknowledgement({ accepted_amount })); const value = Object.freeze(settlement(amount)); respond(value);
      assert.strictEqual(await payReservationChangeAdjustment(42, 101, request), value); assertOnlySettlement(request);
      assert.equal(JSON.parse(calls[0].init.body).accepted_amount, accepted_amount);
      assert.equal(value.amount, amount);
    });
  }
});

test("different cents are rejected, including half-cent boundaries and exponent-notation edge cases", async (t) => {
  for (const [accepted_amount, amount] of [
    [81.44, 81.45], [1.005, 1], [1.015, 1.01], [0.0049, 0.01],
    [1e-7, 0.01], [Number.MIN_VALUE, 0.01], [81.44, 1e20], [81.44, Number.MAX_VALUE],
    [81.44, Number.MIN_VALUE], [99999999.985, 99999999.98],
  ]) await t.test(`${accepted_amount} versus ${amount}`, () => rejectsResponse(settlement(amount), acknowledgement({ accepted_amount })));
});

test("sub-cent positive acknowledgements are sent unchanged for backend eligibility decisions", async () => {
  const request = acknowledgement({ accepted_amount: Number.MIN_VALUE });
  globalThis.fetch = async (url, init) => { calls.push({ url, init }); return { ok: false, status: 409 }; };
  await assert.rejects(payReservationChangeAdjustment(42, 101, request), (error) => error instanceof ApiError && error.status === 409);
  assertOnlySettlement(request);
});

test("valid settlement timestamp strings retain timezone offsets, microseconds, and historical calendar dates", async (t) => {
  for (const settled_at of ["2026-10-17T12:30:45Z", "2026-10-17T05:30:45.123456-07:00",
    "2096-02-29T23:59:59.1+05:30", "0001-01-01T00:00:00+00:00"]) {
    await t.test(settled_at, async () => {
      const value = { ...settlement(), settled_at }; respond(value);
      assert.strictEqual(await payReservationChangeAdjustment(42, 101, acknowledgement()), value); assertOnlySettlement();
    });
  }
});

test("rejects missing, naive, malformed, or impossible settlement timestamps", async (t) => {
  for (const settled_at of [undefined, null, 0, "", "soon", "2026-10-17", "2026-10-17T12:30:45",
    "2026-02-29T12:00:00Z", "2026-04-31T12:00:00Z", "2026-13-01T12:00:00Z", "0000-01-01T12:00:00Z",
    "2026-10-17T24:00:00Z", "2026-10-17T12:60:00Z", "2026-10-17T12:30:60Z", "2026-10-17T12:30:45+24:00",
    "2026-10-17T12:30:45Z\n", " 2026-10-17T12:30:45Z"]) {
    await t.test(String(settled_at), () => rejectsResponse({ ...settlement(), settled_at }));
  }
});

test("rejects malformed envelopes, every missing response field, and extra fields", async (t) => {
  const cases = { null: null, array: [], string: "paid", empty: {}, extra: { ...settlement(), external_transaction_id: "invented" } };
  for (const key of Object.keys(settlement())) { const value = settlement(); delete value[key]; cases[`missing ${key}`] = value; }
  for (const [name, value] of Object.entries(cases)) await t.test(name, () => rejectsResponse(value));
});

test("requires exact reservation and adjustment identities and a positive safe change ID", async (t) => {
  for (const reservation_id of [43, "42", 0, null, true]) await t.test(`reservation ${String(reservation_id)}`, () => rejectsResponse({ ...settlement(), reservation_id }));
  for (const adjustment_id of [102, "101", 0, null, true]) await t.test(`adjustment ${String(adjustment_id)}`, () => rejectsResponse({ ...settlement(), adjustment_id }));
  for (const change_id of [0, -1, 0.5, "7", null, true, Infinity, Number.MAX_SAFE_INTEGER + 1]) await t.test(`change ${String(change_id)}`, () => rejectsResponse({ ...settlement(), change_id }));
});

test("rejects unsupported currency, role, kind and nonpaid statuses", async (t) => {
  for (const [key, values] of [
    ["currency", ["EUR", "usd", "", null]], ["entry_role", ["cancellation_reconciliation", "", null]],
    ["kind", ["credit", "refund", "", null]], ["status", ["pending", "failed", "recorded", "voided", "PAID", null]],
  ]) for (const value of values) await t.test(`${key}: ${String(value)}`, () => rejectsResponse({ ...settlement(), [key]: value }));
});

test("nullable reconciliation IDs must be explicitly null or positive safe identifiers", async (t) => {
  for (const reconciles_adjustment_id of [undefined, 0, -1, 1.5, "9", true, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
    await t.test(String(reconciles_adjustment_id), () => rejectsResponse({ ...settlement(), reconciles_adjustment_id }));
  }
});

test("paid amount must be present, numeric, finite, and positive without silently substituting zero", async (t) => {
  for (const amount of [undefined, null, "81.44", true, false, 0, -1, NaN, Infinity, -Infinity, {}, []]) {
    await t.test(`${typeof amount}: ${String(amount)}`, () => rejectsResponse({ ...settlement(), amount }));
  }
});

test("explicit already-paid acknowledgement can keep an older revision and reuse identical request bytes", async () => {
  const value = Object.freeze(settlement()); const request = Object.freeze(acknowledgement({ reservation_revision: 0 })); respond(value);
  assert.strictEqual(await payReservationChangeAdjustment(42, 101, request), value);
  assert.strictEqual(await payReservationChangeAdjustment(42, 101, request), value);
  assert.equal(calls.length, 2); assert.equal(calls[0].init.body, calls[1].init.body);
  assertSettlementPost(request, 42, 101, 0); assertSettlementPost(request, 42, 101, 1);
});

test("caller edits while fetch is pending cannot replace the explicitly accepted snapshot", async () => {
  const request = acknowledgement(); const accepted = { ...request }; const value = settlement();
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init }); request.accepted_amount = 99; request.reservation_revision = 9;
    return { ok: true, json: async () => value };
  };
  assert.strictEqual(await payReservationChangeAdjustment(42, 101, request), value); assertOnlySettlement(accepted);
});

test("HTTP statuses propagate unchanged without unsafe body reads, retries, or valid-token removal", async (t) => {
  for (const status of [400, 401, 404, 409, 422, 500, 502, 504]) {
    await t.test(String(status), async () => {
      globalThis.fetch = async (url, init) => {
        calls.push({ url, init }); return { ok: false, status, json: async () => { throw new Error("Unsafe body must not be read"); } };
      };
      await assert.rejects(payReservationChangeAdjustment(42, 101, acknowledgement()), (error) =>
        error instanceof ApiError && error.status === status && error.message === `API request failed with status ${status}`);
      assertOnlySettlement(); assert.equal(entries.get("likehome_access_token"), token);
    });
  }
});

test("ambiguous network failure remains unchanged with no automatic retry; an explicit identical invocation stays possible", async () => {
  const request = Object.freeze(acknowledgement()); const failure = new TypeError("Synthetic response lost after possible commit"); let attempt = 0;
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init }); if (++attempt === 1) throw failure;
    return { ok: true, json: async () => settlement() };
  };
  await assert.rejects(payReservationChangeAdjustment(42, 101, request), (error) => error === failure); assertOnlySettlement(request);
  await payReservationChangeAdjustment(42, 101, request);
  assert.equal(calls.length, 2); assert.equal(calls[0].init.body, calls[1].init.body); assertSettlementPost(request, 42, 101, 1);
});

test("invalid JSON and malformed successful responses do not claim success or cause a refresh/retry", async (t) => {
  await t.test("invalid JSON", async () => {
    globalThis.fetch = async (url, init) => {
      calls.push({ url, init }); return { ok: true, json: async () => { throw new Error(`${token} private customer payload`); } };
    };
    await assert.rejects(payReservationChangeAdjustment(42, 101, acknowledgement()), { message: "API returned an invalid JSON response" }); assertOnlySettlement();
  });
  await t.test("wrong monetary acknowledgement", () => rejectsResponse(settlement(81.45)));
});
