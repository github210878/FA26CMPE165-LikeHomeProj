import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import { ApiError } from "../lib/api.ts";
import { getReservationFinancialSummary } from "../lib/bookings.ts";

const originalFetch = globalThis.fetch;
const originalWindow = globalThis.window;
const token = "synthetic-financial-summary-token";
const settledAt = "2026-10-15T12:30:45.123456+00:00";

beforeEach(() => {
  globalThis.fetch = async () => { throw new Error("Unexpected network request"); };
});
afterEach(() => {
  globalThis.fetch = originalFetch;
  globalThis.window = originalWindow;
});

function session(accessToken = token) {
  const entries = new Map(accessToken === null ? [] : [["likehome_access_token", accessToken]]);
  const writes = [];
  globalThis.window = { sessionStorage: {
    getItem: (key) => entries.get(key) ?? null,
    setItem: (key, value) => { writes.push("set"); entries.set(key, value); },
    removeItem: (key) => { writes.push("remove"); entries.delete(key); },
    clear: () => { writes.push("clear"); entries.clear(); },
  } };
  return { writes, entries };
}

function summary() {
  return {
    reservation_id: 42, reservation_revision: 0, reservation_status: "confirmed", currency: "USD",
    latest_change_id: null, current_reservation_total: 210, current_booking_obligation: 226.8,
    original_booking_payment: { payment_id: 11, reservation_id: 42, amount: 226.8,
      payment_type: "booking", payment_status: "pending" },
    paid_additional_charges: 0, pending_additional_charges: 0, failed_additional_charges: 0,
    recorded_internal_credits: 0, outstanding_additional_amount: 0, adjustments: [],
    voided_additional_charges: 0, cancellation_reconciliations: [], reconciliation_credits: 0,
    reconciliation_debits: 0, cancellation_payment: null, outstanding_cancellation_amount: 0,
    outstanding_booking_amount: 226.8,
  };
}

function changed(status = "pending", kind = "charge") {
  const value = summary();
  value.original_booking_payment.payment_status = "paid";
  value.outstanding_booking_amount = 0;
  value.reservation_revision = status === "paid" ? 2 : 1;
  value.latest_change_id = 7;
  value.current_reservation_total = kind === "credit" ? 168 : 252;
  value.current_booking_obligation = kind === "credit" ? 181.44 : 272.16;
  value.adjustments = [{ adjustment_id: 101, change_id: 7, reservation_id: 42, currency: "USD",
    entry_role: "price_change", reconciles_adjustment_id: null, kind, amount: 45.36, status,
    settled_at: status === "paid" ? settledAt : null }];
  const field = kind === "credit" ? "recorded_internal_credits" : `${status}_additional_charges`;
  value[field] = 45.36;
  value.outstanding_additional_amount = ["pending", "failed"].includes(status) ? 45.36 : 0;
  return value;
}

function cancelled(kind = "charge") {
  const value = changed(kind === "charge" ? "paid" : "recorded", kind);
  value.reservation_status = "cancelled";
  value.reservation_revision += 1;
  value.original_booking_payment.payment_status = "refunded";
  value.cancellation_payment = { payment_id: 12, reservation_id: 42, amount: kind === "charge" ? 50.4 : 33.6,
    payment_type: "cancellation", payment_status: "pending" };
  value.outstanding_cancellation_amount = value.cancellation_payment.amount;
  value.cancellation_reconciliations = [{ ...value.adjustments[0], adjustment_id: 102,
    entry_role: "cancellation_reconciliation", reconciles_adjustment_id: 101,
    kind: kind === "charge" ? "credit" : "charge", status: "recorded", settled_at: null }];
  value[kind === "charge" ? "reconciliation_credits" : "reconciliation_debits"] = 45.36;
  return value;
}

function respond(value) {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    return { ok: true, json: async () => value };
  };
  return calls;
}

function assertReadOnly(calls) {
  assert.equal(calls.length, 1);
  const { url, init } = calls[0];
  const expectedBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
  assert.equal(url, `${expectedBase}/bookings/42/financial-summary`);
  assert.equal(init.method ?? "GET", "GET");
  assert.equal(init.body, undefined);
  assert.equal(init.cache, "no-store");
  assert.deepEqual(init.headers, { Authorization: `Bearer ${token}` });
  assert.ok(!url.includes(token));
}

