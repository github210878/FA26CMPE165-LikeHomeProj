import { getJson } from "./api.ts";
import type { HotelSearchResponse, HotelSearchResult } from "./api-types.ts";

export type SearchValues = {
  destination: string;
  checkIn: string;
  checkOut: string;
  guests: string;
};

export type SearchOptions = {
  fresh?: boolean;
  nextPageToken?: string | null;
};

export function hotelSearchParams(values: SearchValues, options: SearchOptions | string | null = {}): URLSearchParams {
  // Preserve existing callers that pass a pagination token as the second argument.
  const resolvedOptions: SearchOptions = typeof options === "string" ? { nextPageToken: options } : options ?? {};
  const params = new URLSearchParams({
    q: values.destination.trim(),
    check_in_date: values.checkIn,
    check_out_date: values.checkOut,
    adults: String(Number(values.guests)),
  });
  if (resolvedOptions.nextPageToken) params.set("next_page_token", resolvedOptions.nextPageToken);
  if (resolvedOptions.fresh) params.set("no_cache", "true");
  return params;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isNullableNumber(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isFinite(value));
}

function isHotelSearchResult(value: unknown): value is HotelSearchResult {
  return isRecord(value) &&
    isNullableString(value.name) &&
    isNullableString(value.property_token) &&
    isNullableNumber(value.price_per_night) &&
    isNullableNumber(value.rating) &&
    (value.amenities === null ||
      (Array.isArray(value.amenities) && value.amenities.every((item) => typeof item === "string")));
}

function parseHotelSearchResponse(value: unknown): HotelSearchResponse {
  if (!isRecord(value) ||
    typeof value.search_query !== "string" ||
    typeof value.check_in_date !== "string" ||
    typeof value.check_out_date !== "string" ||
    typeof value.result_count !== "number" ||
    !Number.isInteger(value.result_count) ||
    value.result_count < 0 ||
    !Array.isArray(value.properties) ||
    !value.properties.every(isHotelSearchResult) ||
    (value.next_page_token !== undefined && value.next_page_token !== null && typeof value.next_page_token !== "string")) {
    throw new Error("Hotel search returned an unexpected response");
  }

  return value as HotelSearchResponse;
}

export async function searchHotels(values: SearchValues, options: SearchOptions | string | null = {}): Promise<HotelSearchResponse> {
  const response = await getJson<unknown>(`/hotels/search?${hotelSearchParams(values, options)}`, {
    cache: "no-store",
  });
  return parseHotelSearchResponse(response);
}
