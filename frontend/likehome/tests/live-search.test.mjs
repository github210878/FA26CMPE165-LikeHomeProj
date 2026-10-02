import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { ApiError, getJson } from "../lib/api.ts";
import { hotelSearchParams, searchHotels } from "../lib/search.ts";

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

const values = {
  destination: " San Jose hotels ",
  checkIn: "2026-10-05",
  checkOut: "2026-10-08",
  guests: " 3 ",
};

test("validated form values map to the current hotel query contract", () => {
  assert.deepEqual([...hotelSearchParams(values).entries()], [
    ["q", "San Jose hotels"],
    ["check_in_date", "2026-10-05"],
    ["check_out_date", "2026-10-08"],
    ["adults", "3"],
  ]);
});

test("live search GET returns normalized hotel results", async () => {
  let requestedUrl;
  const payload = {
    search_query: "San Jose hotels",
    check_in_date: "2026-10-05",
    check_out_date: "2026-10-08",
    result_count: 1,
    properties: [{
      name: "Test Hotel",
      property_token: "property-123",
      price_per_night: 125,
      rating: 4.5,
      amenities: ["Pool"],
      thumbnail: "https://images.example.com/hotel.jpg",
    }],
  };
  globalThis.fetch = async (url) => {
    requestedUrl = url;
    return new Response(JSON.stringify(payload), { status: 200 });
  };

  assert.deepEqual(await searchHotels(values), payload);
  const baseUrl = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
  assert.equal(requestedUrl, `${baseUrl}/hotels/search?${hotelSearchParams(values)}`);
});

test("empty search results are accepted", async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({
    search_query: "San Jose hotels",
    check_in_date: "2026-10-05",
    check_out_date: "2026-10-08",
    result_count: 0,
    properties: [],
  }));

  assert.deepEqual((await searchHotels(values)).properties, []);
});

test("HTTP errors expose status without backend response details", async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: "private backend detail" }), { status: 502 });

  await assert.rejects(searchHotels(values), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 502);
    assert.ok(!error.message.includes("private backend detail"));
    return true;
  });
});

test("network errors, empty responses, and malformed JSON are reported", async () => {
  globalThis.fetch = async () => { throw new TypeError("Failed to fetch"); };
  await assert.rejects(searchHotels(values), TypeError);

  globalThis.fetch = async () => new Response(null, { status: 200 });
  await assert.rejects(getJson("/hotels/search"), /invalid JSON response/);

  globalThis.fetch = async () => new Response("not JSON", { status: 200 });
  await assert.rejects(searchHotels(values), /invalid JSON response/);
});

test("malformed successful search payloads are rejected before rendering", async () => {
  for (const payload of [{}, { properties: null }, {
    search_query: "San Jose hotels",
    check_in_date: "2026-10-05",
    check_out_date: "2026-10-08",
    result_count: 1,
    properties: [{}],
  }]) {
    globalThis.fetch = async () => new Response(JSON.stringify(payload), { status: 200 });
    await assert.rejects(searchHotels(values), /unexpected response/);
  }
});