test("unchanged reservation is read with one authorized bodyless no-store GET and no session writes", async () => {
  const storage = session();
  const value = summary();
  const calls = respond(value);
  assert.deepEqual(await getReservationFinancialSummary(42), value);
  assertReadOnly(calls);
  assert.deepEqual(storage.writes, []);
  assert.equal(storage.entries.get("likehome_access_token"), token);
});

test("paid history preserves original payment and separate pending, failed, settled, credit and cancellation entries", async (t) => {
  const voided = changed("voided");
  voided.reservation_status = "cancelled";
  voided.original_booking_payment.payment_status = "refunded";
  voided.cancellation_payment = { payment_id: 12, reservation_id: 42, amount: 50.4,
    payment_type: "cancellation", payment_status: "pending" };
  voided.outstanding_cancellation_amount = 50.4;
  const completed = summary();
  completed.reservation_status = "completed";
  completed.original_booking_payment.payment_status = "paid";
  completed.outstanding_booking_amount = 0;
  const cases = { pending: changed(), failed: changed("failed"), paid: changed("paid"),
    credit: changed("recorded", "credit"), paidChargeReversal: cancelled(),
    recordedCreditReversal: cancelled("credit"), voided, completed };
  for (const [name, value] of Object.entries(cases)) {
    await t.test(name, async () => {
      const storage = session();
      const calls = respond(value);
      const result = await getReservationFinancialSummary(42);
      assert.deepEqual(result, value);
      assert.equal(result.original_booking_payment.amount, 226.8);
      assertReadOnly(calls);
      assert.deepEqual(storage.writes, []);
    });
  }
});

test("nullable fields, revision boundaries, zero cancellation fee and large aggregate numbers are retained", async () => {
  session();
  const value = summary();
  value.reservation_revision = 4294967295;
  value.latest_change_id = 7; // A date/price-neutral change need not have an adjustment.
  respond(value);
  assert.deepEqual(await getReservationFinancialSummary(42), value);
  const cancellation = summary();
  cancellation.reservation_status = "cancelled";
  cancellation.reservation_revision = 1;
  cancellation.current_reservation_total = 0.01;
  cancellation.current_booking_obligation = cancellation.original_booking_payment.amount = 0.01;
  cancellation.outstanding_booking_amount = 0;
  cancellation.cancellation_payment = { payment_id: 12, reservation_id: 42, amount: 0,
    payment_type: "cancellation", payment_status: "pending" };
  respond(cancellation);
  assert.deepEqual(await getReservationFinancialSummary(42), cancellation);
  const large = changed("paid");
  large.adjustments.push({ ...large.adjustments[0], adjustment_id: 103, change_id: 8, amount: 99999999.99 });
  large.adjustments[0].amount = 99999999.99;
  large.latest_change_id = 8;
  large.reservation_revision = 4;
  large.paid_additional_charges = 199999999.98;
  respond(large);
  assert.equal((await getReservationFinancialSummary(42)).paid_additional_charges, 199999999.98);
});

test("invalid reservation IDs and absent or unavailable authentication never send requests", async () => {
  const storage = session();
  const calls = respond(summary());
  for (const id of [0, -1, 1.5, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1, "42", true, null, undefined]) {
    await assert.rejects(getReservationFinancialSummary(id), /Invalid reservation ID/);
  }
  assert.deepEqual(storage.writes, []);
  const missing = session(null);
  await assert.rejects(getReservationFinancialSummary(42), (e) => e instanceof ApiError && e.status === 401);
  assert.deepEqual(missing.writes, []);
  globalThis.window = undefined;
  await assert.rejects(getReservationFinancialSummary(42), (e) => e instanceof ApiError && e.status === 401);
  globalThis.window = { get sessionStorage() { throw new Error("Storage unavailable"); } };
  await assert.rejects(getReservationFinancialSummary(42), (e) => e instanceof ApiError && e.status === 401);
  assert.equal(calls.length, 0);
});

