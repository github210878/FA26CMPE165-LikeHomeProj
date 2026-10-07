import assert from "node:assert/strict";
import test from "node:test";

import { filterHotels } from "../lib/hotel-filters.ts";
import { sortHotels } from "../lib/hotel-sort.ts";

const hotels = [
  { name: "First", price_per_night: 150.5, rating: 4, amenities: ["Pool"] },
  { name: "No price", price_per_night: null, rating: 5, amenities: ["Pool"] },
  { name: "Budget", price_per_night: 0, rating: null, amenities: null },
  { name: "Price tie", price_per_night: 150.5, rating: 4.5, amenities: ["Gym"] },
  { name: "Luxury", price_per_night: 300, rating: 4.5, amenities: ["pool", "Gym"] },
  { name: "No values", price_per_night: null, rating: null, amenities: null },
].map((hotel) => Object.freeze({ ...hotel, property_token: hotel.name }));
Object.freeze(hotels);
const names = (results) => results.map((hotel) => hotel.name);

test("recommended preserves original API order and returns a separate array", () => {
  const result = sortHotels(hotels, "recommended");
  assert.deepEqual(result, hotels);
  assert.notEqual(result, hotels);
  assert.equal(result[0], hotels[0]);
});

test("ascending price compares decimals and zero, preserves price ties, and places nulls last", () => {
  assert.deepEqual(names(sortHotels(hotels, "price-asc")), ["Budget", "First", "Price tie", "Luxury", "No price", "No values"]);
});

test("descending price also places nulls last and preserves equal-price order", () => {
  assert.deepEqual(names(sortHotels(hotels, "price-desc")), ["Luxury", "First", "Price tie", "Budget", "No price", "No values"]);
});

test("rating sorts descending, preserving rated ties and null-rating order", () => {
  assert.deepEqual(names(sortHotels(hotels, "rating-desc")), ["No price", "Price tie", "Luxury", "First", "Budget", "No values"]);
});

test("undefined and nonfinite prices or ratings sort after known values in either direction", () => {
  for (const [field, sorts] of [["price_per_night", ["price-asc", "price-desc"]], ["rating", ["rating-desc"]]]) {
    const missing = [null, undefined, NaN, Infinity, -Infinity].map((value, index) => ({ ...hotels[0], name: `Missing ${index}`, [field]: value }));
    const known = { ...hotels[0], name: "Known", [field]: 0 };
    const input = [...missing.slice(0, 2), known, ...missing.slice(2)];
    for (const sort of sorts) {
      assert.deepEqual(sortHotels(input, sort), [known, ...missing]);
    }
  }
});

test("all sort modes preserve source order, hotel identities, and result count", () => {
  const originalNames = names(hotels);
  for (const sort of ["recommended", "price-asc", "price-desc", "rating-desc"]) {
    const result = sortHotels(hotels, sort);
    assert.equal(result.length, hotels.length);
    assert.notEqual(result, hotels);
    assert.ok(result.every((hotel) => hotels.includes(hotel)));
    assert.deepEqual(names(hotels), originalNames);
    assert.deepEqual(sortHotels([], sort), []);
    assert.deepEqual(sortHotels([hotels[0]], sort), [hotels[0]]);
  }
});

test("sorting follows combined filters and default retains the filtered API order", () => {
  const filters = { maxPrice: "150.5", amenities: ["pool"] };
  assert.deepEqual(names(sortHotels(filterHotels(hotels, filters), "price-asc")), ["First"]);
  assert.deepEqual(names(sortHotels(filterHotels(hotels, { maxPrice: "", amenities: ["pool"] }), "price-desc")), ["Luxury", "First", "No price"]);
  assert.deepEqual(names(sortHotels(filterHotels(hotels, { maxPrice: "", amenities: ["pool"] }), "recommended")), ["First", "No price", "Luxury"]);
  assert.deepEqual(sortHotels(filterHotels(hotels, { maxPrice: "1", amenities: ["pool"] }), "rating-desc"), []);
});
