import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { afterEach, test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

import { ApiError } from "../lib/api.ts";
import { checkoutHref, parseCheckoutSelection } from "../lib/checkout-selection.ts";
import { filterHotels, getAmenityOptions, parseMaxPrice } from "../lib/hotel-filters.ts";
import { getHotelThumbnailUrl } from "../lib/hotel-thumbnail.ts";
import { HOTEL_SORT_OPTIONS, sortHotels } from "../lib/hotel-sort.ts";
import { searchHotels } from "../lib/search.ts";
import { searchError } from "../lib/search-error.ts";

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });

function hotel(name, price, amenities, token = name) {
  return { name, property_token: token, price_per_night: price, amenities, rating: null };
}

const hotels = [
  hotel("Budget", 0, null),
  hotel("Pool stay", 100, [" Pool ", "POOL", " Wi-Fi ", ""]),
  hotel("Gym stay", 150.5, ["Gym", "wi-fi", "pool"]),
  hotel("Luxury", 300, ["Parking", "Gym"]),
  hotel("Unknown price", null, ["Pool"]),
];
const names = (results) => results.map((result) => result.name);
const clear = { maxPrice: "", amenities: [] };

test("maximum price parses nonnegative decimal amounts, including zero", () => {
  for (const [value, expected] of [["0", 0], ["150", 150], [" 150.50 ", 150.5], [".5", 0.5], ["150.", 150]]) {
    assert.equal(parseMaxPrice(value), expected);
  }
  for (const value of ["", " ", "-1", "NaN", "Infinity", "1e2", "0x10", "1,000", "abc", "1.2.3", "9".repeat(400)]) {
    assert.equal(parseMaxPrice(value), null);
  }
});

test("maximum price is inclusive and missing prices do not satisfy an active limit", () => {
  assert.deepEqual(names(filterHotels(hotels, { ...clear, maxPrice: "150.50" })), ["Budget", "Pool stay", "Gym stay"]);
  assert.deepEqual(names(filterHotels(hotels, { ...clear, maxPrice: "150.49" })), ["Budget", "Pool stay"]);
  assert.deepEqual(names(filterHotels(hotels, { ...clear, maxPrice: "0" })), ["Budget"]);
  assert.deepEqual(filterHotels(hotels, clear), hotels);
});

test("missing and non-comparable prices are safe and never treated as zero", () => {
  const missing = [null, undefined, NaN, Infinity, -1].map((price) => hotel("Missing", price, null));
  assert.deepEqual(filterHotels(missing, clear), missing);
  assert.deepEqual(filterHotels(missing, { ...clear, maxPrice: "100" }), []);
  assert.deepEqual(filterHotels(hotels, { ...clear, maxPrice: "-1" }), hotels);
});

test("amenity options come from loaded results, deduplicate normalized values, and preserve first label", () => {
  assert.deepEqual(getAmenityOptions(hotels), [
    { value: "pool", label: "Pool" },
    { value: "wi-fi", label: "Wi-Fi" },
    { value: "gym", label: "Gym" },
    { value: "parking", label: "Parking" },
  ]);
  assert.deepEqual(getAmenityOptions([hotel("Empty", 100, null), hotel("Missing", 100, undefined)]), []);
  assert.deepEqual(getAmenityOptions([]), []);
});

test("one amenity matches case and whitespace; duplicates do not change matches", () => {
  assert.deepEqual(names(filterHotels(hotels, { ...clear, amenities: [" POOL ", "pool"] })), ["Pool stay", "Gym stay", "Unknown price"]);
});

test("multiple amenities require ALL selected values and missing amenities cannot satisfy them", () => {
  assert.deepEqual(names(filterHotels(hotels, { ...clear, amenities: ["Pool", " WI-FI "] })), ["Pool stay", "Gym stay"]);
  assert.deepEqual(names(filterHotels(hotels, { ...clear, amenities: ["Pool", "Gym"] })), ["Gym stay"]);
  assert.deepEqual(filterHotels([hotel("Missing", 100, undefined)], { ...clear, amenities: ["Pool"] }), []);
});

test("combined filters narrow results, clear restores them, and original objects and order are retained", () => {
  const original = structuredClone(hotels);
  const results = filterHotels(hotels, { maxPrice: "100", amenities: ["pool", "wi-fi"] });
  assert.deepEqual(names(results), ["Pool stay"]);
  assert.equal(results[0], hotels[1]);
  assert.deepEqual(filterHotels(hotels, { maxPrice: "99", amenities: ["pool"] }), []);
  assert.deepEqual(filterHotels(hotels, clear), original);
  assert.deepEqual(hotels, original);
});

