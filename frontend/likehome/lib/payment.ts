import type { PaymentResponse } from "./api-types.ts";

export function paymentHref(paymentId: number): string {
  if (!Number.isSafeInteger(paymentId) || paymentId <= 0) throw new Error("Invalid payment ID");
  return `/payment/${paymentId}`;
}

export function bookingPaymentForReservation(payments: PaymentResponse[], reservationId: number): PaymentResponse | null {
  const matches = payments.filter((payment) => payment.reservation_id === reservationId && payment.payment_type === "booking");
  return matches.length === 1 ? matches[0] : null;
}
