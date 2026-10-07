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
import { searchHotels } from "../lib/search.ts";

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
    "@/lib/api": { ApiError },
    "@/lib/search": { searchHotels },
    "@/lib/checkout-selection": { checkoutHref },
    "@/lib/hotel-filters": { filterHotels, getAmenityOptions },
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
        else visit(node.props?.children);
      }
      visit(tree);
      return {
        nodes,
        html: renderToStaticMarkup(tree),
        cards: nodes.filter((node) => node.type === HotelResultCard),
        form: nodes.find((node) => node.type === SearchForm),
        price: nodes.find((node) => node.props?.id === "hotel-max-price"),
        checkbox: (value) => nodes.find((node) => node.type === "input" && node.props.value === value),
        clearButton: nodes.find((node) => node.type === "button" && node.props.children === "Clear filters"),
      };
    },
  };
}

const search = { destination: " San Jose hotels ", checkIn: "2026-11-01", checkOut: "2026-11-03", guests: "3" };

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

  properties = [hotel("No amenities", null, null, null)];
  await view.form.props.onSearch(search);
  view = harness.render();
  assert.match(view.html, /No amenities listed in these results/);
  assert.equal(view.nodes.filter((node) => node.type === "input" && node.props.type === "checkbox").length, 0);
  assert.equal(view.cards[0].props.checkoutHref, null);
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
