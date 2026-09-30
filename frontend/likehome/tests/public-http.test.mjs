import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { ApiError, getJson, postJson } from "../lib/api.ts";
import { hotelSearchParams } from "../lib/search.ts";
import { validateSignup } from "../lib/signup.ts";

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

test("GET parses JSON from the configured FastAPI base URL", async () => {
  let requestedUrl;
  globalThis.fetch = async (url) => {
    requestedUrl = url;
    return new Response(JSON.stringify({ properties: [] }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };

  assert.deepEqual(await getJson("/hotels/search?q=San+Jose"), { properties: [] });
  assert.equal(requestedUrl, "http://127.0.0.1:8000/hotels/search?q=San+Jose");
});

test("POST sends a JSON registration request", async () => {
  let received;
  globalThis.fetch = async (_url, init) => {
    received = init;
    return new Response(JSON.stringify({ user_id: 17, email: "person@example.com" }), {
      status: 201,
      headers: { "Content-Type": "application/json" },
    });
  };

  const request = {
    email: "person@example.com",
    password: "password123",
    full_name: null,
    phone: null,
  };
  assert.equal((await postJson("/users/register", request)).user_id, 17);
  assert.equal(received.method, "POST");
  assert.equal(received.headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(received.body), request);
});

test("non-JSON error bodies keep their HTTP status", async () => {
  globalThis.fetch = async () => new Response("", { status: 409 });
  await assert.rejects(getJson("/users/register"), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 409);
    return true;
  });

  globalThis.fetch = async () => new Response("server failed", { status: 500 });
  await assert.rejects(getJson("/hotels/search"), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 500);
    return true;
  });

  globalThis.fetch = async () => new Response(JSON.stringify({ detail: [] }), {
    status: 422,
    headers: { "Content-Type": "application/json" },
  });
  await assert.rejects(getJson("/hotels/search"), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 422);
    assert.ok(!error.message.includes("detail"));
    return true;
  });
});

test("connection and malformed-success failures remain distinct", async () => {
  globalThis.fetch = async () => { throw new TypeError("Failed to fetch"); };
  await assert.rejects(getJson("/hotels/search"), TypeError);

  globalThis.fetch = async () => new Response("not JSON", { status: 200 });
  await assert.rejects(getJson("/hotels/search"), /invalid JSON response/);
});

test("search fields map to the FastAPI query contract", () => {
  const query = hotelSearchParams({
    destination: " San Jose hotels ",
    checkIn: "2026-10-05",
    checkOut: "2026-10-08",
    guests: 3,
  });

  assert.deepEqual([...query.entries()], [
    ["q", "San Jose hotels"],
    ["check_in_date", "2026-10-05"],
    ["check_out_date", "2026-10-08"],
    ["adults", "3"],
  ]);
});

test("invalid destination, dates, and guest counts are rejected before fetching", () => {
  const valid = {
    destination: "San Jose",
    checkIn: "2026-10-05",
    checkOut: "2026-10-08",
    guests: 2,
  };

  for (const change of [
    { destination: "  " },
    { checkIn: "" },
    { checkOut: "2026-10-05" },
    { checkIn: "2026-02-31" },
    { guests: 0 },
    { guests: 21 },
    { guests: 1.5 },
  ]) {
    assert.throws(() => hotelSearchParams({ ...valid, ...change }));
  }
});

test("sign-up validation matches required fields and password limits", () => {
  const valid = {
    full_name: "",
    email: "person@example.com",
    phone: "",
    password: "password123",
    confirm_password: "password123",
  };

  assert.deepEqual(validateSignup(valid), {});
  assert.ok(validateSignup({ ...valid, email: "invalid" }).email);
  assert.ok(validateSignup({ ...valid, password: "short" }).password);
  assert.equal(validateSignup({ ...valid, password: "x".repeat(20), confirm_password: "x".repeat(20) }).password, undefined);
  assert.ok(validateSignup({ ...valid, password: "x".repeat(21) }).password);
  assert.ok(validateSignup({ ...valid, confirm_password: "different" }).confirm_password);
  assert.ok(validateSignup({ ...valid, full_name: "x".repeat(101) }).full_name);
  assert.ok(validateSignup({ ...valid, phone: "invalid phone" }).phone);
});
