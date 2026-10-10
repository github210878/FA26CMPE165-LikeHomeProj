import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

import { filterHotels, getAmenityOptions } from "../lib/hotel-filters.ts";
import { sortHotels } from "../lib/hotel-sort.ts";
import { getHotelThumbnailUrl } from "../lib/hotel-thumbnail.ts";

// Use the existing Node/TSX test pattern; exercise the real card and its handler.
const require = createRequire(import.meta.url);
const { outputText } = ts.transpileModule(
  readFileSync(new URL("../components/HotelResultCard.tsx", import.meta.url), "utf8"),
  { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } },
);

function cardHarness() {
  let failedThumbnail = null;
  const imports = {
    react: { useState: () => [failedThumbnail, (value) => { failedThumbnail = value; }] },
    "next/link": { default: ({ href, children, className }) => createElement("a", { href, className }, children) },
    "@/lib/hotel-thumbnail": { getHotelThumbnailUrl },
  };
  const loaded = { exports: {} };
  new Function("require", "module", "exports", outputText)(
    (name) => Object.hasOwn(imports, name) ? imports[name] : require(name),
    loaded, loaded.exports,
  );
  return (hotel, checkoutHref = null) => {
    const tree = loaded.exports.default({ hotel, checkoutHref });
    const nodes = [];
    function visit(node) {
      if (Array.isArray(node)) return node.forEach(visit);
      if (!node || typeof node !== "object") return;
      nodes.push(node);
      visit(node.props?.children);
    }
    visit(tree);
    return { html: renderToStaticMarkup(tree), nodes, image: nodes.find((node) => node.type === "img") };
  };
}

const hotel = {
  name: "Provider Hotel",
  property_token: "synthetic-property",
  price_per_night: 125.5,
  rating: 4.4,
  amenities: ["Wi-Fi", "Pool"],
  thumbnail: "https://images.example.test/hotel.jpg",
};

test("card renders normalized name, USD nightly price, guest rating and amenities", () => {
  const { html } = cardHarness()(hotel);
  assert.match(html, /Provider Hotel<\/h3>/);
  assert.match(html, /From \$125\.50 \/ night/);
  assert.match(html, /Rating: 4\.4 \/ 5/);
  assert.match(html, /Wi-Fi · Pool/);
  assert.doesNotMatch(html, /reviews|tax|fees|total/i);
});

test("card uses only the canonical nightly price, regardless of raw or total rate fields", () => {
  const { html } = cardHarness()({
    ...hotel, price_per_night: 100,
    rate_per_night: { extracted_lowest: 999 }, total_rate: { extracted_lowest: 1998 },
  });
  assert.match(html, /From \$100\.00 \/ night/);
  assert.doesNotMatch(html, /999|1,998/);
});

test("USD prices include cents, thousands separators, zero and cent rounding", () => {
  for (const [price, amount] of [[0, "$0.00"], [0.01, "$0.01"], [1234.5, "$1,234.50"], [125.555, "$125.56"]]) {
    const { html } = cardHarness()({ ...hotel, price_per_night: price });
    assert.ok(html.includes(`From ${amount} / night`), html);
  }
});

test("missing, null and blank names show a property placeholder", () => {
  for (const name of [undefined, null, "", "   "]) {
    const { html, image } = cardHarness()({ ...hotel, name });
    assert.match(html, /Unnamed property<\/h3>/);
    assert.equal(image.props.alt, "Hotel thumbnail for Unnamed property");
  }
});

test("missing or invalid prices use the unavailable label without a raw-rate fallback", () => {
  for (const price of [undefined, null, NaN, Infinity, -Infinity, -1]) {
    const { html } = cardHarness()({ ...hotel, price_per_night: price, rate_per_night: { extracted_lowest: 999 } });
    assert.match(html, /Price unavailable/);
    assert.doesNotMatch(html, /From |NaN|Infinity|999/);
  }
});

test("missing or invalid ratings are omitted and valid boundary ratings keep the five-point scale", () => {
  for (const rating of [undefined, null, NaN, Infinity, -1, 5.1]) {
    assert.doesNotMatch(cardHarness()({ ...hotel, rating }).html, /Rating:/);
  }
  for (const rating of [0, 5]) {
    assert.ok(cardHarness()({ ...hotel, rating }).html.includes(`Rating: ${rating} / 5`));
  }
});

