import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import {
  clearRecentSearches,
  getRecentSearchSnapshot,
  parseRecentSearches,
  rememberRecentSearch,
  subscribeRecentSearches,
} from "../lib/recent-searches.ts";
import { ApiError } from "../lib/api.ts";
import { hotelSearchParams, searchHotels } from "../lib/search.ts";
import { parseCheckoutSelection, safeCheckoutReturnTo } from "../lib/checkout-selection.ts";

const originalFetch = globalThis.fetch;
const originalWindow = globalThis.window;

afterEach(() => {
  globalThis.fetch = originalFetch;
  globalThis.window = originalWindow;
});

const futureSearch = {
  destination: "San Jose hotels",
  checkIn: "2026-11-01",
  checkOut: "2026-11-03",
  guests: "2",
};

function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
    snapshot: () => Object.fromEntries(values),
  };
}

function installWindow(localStorage) {
  const listeners = new Map();
  globalThis.window = {
    localStorage,
    addEventListener: (name, listener) => listeners.set(name, listener),
    removeEventListener: (name) => listeners.delete(name),
    dispatchEvent: (event) => listeners.get(event.type)?.(event),
    emit: (name, event) => listeners.get(name)?.(event),
  };
  return listeners;
}

test("recent-search parsing ignores malformed entries, deduplicates, and caps history", () => {
  const entries = [
    futureSearch,
    { ...futureSearch, destination: " SAN JOSE HOTELS " },
    { ...futureSearch, guests: "not-a-number" },
    { ...futureSearch, checkOut: "2026-11-01" },
    ...Array.from({ length: 8 }, (_, index) => ({
      destination: `Destination ${index}`,
      checkIn: "2026-12-01",
      checkOut: "2026-12-03",
      guests: "2",
    })),
  ];

  const parsed = parseRecentSearches(JSON.stringify(entries));

  assert.equal(parsed.length, 5);
  assert.deepEqual(parsed[0], futureSearch);
  assert.equal(parsed.filter((item) => item.destination.toLowerCase() === "san jose hotels").length, 1);
  assert.deepEqual(parseRecentSearches("not-json"), []);
  assert.deepEqual(parseRecentSearches(JSON.stringify({ entries })), []);
});

test("recent-search storage failures never break the search workflow", () => {
  const failingStorage = {
    getItem: () => { throw new Error("blocked"); },
    setItem: () => { throw new Error("quota"); },
    removeItem: () => { throw new Error("blocked"); },
  };
  installWindow(failingStorage);

  assert.equal(getRecentSearchSnapshot(), null);
  assert.doesNotThrow(() => rememberRecentSearch(futureSearch));
  assert.doesNotThrow(() => clearRecentSearches());
});

test("recent-search subscription cleans up storage and custom event listeners", () => {
  const storage = memoryStorage();
  const listeners = installWindow(storage);
  let changes = 0;
  const unsubscribe = subscribeRecentSearches(() => { changes += 1; });

  globalThis.window.emit("storage", { key: "unrelated" });
  assert.equal(changes, 0);
  globalThis.window.emit("storage", { key: "likehome_recent_searches_v1" });
  globalThis.window.emit("likehome:recent-searches-changed", {});
  assert.equal(changes, 2);

  unsubscribe();
  assert.equal(listeners.has("storage"), false);
  assert.equal(listeners.has("likehome:recent-searches-changed"), false);
});

test("recent-search persistence stores only validated search parameters", () => {
  const storage = memoryStorage();
  installWindow(storage);
  rememberRecentSearch({ ...futureSearch, destination: "  San Jose hotels  ", guests: " 02 " });

  const stored = JSON.parse(storage.snapshot().likehome_recent_searches_v1);
  assert.deepEqual(stored, [{ ...futureSearch, destination: "San Jose hotels", guests: "2" }]);
  assert.equal(JSON.stringify(stored).includes("property_token"), false);
  assert.equal(JSON.stringify(stored).includes("price"), false);
});

test("hotel search parameters encode user input and preserve fresh pagination controls", () => {
  const params = hotelSearchParams(
    { ...futureSearch, destination: " San Jose & family hotels " },
    { fresh: true, nextPageToken: "token+/=?" },
  );

  assert.equal(params.get("q"), "San Jose & family hotels");
  assert.equal(params.get("check_in_date"), "2026-11-01");
  assert.equal(params.get("adults"), "2");
  assert.equal(params.get("no_cache"), "true");
  assert.equal(params.get("next_page_token"), "token+/=?");
  assert.ok(!params.toString().includes("api_key"));
});

test("search rejects malformed successful responses before rendering", async () => {
  const malformedResponses = [
    {},
    { search_query: "x", check_in_date: "2026-11-01", check_out_date: "2026-11-03", result_count: -1, properties: [] },
    { search_query: "x", check_in_date: "2026-11-01", check_out_date: "2026-11-03", result_count: 1, properties: [{ property_token: "x" }] },
    { search_query: "x", check_in_date: "2026-11-01", check_out_date: "2026-11-03", result_count: 0, properties: [], next_page_token: 4 },
  ];

  for (const malformed of malformedResponses) {
    globalThis.fetch = async () => new Response(JSON.stringify(malformed));
    await assert.rejects(searchHotels(futureSearch), /unexpected response/);
  }
});

test("search exposes status without leaking backend error details", async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: "private provider secret" }), { status: 502 });

  await assert.rejects(searchHotels(futureSearch), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 502);
    assert.ok(!error.message.includes("private"));
    return true;
  });
});

test("checkout selection rejects arrays, non-integer counts, and unsafe return paths", () => {
  const valid = {
    property_token: "property-123",
    q: "San Jose hotels",
    check_in_date: "2026-11-01",
    check_out_date: "2026-11-03",
    adults: "2",
    children: "0",
    currency: "USD",
    gl: "us",
    hl: "en",
  };

  assert.equal(parseCheckoutSelection({ ...valid, adults: ["2"] }), null);
  assert.equal(parseCheckoutSelection({ ...valid, adults: "2.5" }), null);
  assert.equal(parseCheckoutSelection({ ...valid, adults: "1e1" }), null);
  assert.equal(parseCheckoutSelection({ ...valid, displayed_price_per_night: "Infinity" }).displayed_price_per_night, undefined);
  assert.equal(safeCheckoutReturnTo("/checkout?property_token=x"), "/checkout?property_token=x");
  assert.equal(safeCheckoutReturnTo("/checkout\\evil"), null);
  assert.equal(safeCheckoutReturnTo("https://evil.example/checkout"), null);
});