test("HTTP errors retain ApiError status and the stored session without retries or mutations", async () => {
  const storage = session();
  for (const status of [401, 404, 409, 422, 500, 503]) {
    const calls = [];
    globalThis.fetch = async (url, init) => {
      calls.push({ url, init });
      return new Response("sensitive server detail", { status });
    };
    await assert.rejects(getReservationFinancialSummary(42), (error) =>
      error instanceof ApiError && error.status === status &&
      !error.message.includes("sensitive") && !error.message.includes(token));
    assertReadOnly(calls);
  }
  assert.deepEqual(storage.writes, []);
  assert.equal(storage.entries.get("likehome_access_token"), token);
});

test("network errors propagate unchanged and invalid JSON keeps the existing controlled error", async () => {
  session();
  const failure = new TypeError("Synthetic network interruption");
  let calls = 0;
  globalThis.fetch = async () => { calls += 1; throw failure; };
  await assert.rejects(getReservationFinancialSummary(42), (error) => error === failure);
  assert.equal(calls, 1);
  globalThis.fetch = async () => new Response("invalid JSON");
  await assert.rejects(getReservationFinancialSummary(42), /API returned an invalid JSON response/);
});

test("malformed or missing top-level financial data is rejected without defaulting history or money", async (t) => {
  const cases = {
    null: () => null, array: () => [], empty: () => ({}), wrongReservation: (v) => ({ ...v, reservation_id: 43 }),
    wrongCurrency: (v) => ({ ...v, currency: "EUR" }), wrongStatus: (v) => ({ ...v, reservation_status: "paid" }),
    negativeRevision: (v) => ({ ...v, reservation_revision: -1 }), fractionalRevision: (v) => ({ ...v, reservation_revision: 0.5 }),
    excessiveRevision: (v) => ({ ...v, reservation_revision: 4294967296 }), stringRevision: (v) => ({ ...v, reservation_revision: "1" }),
    invalidLatestId: (v) => ({ ...v, latest_change_id: 0 }), unsafeLatestId: (v) => ({ ...v, latest_change_id: Number.MAX_SAFE_INTEGER + 1 }),
    stringMoney: (v) => ({ ...v, current_reservation_total: "210.00" }), zeroTotal: (v) => ({ ...v, current_reservation_total: 0 }),
    zeroObligation: (v) => ({ ...v, current_booking_obligation: 0 }), nanMoney: (v) => ({ ...v, current_booking_obligation: NaN }),
    infiniteMoney: (v) => ({ ...v, paid_additional_charges: Infinity }), negativeMoney: (v) => ({ ...v, outstanding_booking_amount: -0.01 }),
    nullHistory: (v) => ({ ...v, adjustments: null }), invalidHistory: (v) => ({ ...v, adjustments: {} }),
    nullReconciliations: (v) => ({ ...v, cancellation_reconciliations: null }),
    unexpectedCancellation: (v) => ({ ...v, cancellation_payment: cancelled().cancellation_payment }),
  };
  for (const key of Object.keys(summary())) {
    cases[`missing ${key}`] = (v) => { delete v[key]; return v; };
  }
  for (const [name, change] of Object.entries(cases)) {
    await t.test(name, async () => {
      const storage = session();
      const calls = respond(change(summary()));
      await assert.rejects(getReservationFinancialSummary(42), /^Error: Reservation financial summary returned an unexpected response$/);
      assertReadOnly(calls);
      assert.deepEqual(storage.writes, []);
    });
  }
});

test("nested payment shapes, identities, amounts and cancellation data are validated", async (t) => {
  const cases = {
    missingPayment: (v) => { v.original_booking_payment = null; },
    wrongBookingType: (v) => { v.original_booking_payment.payment_type = "cancellation"; },
    wrongBookingReservation: (v) => { v.original_booking_payment.reservation_id = 43; },
    unsafePaymentId: (v) => { v.original_booking_payment.payment_id = Number.MAX_SAFE_INTEGER + 1; },
    fractionalPaymentId: (v) => { v.original_booking_payment.payment_id = 1.5; },
    zeroBookingAmount: (v) => { v.original_booking_payment.amount = 0; },
    stringBookingAmount: (v) => { v.original_booking_payment.amount = "226.80"; },
    missingBookingStatus: (v) => { delete v.original_booking_payment.payment_status; },
    invalidBookingStatus: (v) => { v.original_booking_payment.payment_status = "settled"; },
    missingCancellation: (v) => { v.cancellation_payment = null; },
    wrongCancellationType: (v) => { v.cancellation_payment.payment_type = "booking"; },
    wrongCancellationReservation: (v) => { v.cancellation_payment.reservation_id = 43; },
    duplicatePaymentId: (v) => { v.cancellation_payment.payment_id = 11; },
    negativeCancellationAmount: (v) => { v.cancellation_payment.amount = -1; },
    invalidCancellationStatus: (v) => { v.cancellation_payment.payment_status = "recorded"; },
    missingCancellationAmount: (v) => { delete v.cancellation_payment.amount; },
  };
  for (const [name, change] of Object.entries(cases)) {
    await t.test(name, async () => {
      session();
      const value = cancelled();
      change(value);
      const calls = respond(value);
      await assert.rejects(getReservationFinancialSummary(42), /unexpected response/);
      assertReadOnly(calls);
    });
  }
});

