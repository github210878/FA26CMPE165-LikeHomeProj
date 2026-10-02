import { ApiError, getAuthorizedJson } from "./api.ts";
import type { BookingListItem, BookingListResponse } from "./api-types.ts";
import { getAccessToken } from "./token-storage.ts";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isBookingListItem(value: unknown): value is BookingListItem {
  return isRecord(value) &&
    Number.isInteger(value.reservation_id) && (value.reservation_id as number) > 0 &&
    typeof value.hotel_name === "string" &&
    typeof value.room_type_name === "string" &&
    typeof value.hotel_address === "string" &&
    isNullableString(value.hotel_phone) &&
    isNullableString(value.hotel_description) &&
    isNullableString(value.room_description) &&
    typeof value.check_in_date === "string" && /^\d{4}-\d{2}-\d{2}(?:T.*)?$/.test(value.check_in_date) &&
    typeof value.check_out_date === "string" && /^\d{4}-\d{2}-\d{2}(?:T.*)?$/.test(value.check_out_date) &&
    typeof value.price_per_night === "number" && Number.isFinite(value.price_per_night) &&
    typeof value.total_price === "number" && Number.isFinite(value.total_price) &&
    (value.status === "confirmed" || value.status === "cancelled" || value.status === "completed");
}

export async function getMyBookings(): Promise<BookingListResponse> {
  const token = getAccessToken();
  if (!token) throw new ApiError(401);

  const response = await getAuthorizedJson<unknown>("/bookings/get-all-bookings", token);
  if (!Array.isArray(response) || !response.every(isBookingListItem)) {
    throw new Error("Bookings returned an unexpected response");
  }
  return response;
}
