import assert from "node:assert/strict";
import { test } from "node:test";
import { bookingConfirmationHref } from "../lib/booking-confirmation.ts";
import { classifyRedemptionConfirmation } from "../lib/redemption-confirmation.ts";

const booking = {
  reservation_id: 42, hotel_name: "Harbor Hotel", status: "confirmed",
  check_in_date: "2027-01-10", check_out_date: "2027-01-12",
};
const paid = {
  reservation_id: 42, payment_id: 11, amount: 306.18,
  payment_type: "booking", payment_status: "paid",
};
const receipt = {
  status: "confirmed", redemption_type: "free_stay", currency: "USD",
  reservation_id: 42, payment_id: 11, booking_reference: "LH-00000042",
  points_redeemed: 30618, points_funded_value_cents: 30618, remaining_cash_due_cents: 0,
};
const classify = (options = {}) => classifyRedemptionConfirmation({ requested: true, booking, payment: paid, ...options });

test("a matching, authenticated points receipt supplies the confirmed values", () => {
  assert.deepEqual(classify({ requested: false, serverEvidence: receipt }), {
    kind: "confirmed", bookingReference: "LH-00000042", hotelName: "Harbor Hotel",
    checkInDate: "2027-01-10", checkOutDate: "2027-01-12", pointsRedeemed: 30618,
    pointsFundedValueCents: 30618, remainingCashDueCents: 0,
  });
});

test("a paid booking remains ordinary without intent or linked evidence", () => {
  assert.equal(classify({ requested: false }), null);
  assert.equal(bookingConfirmationHref(booking), "/booking-confirmation/42");
});

test("query intent and a generic paid response can show only unverified redemption", () => {
  assert.equal(bookingConfirmationHref(booking, true), "/booking-confirmation/42?redeem=1");
  assert.deepEqual(classify({ payment: { ...paid, ...receipt } }), { kind: "unverified" });
  assert.deepEqual(classify({ serverEvidence: null }), { kind: "unverified" });
});

test("pending, failed and refunded payments cannot become verified from intent", () => {
  const payment = (payment_status) => ({ ...paid, payment_status });
  assert.deepEqual(classify({ payment: payment("pending") }), { kind: "requested" });
  for (const status of ["failed", "refunded"]) {
    assert.deepEqual(classify({ payment: payment(status) }), { kind: "uncertain" });
  }
  assert.deepEqual(classify({ payment: payment("pending"), serverEvidence: receipt }), { kind: "uncertain" });
});

test("incomplete, inconsistent or unlinked evidence cannot confirm a redemption", () => {
  for (const serverEvidence of [
    [], "confirmed", {}, { ...receipt, status: "pending" },
    { ...receipt, reservation_id: 40 }, { ...receipt, payment_id: 12 },
    { ...receipt, booking_reference: "LH-00000043" },
    { ...receipt, redemption_type: "wallet" }, { ...receipt, currency: "EUR" },
    { ...receipt, points_redeemed: 0 }, { ...receipt, points_redeemed: 3.5 },
    { ...receipt, points_funded_value_cents: 30619 }, { ...receipt, points_funded_value_cents: "30618" },
    { ...receipt, remaining_cash_due_cents: undefined }, { ...receipt, remaining_cash_due_cents: 1 },
    { transaction_id: 9, points_change: -30618, transaction_type: "redeemed" },
  ]) {
    assert.deepEqual(classify({ serverEvidence }), { kind: "uncertain" }, JSON.stringify(serverEvidence));
  }
  assert.deepEqual(classify({ payment: { ...paid, reservation_id: 40 }, serverEvidence: receipt }), { kind: "uncertain" });
});

test("only linked evidence can classify a rejected attempt and its insufficient-points reason", () => {
  const rejected = { reservation_id: 42, payment_id: 11, redemption_type: "free_stay", status: "rejected",
    reason: "insufficient_points" };
  const pending = { ...paid, payment_status: "pending" };
  assert.deepEqual(classify({ payment: pending, serverEvidence: rejected }),
    { kind: "rejected", reason: "insufficient_points" });
  assert.deepEqual(classify({ payment: pending, serverEvidence: { ...rejected, reason: "not_eligible" } }),
    { kind: "rejected", reason: "not_eligible" });
  assert.deepEqual(classify({ payment: pending, serverEvidence: { ...rejected, payment_id: 12 } }),
    { kind: "uncertain" });
});

test("cancellation has priority over even a matching historical receipt", () => {
  assert.deepEqual(classify({ booking: { ...booking, status: "cancelled" }, serverEvidence: receipt }),
    { kind: "unavailable", cancelled: true });
});
