import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";
import { ApiError } from "../lib/api.ts";
import { getShortlist, removeShortlistHotel, saveShortlistHotel, shortlistToken } from "../lib/shortlist.ts";
import { saveAccessToken } from "../lib/token-storage.ts";

const originalFetch = globalThis.fetch;
const originalWindow = globalThis.window;
beforeEach(() => {
  const entries = new Map();
  globalThis.window = { sessionStorage: {
    getItem: (key) => entries.get(key) ?? null,
    setItem: (key, value) => entries.set(key, value),
    removeItem: (key) => entries.delete(key),
  } };
  saveAccessToken("shortlist-test-token");
});
afterEach(() => { globalThis.fetch = originalFetch; globalThis.window = originalWindow; });

test("shortlist tokens reject missing, oversized and unsupported hotel identities", () => {
  for (const token of [null, undefined, "", "  ", "x".repeat(256), "legacy:1", "partner:1"]) assert.equal(shortlistToken(token), null);
  assert.equal(shortlistToken(" property-123 "), "property-123");
});

test("shortlist read uses authentication and validates and deduplicates saved identities", async () => {
  let request;
  globalThis.fetch = async (url, init) => {
    request = { url, init };
    return new Response(JSON.stringify({ properties: [{ property_token: "a" }, { property_token: "b" }, { property_token: "a" }] }));
  };
  assert.deepEqual(await getShortlist(), ["a", "b"]);
  assert.equal(new URL(request.url).pathname, "/shortlist");
  assert.equal(request.init.headers.Authorization, "Bearer shortlist-test-token");
  assert.equal(request.init.cache, "no-store");
  for (const response of [{}, { properties: [null] }, { properties: [{ property_token: 4 }] }, { properties: [{ property_token: "" }] }]) {
    globalThis.fetch = async () => new Response(JSON.stringify(response));
    await assert.rejects(getShortlist(), /Unexpected shortlist/);
  }
});

test("save sends only the property token and requires acknowledgement for the same property", async () => {
  let request;
  globalThis.fetch = async (url, init) => {
    request = { url, init };
    return new Response(JSON.stringify({ property_token: "a" }), { status: 201 });
  };
  await saveShortlistHotel("a");
  assert.equal(new URL(request.url).pathname, "/shortlist");
  assert.equal(request.init.method, "POST");
  assert.equal(request.init.headers.Authorization, "Bearer shortlist-test-token");
  assert.deepEqual(JSON.parse(request.init.body), { property_token: "a" });
  globalThis.fetch = async () => new Response(JSON.stringify({ property_token: "another-hotel" }), { status: 201 });
  await assert.rejects(saveShortlistHotel("a"), /Unexpected saved hotel/);
});

test("already-saved response is accepted without another write", async () => {
  let writes = 0;
  globalThis.fetch = async () => { writes++; return new Response(null, { status: 409 }); };
  await saveShortlistHotel("a");
  assert.equal(writes, 1);
});

test("remove encodes the property token and handles the API's empty 204 response", async () => {
  let request;
  globalThis.fetch = async (url, init) => { request = { url, init }; return new Response(null, { status: 204 }); };
  await removeShortlistHotel("property/with?special=characters");
  assert.equal(new URL(request.url).pathname, "/shortlist/property%2Fwith%3Fspecial%3Dcharacters");
  assert.equal(request.init.method, "DELETE");
  assert.equal(request.init.headers.Authorization, "Bearer shortlist-test-token");
  assert.equal(request.init.body, undefined);
});

test("unavailable API, expired session and failed writes propagate without false success", async () => {
  for (const status of [401, 404, 500, 501]) {
    globalThis.fetch = async () => new Response(JSON.stringify({ detail: "private database information" }), { status });
    for (const action of [getShortlist, () => saveShortlistHotel("a"), () => removeShortlistHotel("a")]) {
      await assert.rejects(action(), (error) => error instanceof ApiError && error.status === status && !error.message.includes("private"));
    }
  }
  globalThis.fetch = async () => { throw new TypeError("Network unavailable"); };
  await assert.rejects(saveShortlistHotel("a"), /Network unavailable/);
});

test("signed-out actions never send an unauthenticated shortlist request", async () => {
  globalThis.window.sessionStorage.removeItem("likehome_access_token");
  let requests = 0;
  globalThis.fetch = async () => { requests++; throw new Error("Unexpected request"); };
  for (const action of [getShortlist, () => saveShortlistHotel("a"), () => removeShortlistHotel("a")]) {
    await assert.rejects(action(), (error) => error instanceof ApiError && error.status === 401);
  }
  assert.equal(requests, 0);
});