test("amenities omit blanks before limiting display to five without changing the source", () => {
  const amenities = Object.freeze(["", "  Wi-Fi  ", " ", "Pool", "Gym", "Spa", "Parking", "Breakfast"]);
  const result = Object.freeze({ ...hotel, amenities });
  const { html } = cardHarness()(result);
  assert.match(html, /Wi-Fi · Pool · Gym · Spa · Parking/);
  assert.doesNotMatch(html, /Breakfast|· ·/);
  assert.equal(result.amenities, amenities);
  assert.equal(amenities[1], "  Wi-Fi  ");
});

test("null, missing, empty and blank-only amenities render no empty separators", () => {
  for (const amenities of [undefined, null, [], ["", "  "]]) {
    const { html } = cardHarness()({ ...hotel, amenities });
    assert.doesNotMatch(html, / · |undefined|null/);
  }
});

test("HTTP(S) thumbnails preserve lazy loading, name-based alt text and reserved dimensions", () => {
  for (const thumbnail of [hotel.thumbnail, "http://images.example.test/hotel.jpg"]) {
    const { image, html } = cardHarness()({ ...hotel, thumbnail });
    assert.equal(image.props.src, thumbnail);
    assert.equal(image.props.alt, "Hotel thumbnail for Provider Hotel");
    assert.equal(image.props.loading, "lazy");
    assert.equal(image.props.decoding, "async");
    assert.equal(image.props.width, 640);
    assert.equal(image.props.height, 360);
    assert.match(html, /aspect-video/);
    assert.doesNotMatch(html, /No image available/);
  }
});

test("absent or invalid thumbnails show an accessible neutral fallback", () => {
  for (const thumbnail of [undefined, null, "", " ", "not a URL", "/hotel.jpg", "javascript:alert(1)", "data:image/png;base64,abc", "ftp://images.example.test/hotel.jpg", 42]) {
    const { html, image } = cardHarness()({ ...hotel, thumbnail });
    assert.equal(image, undefined);
    assert.match(html, /role="img" aria-label="No image available for Provider Hotel"/);
    assert.match(html, /No image available/);
  }
});

test("image errors replace the failed image and a new URL can load normally", () => {
  const render = cardHarness();
  const first = render(hotel);
  first.image.props.onError();
  const failed = render(hotel);
  assert.equal(failed.image, undefined);
  assert.match(failed.html, /No image available for Provider Hotel/);
  assert.match(failed.html, /Provider Hotel<\/h3>/);
  const replacement = render({ ...hotel, thumbnail: "https://images.example.test/replacement.jpg" });
  assert.equal(replacement.image.props.src, "https://images.example.test/replacement.jpg");
});

test("all missing optional display fields render safely and keep Select stay navigation", () => {
  const { html, image } = cardHarness()({ property_token: "synthetic-property" }, "/checkout?property_token=synthetic-property");
  assert.equal(image, undefined);
  assert.match(html, /Unnamed property/);
  assert.match(html, /Price unavailable/);
  assert.doesNotMatch(html, /Rating:|undefined|null|NaN/);
  assert.match(html, /href="\/checkout\?property_token=synthetic-property"/);
  assert.match(html, /Select stay/);
  assert.doesNotMatch(cardHarness()(hotel).html, /Select stay/);
});

test("card presentation preserves full amenity filtering, price sorting and rating sorting", () => {
  const first = Object.freeze({ ...hotel, amenities: Object.freeze(["Wi-Fi", "Pool", "Gym", "Spa", "Parking", "Breakfast"]) });
  const cheaper = Object.freeze({ ...hotel, name: "Budget Hotel", price_per_night: 50, rating: 4.9 });
  const results = Object.freeze([first, cheaper]);
  for (const result of results) cardHarness()(result);
  assert.equal(filterHotels(results, { maxPrice: "130", amenities: ["breakfast"] })[0], first);
  assert.ok(getAmenityOptions(results).some((option) => option.value === "breakfast"));
  assert.deepEqual(sortHotels(results, "price-asc"), [cheaper, first]);
  assert.deepEqual(sortHotels(results, "price-desc"), [first, cheaper]);
  assert.deepEqual(sortHotels(results, "rating-desc"), [cheaper, first]);
  assert.deepEqual(results, [first, cheaper]);
});