test("adjustment roles, lifecycle, timestamps and reconciliation links cannot be silently misread", async (t) => {
  const cases = {
    zeroId: (v) => { v.adjustments[0].adjustment_id = 0; },
    unsafeChangeId: (v) => { v.adjustments[0].change_id = Number.MAX_SAFE_INTEGER + 1; },
    wrongReservation: (v) => { v.adjustments[0].reservation_id = 43; },
    wrongCurrency: (v) => { v.adjustments[0].currency = "EUR"; },
    wrongRole: (v) => { v.adjustments[0].entry_role = "cancellation_reconciliation"; },
    wrongKind: (v) => { v.adjustments[0].kind = "refund"; },
    zeroAmount: (v) => { v.adjustments[0].amount = 0; },
    negativeAmount: (v) => { v.adjustments[0].amount = -1; },
    stringAmount: (v) => { v.adjustments[0].amount = "45.36"; },
    nonfiniteAmount: (v) => { v.adjustments[0].amount = Infinity; },
    unknownStatus: (v) => { v.adjustments[0].status = "refunded"; },
    recordedPrimaryCharge: (v) => { v.adjustments[0].status = "recorded"; },
    primaryParent: (v) => { v.adjustments[0].reconciles_adjustment_id = 99; },
    missingTimestamp: (v) => { delete v.adjustments[0].settled_at; },
    naiveTimestamp: (v) => { v.adjustments[0].settled_at = "2026-10-15T12:30:45"; },
    invalidTimestamp: (v) => { v.adjustments[0].settled_at = "not-a-date"; },
    impossibleDate: (v) => { v.adjustments[0].settled_at = "2026-02-30T12:30:45Z"; },
    unpaidWithTimestamp: (v) => { v.adjustments[0].status = "pending"; },
    paidWithoutTimestamp: (v) => { v.adjustments[0].settled_at = null; },
    paidCredit: (v) => { v.adjustments[0].kind = "credit"; },
    duplicateIds: (v) => { v.adjustments.push({ ...v.adjustments[0] }); },
    missingLatestChange: (v) => { v.latest_change_id = null; },
    wrongReconciliationRole: (v) => { v.cancellation_reconciliations[0].entry_role = "price_change"; },
    wrongReconciliationReservation: (v) => { v.cancellation_reconciliations[0].reservation_id = 43; },
    missingParent: (v) => { v.cancellation_reconciliations[0].reconciles_adjustment_id = null; },
    unknownParent: (v) => { v.cancellation_reconciliations[0].reconciles_adjustment_id = 999; },
    differentChange: (v) => { v.cancellation_reconciliations[0].change_id = 8; },
    sameKind: (v) => { v.cancellation_reconciliations[0].kind = "charge"; },
    wrongReversalAmount: (v) => { v.cancellation_reconciliations[0].amount = 45.35; },
    settledReconciliation: (v) => { v.cancellation_reconciliations[0].settled_at = settledAt; },
    pendingReconciliation: (v) => { v.cancellation_reconciliations[0].status = "pending"; },
    duplicateReversal: (v) => { v.cancellation_reconciliations.push({ ...v.cancellation_reconciliations[0], adjustment_id: 103 }); },
  };
  for (const [name, change] of Object.entries(cases)) {
    await t.test(name, async () => {
      session();
      const value = cancelled();
      change(value);
      const calls = respond(value);
      await assert.rejects(getReservationFinancialSummary(42), /unexpected response/);
      assertReadOnly(calls);
    });
  }
});
