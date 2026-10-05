import type { HotelRevalidationRequest, HotelSearchResult } from "./api-types.ts";
import type { SearchValues } from "./search.ts";

export type CheckoutSelection = HotelRevalidationRequest;
type QueryValue = string | string[] | undefined;

function single(value: QueryValue): string | null {
  return typeof value === "string" ? value : null;
}

function calendarDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

export function checkoutHref(values: SearchValues, hotel: HotelSearchResult): string | null {
  const propertyToken = hotel.property_token?.trim();
  if (!propertyToken || propertyToken.startsWith("legacy:") || propertyToken.startsWith("partner:")) return null;
  const params = new URLSearchParams({
    property_token: propertyToken,
    q: values.destination.trim(),
    check_in_date: values.checkIn,
    check_out_date: values.checkOut,
    adults: String(Number(values.guests)),
    children: "0",
    currency: "USD",
    gl: "us",
    hl: "en",
  });
  if (hotel.price_per_night !== null && Number.isFinite(hotel.price_per_night) && hotel.price_per_night > 0) {
    params.set("displayed_price_per_night", String(hotel.price_per_night));
  }
  return `/checkout?${params.toString()}`;
}

export function parseCheckoutSelection(query: Record<string, QueryValue>): CheckoutSelection | null {
  const propertyToken = single(query.property_token)?.trim();
  const q = single(query.q)?.trim();
  const checkIn = single(query.check_in_date);
  const checkOut = single(query.check_out_date);
  const adultsText = single(query.adults);
  const childrenText = single(query.children);
  const currency = single(query.currency);
  const gl = single(query.gl);
  const hl = single(query.hl);
  if (!propertyToken || propertyToken.length > 255 || propertyToken.startsWith("legacy:") || propertyToken.startsWith("partner:") ||
    !q || q.length > 255 || !checkIn || !checkOut || !calendarDate(checkIn) || !calendarDate(checkOut) || checkOut <= checkIn ||
    !adultsText || !childrenText || !/^\d+$/.test(adultsText) || !/^\d+$/.test(childrenText) ||
    currency !== "USD" || gl !== "us" || hl !== "en") return null;
  const adults = Number(adultsText);
  const children = Number(childrenText);
  if (!Number.isInteger(adults) || adults < 1 || adults > 20 || !Number.isInteger(children) || children < 0 || children > 20) return null;
  const selection: CheckoutSelection = {
    property_token: propertyToken, q, check_in_date: checkIn, check_out_date: checkOut,
    adults, children, currency, gl, hl,
  };
  const displayed = single(query.displayed_price_per_night);
  if (displayed && /^\d+(?:\.\d+)?$/.test(displayed)) {
    const amount = Number(displayed);
    if (Number.isFinite(amount) && amount > 0 && amount <= 99999999.99) selection.displayed_price_per_night = amount;
  }
  return selection;
}

export function safeCheckoutReturnTo(value: QueryValue): string | null {
  const path = single(value);
  return path && /^\/checkout(?:\?|$)/.test(path) && !path.includes("\\") ? path : null;
}