// Exercise the actual TSX handlers with the existing Node runner, without a DOM
// dependency. Only React hooks and the two unrelated child components are stubbed.
const require = createRequire(import.meta.url);
function loadComponent(path, imports) {
  const source = readFileSync(new URL(path, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  });
  const loadedModule = { exports: {} };
  const componentRequire = (name) => Object.hasOwn(imports, name) ? imports[name] : require(name);
  new Function("require", "module", "exports", outputText)(componentRequire, loadedModule, loadedModule.exports);
  return loadedModule.exports.default;
}

const HotelFilters = loadComponent("../components/HotelFilters.tsx", {
  "@/lib/hotel-filters": { parseMaxPrice },
});
const RetryButton = loadComponent("../components/RetryButton.tsx", {});
const ErrorState = loadComponent("../components/ErrorState.tsx", {
  "./RetryButton": { default: RetryButton },
});

function searchHarness() {
  const slots = [];
  let cursor = 0;
  const hooks = {
    useState(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = initial;
      return [slots[index], (value) => {
        slots[index] = typeof value === "function" ? value(slots[index]) : value;
      }];
    },
    useRef(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = { current: initial };
      return slots[index];
    },
  };
  const SearchForm = () => null;
  const HotelResultCard = () => null;
  const SearchExperience = loadComponent("../app/search/search-experience.tsx", {
    react: hooks,
    "@/components/HotelResultCard": { default: HotelResultCard },
    "@/components/HotelFilters": { default: HotelFilters },
    "@/components/ErrorState": { default: ErrorState },
    "@/lib/search-error": { searchError },
    "@/lib/api": { ApiError },
    "@/lib/search": { searchHotels },
    "@/lib/checkout-selection": { checkoutHref },
    "@/lib/hotel-filters": { filterHotels, getAmenityOptions },
    "@/lib/hotel-sort": { HOTEL_SORT_OPTIONS, sortHotels },
    "./search-form": { default: SearchForm },
  });

  return {
    SearchForm, HotelResultCard,
    render() {
      cursor = 0;
      const tree = SearchExperience();
      const nodes = [];
      function visit(node) {
        if (Array.isArray(node)) return node.forEach(visit);
        if (!node || typeof node !== "object") return;
        nodes.push(node);
        if (node.type === HotelFilters) visit(HotelFilters(node.props));
        else if (node.type === ErrorState) visit(ErrorState(node.props));
        else if (node.type === RetryButton) visit(RetryButton(node.props));
        else visit(node.props?.children);
      }
      visit(tree);
      return {
        nodes,
        html: renderToStaticMarkup(tree),
        cards: nodes.filter((node) => node.type === HotelResultCard),
        form: nodes.find((node) => node.type === SearchForm),
        retry: nodes.find((node) => node.type === RetryButton),
        price: nodes.find((node) => node.props?.id === "hotel-max-price"),
        sort: nodes.find((node) => node.props?.id === "hotel-sort"),
        checkbox: (value) => nodes.find((node) => node.type === "input" && node.props.value === value),
        clearButton: nodes.find((node) => node.type === "button" && node.props.children === "Clear filters"),
      };
    },
  };
}

const search = { destination: " San Jose hotels ", checkIn: "2026-11-01", checkOut: "2026-11-03", guests: "3" };

test("retry repeats the failed search once, stays disabled while pending, and clears on success", async () => {
  const calls = [];
  let resolveRetry;
  globalThis.fetch = async (url) => {
    calls.push(url);
    if (calls.length === 1) return new Response(null, { status: 504 });
    return new Promise((resolve) => { resolveRetry = resolve; });
  };
  const harness = searchHarness();
  await harness.render().form.props.onSearch(search);
  let view = harness.render();
  assert.match(view.html, /The search took too long/);
  assert.match(view.html, /role="alert"/);
  view.retry.props.onRetry();
  view.retry.props.onRetry();
  view = harness.render();
  assert.equal(calls.length, 2);
  assert.equal(calls[0], calls[1]);
  assert.equal(view.retry.props.isRetrying, true);
  assert.match(view.html, /disabled="" aria-busy="true"/);
  assert.match(view.html, /Trying again/);
  resolveRetry(new Response(JSON.stringify({
    search_query: "San Jose hotels", check_in_date: search.checkIn,
    check_out_date: search.checkOut, result_count: 0, properties: [],
  })));
  await new Promise(setImmediate);
  view = harness.render();
  assert.equal(view.retry, undefined);
  assert.match(view.html, /No hotels found/);
  assert.doesNotMatch(view.html, /role="alert"/);
});

