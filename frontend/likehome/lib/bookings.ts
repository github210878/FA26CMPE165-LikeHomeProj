import { ApiError, getAuthorizedJson, postAuthorizedJson } from "./api.ts";
import type { BookingDetailResponse, BookingListItem, BookingListResponse, CancellationResponse } from "./api-types.ts";
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

export async function getBookingDetails(reservationId: number): Promise<BookingDetailResponse> {
  if (!Number.isInteger(reservationId) || reservationId <= 0) {
    throw new Error("Invalid reservation ID");
  }
  const token = getAccessToken();
  if (!token) throw new ApiError(401);

  const response = await getAuthorizedJson<unknown>(
    `/bookings/get-booking-details/${reservationId}`,
    token,
  );
  if (response === null) return null;
  if (!isBookingListItem(response)) {
    throw new Error("Booking details returned an unexpected response");
  }
  return response;
}

function isCancellationResponse(value: unknown): value is CancellationResponse {
  return isRecord(value) &&
    Number.isInteger(value.reservation_id) && (value.reservation_id as number) > 0 &&
    value.status === "cancelled" &&
    Number.isInteger(value.booking_payment_id) && (value.booking_payment_id as number) > 0 &&
    value.booking_payment_status === "refunded" &&
    Number.isInteger(value.cancellation_payment_id) && (value.cancellation_payment_id as number) > 0 &&
    typeof value.cancellation_amount === "number" && Number.isFinite(value.cancellation_amount) && value.cancellation_amount >= 0 &&
    value.cancellation_payment_status === "pending";
}

export async function cancelBooking(reservationId: number): Promise<CancellationResponse> {
  if (!Number.isInteger(reservationId) || reservationId <= 0) {
    throw new Error("Invalid reservation ID");
  }
  const token = getAccessToken();
  if (!token) throw new ApiError(401);

  const response = await postAuthorizedJson<unknown>(
    `/bookings/cancel-booking/${reservationId}`,
    token,
  );
  if (!isCancellationResponse(response) || response.reservation_id !== reservationId) {
    throw new Error("Cancellation returned an unexpected response");
  }
  return response;
}

export async function cancelBookingAndRefresh(
  reservationId: number,
  onCancelled: (response: CancellationResponse) => void,
): Promise<{ kind: "refreshed"; bookings: BookingListResponse } | { kind: "refresh-error"; error: unknown }> {
  const cancellation = await cancelBooking(reservationId);
  onCancelled(cancellation);
  try {
    return { kind: "refreshed", bookings: await getMyBookings() };
  } catch (error: unknown) {
    return { kind: "refresh-error", error };
  }
}
