import { ApiError, postJson } from "./api.ts";
import type {
  BookingRequest, BookingResponse, HotelRevalidationRequest, HotelRevalidationResponse,
} from "./api-types.ts";
import { createBooking } from "./bookings.ts";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function money(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

function validQuote(value: unknown, selection: HotelRevalidationRequest): value is HotelRevalidationResponse {
  return isRecord(value) &&
    value.property_token === selection.property_token &&
    typeof value.hotel_name === "string" && value.hotel_name.trim().length > 0 &&
    value.check_in_date === selection.check_in_date && value.check_out_date === selection.check_out_date &&
    value.adults === selection.adults && value.children === selection.children && value.currency === "USD" &&
    Number.isInteger(value.number_of_nights) && (value.number_of_nights as number) > 0 &&
    value.availability === "available" && value.rate_rule === "lowest_eligible_provider_base_total" &&
    typeof value.source === "string" && value.source.trim().length > 0 &&
    Number.isInteger(value.guest_capacity) && (value.guest_capacity as number) >= selection.adults + selection.children &&
    money(value.current_price_per_night) && money(value.provider_base_total) &&
    (value.provider_total_with_taxes_fees === null || money(value.provider_total_with_taxes_fees)) &&
    money(value.likehome_reservation_total) && money(value.likehome_payment_amount) &&
    (value.price_changed === null || typeof value.price_changed === "boolean");
}

export async function revalidateHotel(selection: HotelRevalidationRequest): Promise<HotelRevalidationResponse> {
  const result = await postJson<unknown, HotelRevalidationRequest>("/hotels/revalidate", selection);
  if (!validQuote(result, selection)) throw new Error("Hotel quote returned an unexpected response");
  return result;
}

export function bookingRequestFromQuote(
  selection: HotelRevalidationRequest,
  quote: HotelRevalidationResponse,
): BookingRequest {
  return {
    hotel_token: selection.property_token,
    q: selection.q,
    check_in_date: selection.check_in_date,
    check_out_date: selection.check_out_date,
    adults: selection.adults,
    children: selection.children,
    currency: selection.currency,
    gl: selection.gl,
    hl: selection.hl,
    price_per_night: quote.current_price_per_night,
    accepted_payment_amount: quote.likehome_payment_amount,
  };
}

export async function submitAcceptedQuote(
  selection: HotelRevalidationRequest,
  quote: HotelRevalidationResponse,
  onConflict: () => void,
): Promise<{ kind: "created"; booking: BookingResponse } | { kind: "changed"; quote: HotelRevalidationResponse }> {
  try {
    return { kind: "created", booking: await createBooking(bookingRequestFromQuote(selection, quote)) };
  } catch (error: unknown) {
    if (!(error instanceof ApiError) || error.status !== 409) throw error;
    onConflict();
    return { kind: "changed", quote: await revalidateHotel(selection) };
  }
}

export function createBookingSubmissionGuard() {
  let pending = false;
  return {
    tryStart(): boolean {
      if (pending) return false;
      pending = true;
      return true;
    },
    finish(): void { pending = false; },
  };
}