test("load more appends the next page and keeps the pagination token out of card data", async () => {
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(url);
    const page = calls.length === 1
      ? { search_query: "San Jose hotels", check_in_date: search.checkIn, check_out_date: search.checkOut, result_count: 1, properties: [hotels[0]], next_page_token: "next-page-token" }
      : { search_query: "San Jose hotels", check_in_date: search.checkIn, check_out_date: search.checkOut, result_count: 1, properties: [hotels[1]], next_page_token: null };
    return new Response(JSON.stringify(page));
  };

  const harness = searchHarness();
  await harness.render().form.props.onSearch(search);
  let view = harness.render();
  let loadMore = view.nodes.find((node) => node.type === "button" && node.props.children === "Load more stays");
  assert.ok(loadMore);
  loadMore.props.onClick();
  await new Promise(setImmediate);

  view = harness.render();
  assert.equal(calls.length, 2);
  assert.match(calls[1], /next_page_token=next-page-token/);
  assert.deepEqual(names(view.cards.map((card) => card.props.hotel)), ["Budget", "Pool stay"]);
  assert.match(view.html, /2 of 2 loaded stays/);
  assert.equal(view.nodes.find((node) => node.type === "button" && node.props.children === "Load more stays"), undefined);
});

test("failed retries remain available and validation errors require a corrected search", async () => {
  let status = 502;
  globalThis.fetch = async () => new Response(null, { status });
  const harness = searchHarness();
  await harness.render().form.props.onSearch(search);
  harness.render().retry.props.onRetry();
  await new Promise(setImmediate);
  assert.equal(harness.render().retry.props.isRetrying, false);
  status = 422;
  await harness.render().form.props.onSearch({ ...search, destination: "New York" });
  const view = harness.render();
  assert.equal(view.retry, undefined);
  assert.match(view.html, /Check your search details/);
});

test("price, amenity, combination, clear, count and empty UI update locally with no extra HTTP requests", async () => {
  const payload = {
    search_query: "San Jose hotels", check_in_date: search.checkIn, check_out_date: search.checkOut,
    result_count: 999, properties: hotels,
  };
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(url);
    return new Response(JSON.stringify(payload));
  };
  const harness = searchHarness();
  assert.match(harness.render().html, /Enter a destination/);
  await harness.render().form.props.onSearch(search);
  let view = harness.render();
  const loaded = view.cards.map((card) => card.props.hotel);
  assert.deepEqual(loaded, hotels);
  assert.match(view.html, /5 of 5 loaded stays/);
  assert.ok(!view.html.includes("999"));
  assert.equal(view.clearButton, undefined);

  view.price.props.onChange({ target: { value: "100" } });
  view = harness.render();
  assert.deepEqual(names(view.cards.map((card) => card.props.hotel)), ["Budget", "Pool stay"]);
  assert.match(view.html, /2 of 5 loaded stays/);
  assert.equal(view.price.props.value, "100");
  view.checkbox("pool").props.onChange({ target: { checked: true } });
  view = harness.render();
  assert.equal(view.cards.length, 1);
  assert.equal(view.cards[0].props.hotel, loaded[1]);
  assert.equal(view.checkbox("pool").props.checked, true);
  // Options continue to come from all loaded hotels, even when none match.
  view.checkbox("parking").props.onChange({ target: { checked: true } });
  view = harness.render();
  assert.equal(view.cards.length, 0);
  assert.match(view.html, /0 of 5 loaded stays/);
  assert.match(view.html, /No stays match your current filters/);
  assert.ok(!view.html.includes("Try a different destination"));
  const emptyClear = view.nodes.filter((node) => node.type === "button" && node.props.children === "Clear filters").at(-1);
  emptyClear.props.onClick();
  view = harness.render();
  assert.deepEqual(view.cards.map((card) => card.props.hotel), loaded);
  assert.equal(view.price.props.value, "");
  assert.equal(view.checkbox("pool").props.checked, false);
  assert.equal(view.checkbox("parking").props.checked, false);

  view.checkbox("gym").props.onChange({ target: { checked: true } });
  view = harness.render();
  assert.deepEqual(names(view.cards.map((card) => card.props.hotel)), ["Gym stay", "Luxury"]);
  view.checkbox("gym").props.onChange({ target: { checked: false } });
  view = harness.render();
  assert.equal(view.cards.length, 5);
  view.price.props.onChange({ target: { value: "-10" } });
  view = harness.render();
  assert.equal(view.price.props["aria-invalid"], true);
  assert.match(view.html, /The price limit is not applied/);
  assert.equal(view.cards.length, 5);
  view.clearButton.props.onClick();
  view = harness.render();
  assert.equal(view.price.props["aria-invalid"], false);
  assert.equal(calls.length, 1);
  assert.match(calls[0], /\/hotels\/search\?/);

  view.checkbox("pool").props.onChange({ target: { checked: true } });
  view = harness.render();
  const selected = parseCheckoutSelection(Object.fromEntries(new URL(view.cards[0].props.checkoutHref, "https://likehome.test").searchParams));
  assert.deepEqual(selected, {
    property_token: "Pool stay", q: "San Jose hotels", check_in_date: search.checkIn, check_out_date: search.checkOut,
    adults: 3, children: 0, currency: "USD", gl: "us", hl: "en", displayed_price_per_night: 100,
  });
  view.price.props.onChange({ target: { value: "0" } });
  view = harness.render();
  assert.equal(view.cards.length, 0);
  await view.form.props.onSearch(search);
  view = harness.render();
  assert.equal(view.cards.length, 5);
  assert.equal(view.price.props.value, "");
  assert.equal(view.checkbox("pool").props.checked, false);
  assert.equal(calls.length, 2); // Only the two explicit search submissions.
});

