import type { BookingDetailItem, PaymentResponse } from "./api-types.ts";

export type RedemptionConfirmation =
  | { kind: "loading" | "requested" | "unverified" | "uncertain" | "authentication-required" }
  | { kind: "unavailable"; cancelled?: boolean }
  | { kind: "rejected"; reason: "insufficient_points" | "not_eligible" }
  | {
    kind: "confirmed";
    bookingReference: string;
    hotelName: string;
    checkInDate: string;
    checkOutDate: string;
    pointsRedeemed: number;
    pointsFundedValueCents: number;
    remainingCashDueCents: number;
  };

type ConfirmationInput = {
  requested: boolean;
  booking: BookingDetailItem;
  payment: PaymentResponse;
  // Reserved for an authenticated, booking- and payment-scoped server read.
  // Current booking and payment responses do not provide this evidence.
  serverEvidence?: unknown;
};

function positiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

export function classifyRedemptionConfirmation({
  requested, booking, payment, serverEvidence,
}: ConfirmationInput): RedemptionConfirmation | null {
  if (booking.status === "cancelled") return requested ? { kind: "unavailable", cancelled: true } : null;
  if (payment.reservation_id !== booking.reservation_id || payment.payment_type !== "booking") {
    return requested ? { kind: "uncertain" } : null;
  }

  if (serverEvidence !== null && typeof serverEvidence === "object" && !Array.isArray(serverEvidence)) {
    const evidence = serverEvidence as Record<string, unknown>;
    if (evidence.reservation_id === booking.reservation_id
      && evidence.payment_id === payment.payment_id
      && evidence.redemption_type === "free_stay") {
      if (evidence.status === "rejected"
        && (evidence.reason === "insufficient_points" || evidence.reason === "not_eligible")) {
        return { kind: "rejected", reason: evidence.reason };
      }
      if (payment.payment_status === "paid" && evidence.status === "confirmed" && evidence.currency === "USD"
        && evidence.booking_reference === `LH-${String(booking.reservation_id).padStart(8, "0")}`
        && positiveInteger(evidence.points_redeemed) && positiveInteger(evidence.points_funded_value_cents)
        && evidence.points_funded_value_cents / 100 === payment.amount && evidence.remaining_cash_due_cents === 0) {
        return {
          kind: "confirmed",
          bookingReference: evidence.booking_reference,
          hotelName: booking.hotel_name,
          checkInDate: booking.check_in_date,
          checkOutDate: booking.check_out_date,
          pointsRedeemed: evidence.points_redeemed,
          pointsFundedValueCents: evidence.points_funded_value_cents,
          remainingCashDueCents: evidence.remaining_cash_due_cents,
        };
      }
    }
  }

  if (!requested) return null;
  if (serverEvidence != null || payment.payment_status === "failed" || payment.payment_status === "refunded") {
    return { kind: "uncertain" };
  }
  return { kind: payment.payment_status === "paid" ? "unverified" : "requested" };
}
