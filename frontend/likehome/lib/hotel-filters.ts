import type { HotelSearchResult } from "./api-types.ts";

export type HotelFilterValues = {
  maxPrice: string;
  amenities: string[];
};

export type AmenityOption = { value: string; label: string };

function normalizeAmenity(value: string): string {
  return value.trim().toLowerCase();
}

// Blank or invalid input imposes no price constraint; the UI explains invalid input.
export function parseMaxPrice(value: string): number | null {
  const text = value.trim();
  if (!/^(?:\d+(?:\.\d*)?|\.\d+)$/.test(text)) return null;
  const price = Number(text);
  return Number.isFinite(price) && price >= 0 ? price : null;
}

export function getAmenityOptions(hotels: HotelSearchResult[]): AmenityOption[] {
  const options = new Map<string, AmenityOption>();
  for (const hotel of hotels) {
    for (const amenity of hotel.amenities ?? []) {
      const value = normalizeAmenity(amenity);
      if (value && !options.has(value)) {
        options.set(value, { value, label: amenity.trim() });
      }
    }
  }
  return [...options.values()];
}

export function filterHotels(hotels: HotelSearchResult[], filters: HotelFilterValues): HotelSearchResult[] {
  const maxPrice = parseMaxPrice(filters.maxPrice);
  const selectedAmenities = [...new Set(filters.amenities.map(normalizeAmenity).filter(Boolean))];

  return hotels.filter((hotel) => {
    // Missing prices remain visible without a limit, but cannot satisfy an active limit.
    if (maxPrice !== null && (typeof hotel.price_per_night !== "number" ||
      !Number.isFinite(hotel.price_per_night) || hotel.price_per_night < 0 || hotel.price_per_night > maxPrice)) {
      return false;
    }
    const amenities = new Set((hotel.amenities ?? []).map(normalizeAmenity));
    // A stay must contain ALL selected amenities. Keep original objects and order.
    return selectedAmenities.every((amenity) => amenities.has(amenity));
  });
}