test("API zero results are distinct from filters and absent amenities create no invented options", async () => {
  let properties = [];
  globalThis.fetch = async () => new Response(JSON.stringify({
    search_query: "San Jose hotels", check_in_date: search.checkIn, check_out_date: search.checkOut,
    result_count: properties.length, properties,
  }));
  const harness = searchHarness();
  await harness.render().form.props.onSearch(search);
  let view = harness.render();
  assert.match(view.html, /No hotels found for this search/);
  assert.ok(!view.html.includes("No stays match your current filters"));
  assert.equal(view.price, undefined);
  assert.equal(view.sort, undefined);

  properties = [hotel("No amenities", null, null, null)];
  await view.form.props.onSearch(search);
  view = harness.render();
  assert.match(view.html, /No amenities listed in these results/);
  assert.equal(view.nodes.filter((node) => node.type === "input" && node.props.type === "checkbox").length, 0);
  assert.equal(view.cards[0].props.checkoutHref, null);
});

test("sort control composes with filters, retains context and counts, clears locally, and resets on a new search", async () => {
  const ratedHotels = hotels.map((hotel, index) => ({
    ...hotel, rating: [null, 4.3, 4.8, 4.8, null][index], thumbnail: "https://images.example.com/hotel.jpg",
  }));
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    return new Response(JSON.stringify({
      search_query: "San Jose hotels", check_in_date: search.checkIn, check_out_date: search.checkOut,
      result_count: ratedHotels.length, properties: ratedHotels,
    }));
  };
  const harness = searchHarness();
  await harness.render().form.props.onSearch(search);
  let view = harness.render();
  const loaded = view.cards.map((card) => card.props.hotel);
  const originalHrefs = new Map(view.cards.map((card) => [card.props.hotel, card.props.checkoutHref]));
  assert.equal(view.sort.props.value, "recommended");
  assert.match(view.html, /<label[^>]*for="hotel-sort"[^>]*>Sort stays<\/label>/);
  assert.equal(view.sort.type, "select");
  assert.match(view.sort.props.className, /min-h-11/);
  assert.deepEqual(view.nodes.filter((node) => node.type === "option").map((node) => node.props.children), [
    "Recommended / Default", "Price: Low to High", "Price: High to Low", "Guest Rating: High to Low",
  ]);

  for (const [sort, expected] of [
    ["price-desc", ["Luxury", "Gym stay", "Pool stay", "Budget", "Unknown price"]],
    ["price-asc", ["Budget", "Pool stay", "Gym stay", "Luxury", "Unknown price"]],
    ["rating-desc", ["Gym stay", "Luxury", "Pool stay", "Budget", "Unknown price"]],
  ]) {
    view.sort.props.onChange({ target: { value: sort } });
    view = harness.render();
    assert.deepEqual(names(view.cards.map((card) => card.props.hotel)), expected);
    assert.match(view.html, /5 of 5 loaded stays/);
    assert.equal(view.sort.props.value, sort);
    assert.ok(!view.html.includes("No stays match"));
    for (const card of view.cards) {
      assert.ok(loaded.includes(card.props.hotel));
      assert.equal(card.props.checkoutHref, originalHrefs.get(card.props.hotel));
      assert.equal(card.props.hotel.thumbnail, "https://images.example.com/hotel.jpg");
    }
  }
  const selection = parseCheckoutSelection(Object.fromEntries(new URL(view.cards[0].props.checkoutHref, "https://likehome.test").searchParams));
  assert.deepEqual(selection, {
    property_token: "Gym stay", q: "San Jose hotels", check_in_date: search.checkIn, check_out_date: search.checkOut,
    adults: 3, children: 0, currency: "USD", gl: "us", hl: "en", displayed_price_per_night: 150.5,
  });

  view.sort.props.onChange({ target: { value: "price-desc" } });
  view = harness.render();
  view.price.props.onChange({ target: { value: "150.5" } });
  view = harness.render();
  assert.deepEqual(names(view.cards.map((card) => card.props.hotel)), ["Gym stay", "Pool stay", "Budget"]);
  view.checkbox("pool").props.onChange({ target: { checked: true } });
  view = harness.render();
  assert.deepEqual(names(view.cards.map((card) => card.props.hotel)), ["Gym stay", "Pool stay"]);
  assert.match(view.html, /2 of 5 loaded stays/);
  view.sort.props.onChange({ target: { value: "recommended" } });
  view = harness.render();
  assert.deepEqual(names(view.cards.map((card) => card.props.hotel)), ["Pool stay", "Gym stay"]);
  assert.equal(view.price.props.value, "150.5");
  assert.equal(view.checkbox("pool").props.checked, true);
  view.sort.props.onChange({ target: { value: "price-desc" } });
  view = harness.render();
  view.clearButton.props.onClick();
  view = harness.render();
  assert.equal(view.sort.props.value, "price-desc");
  assert.equal(view.price.props.value, "");
  assert.equal(view.checkbox("pool").props.checked, false);
  assert.deepEqual(names(view.cards.map((card) => card.props.hotel)), ["Luxury", "Gym stay", "Pool stay", "Budget", "Unknown price"]);

  view.price.props.onChange({ target: { value: "99" } });
  view = harness.render();
  view.checkbox("pool").props.onChange({ target: { checked: true } });
  view = harness.render();
  view.sort.props.onChange({ target: { value: "rating-desc" } });
  view = harness.render();
  assert.equal(view.cards.length, 0);
  assert.match(view.html, /No stays match your current filters/);
  assert.match(view.html, /0 of 5 loaded stays/);
  view.nodes.filter((node) => node.type === "button" && node.props.children === "Clear filters").at(-1).props.onClick();
  view = harness.render();
  assert.equal(view.sort.props.value, "rating-desc");
  assert.equal(view.cards.length, 5);
  assert.equal(calls, 1);

  await view.form.props.onSearch({ ...search, destination: "Los Angeles hotels" });
  view = harness.render();
  assert.equal(view.sort.props.value, "recommended");
  assert.deepEqual(view.cards.map((card) => card.props.hotel), ratedHotels);
  assert.equal(view.price.props.value, "");
  assert.equal(view.checkbox("pool").props.checked, false);
  assert.equal(calls, 2); // Only the explicit search submissions make requests.
});

