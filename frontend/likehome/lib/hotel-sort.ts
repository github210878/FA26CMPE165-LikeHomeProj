import type { HotelSearchResult } from "./api-types.ts";

export const HOTEL_SORT_OPTIONS = [
  { value: "recommended", label: "Recommended / Default" },
  { value: "price-asc", label: "Price: Low to High" },
  { value: "price-desc", label: "Price: High to Low" },
  { value: "rating-desc", label: "Guest Rating: High to Low" },
] as const;

export type HotelSort = (typeof HOTEL_SORT_OPTIONS)[number]["value"];

function comparableNumber(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function sortHotels(hotels: readonly HotelSearchResult[], sort: HotelSort): HotelSearchResult[] {
  const sorted = [...hotels];
  if (sort === "recommended") return sorted;

  const field = sort === "rating-desc" ? "rating" : "price_per_night";
  return sorted.sort((left, right) => {
    const leftValue = comparableNumber(left[field]);
    const rightValue = comparableNumber(right[field]);
    // Unknown values come last in BOTH directions and never remove a stay.
    if (leftValue === null) return rightValue === null ? 0 : 1;
    if (rightValue === null) return -1;
    // Stable Array.sort retains API order for equal values and unknown values.
    return sort === "price-asc" ? leftValue - rightValue : rightValue - leftValue;
  });
}
