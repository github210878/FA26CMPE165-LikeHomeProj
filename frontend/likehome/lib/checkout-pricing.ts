import type { HotelRevalidationResponse } from "./api-types.ts";

type QuoteTotals = Pick<HotelRevalidationResponse,
  "provider_base_total" | "likehome_reservation_total" | "likehome_payment_amount">;

export function checkoutPriceBreakdown(quote: QuoteTotals) {
  // Presentation only: subtract the server-rounded totals in integer cents.
  // These values never determine the booking price or its acknowledgement.
  const baseCents = Math.round(quote.provider_base_total * 100);
  const reservationCents = Math.round(quote.likehome_reservation_total * 100);
  const paymentCents = Math.round(quote.likehome_payment_amount * 100);

  return {
    baseStayTotal: quote.provider_base_total,
    serviceFee: (reservationCents - baseCents) / 100,
    tax: (paymentCents - reservationCents) / 100,
    finalTotal: quote.likehome_payment_amount,
  };
}