test("filtered card keeps lazy thumbnail and Select stay href, including a price-unavailable fallback", () => {
  const HotelResultCard = loadComponent("../components/HotelResultCard.tsx", {
    react: { useState: () => [null, () => {}] },
    "next/link": { default: ({ children, href, className }) => require("react").createElement("a", { href, className }, children) },
    "@/lib/hotel-thumbnail": { getHotelThumbnailUrl },
  });
  const result = { ...hotels[1], thumbnail: "https://images.example.com/hotel.jpg" };
  const href = checkoutHref(search, result);
  const html = renderToStaticMarkup(HotelResultCard({ hotel: result, checkoutHref: href }));
  assert.match(html, /loading="lazy"/);
  assert.match(html, /decoding="async"/);
  assert.match(html, /src="https:\/\/images.example.com\/hotel.jpg"/);
  assert.ok(html.includes(`href="${href.replaceAll("&", "&amp;")}"`));
  assert.match(html, /Select stay/);
  assert.match(html, /From \$100/);
  const missingHtml = renderToStaticMarkup(HotelResultCard({ hotel: hotels[4], checkoutHref: checkoutHref(search, hotels[4]) }));
  assert.match(missingHtml, /Price unavailable/);
  assert.match(missingHtml, /No image available/);
  assert.match(missingHtml, /Select stay/);
});
