import type { BookingResponse } from "./api-types.ts";

export function bookingConfirmationHref(
  booking: Pick<BookingResponse, "reservation_id">, redemptionRequested = false,
): string {
  // The query records user intent only. Confirmation still requires server evidence.
  return `/booking-confirmation/${booking.reservation_id}${redemptionRequested ? "?redeem=1" : ""}`;
}

export function parseReservationId(value: string): number | null {
  if (!/^[1-9]\d*$/.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) ? id : null;
}
