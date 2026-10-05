import type { BookingResponse } from "./api-types.ts";

export function bookingConfirmationHref(booking: BookingResponse): string {
  return `/booking-confirmation/${booking.reservation_id}`;
}

export function parseReservationId(value: string): number | null {
  if (!/^[1-9]\d*$/.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) ? id : null;
}
