import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { ApiError } from "../lib/api.ts";
import { registerUser, registrationErrorMessage, registrationRequest } from "../lib/register.ts";
import { validateSignup } from "../lib/signup.ts";

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

const values = {
  full_name: "  Person Example  ",
  email: "  Person@Example.com  ",
  phone: "  555-0100  ",
  password: "password123",
  confirm_password: "password123",
};

test("registration maps validated fields without sending password confirmation", () => {
  assert.deepEqual(validateSignup(values), {});
  assert.deepEqual(registrationRequest(values), {
    email: "Person@Example.com",
    password: "password123",
    full_name: "Person Example",
    phone: "555-0100",
  });
  assert.deepEqual(registrationRequest({ ...values, full_name: "  ", phone: "  " }), {
    email: "Person@Example.com",
    password: "password123",
  });
});

test("registration sends JSON POST and accepts a 201 public response", async () => {
  let requestedUrl;
  let requestedInit;
  const publicResponse = {
    user_id: 7,
    email: "person@example.com",
    full_name: "Person Example",
    phone: "555-0100",
  };
  globalThis.fetch = async (url, init) => {
    requestedUrl = url;
    requestedInit = init;
    return new Response(JSON.stringify(publicResponse), { status: 201 });
  };

  assert.deepEqual(await registerUser(values), publicResponse);
  const baseUrl = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
  assert.equal(requestedUrl, `${baseUrl}/users/register`);
  assert.equal(requestedInit.method, "POST");
  assert.equal(requestedInit.headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(requestedInit.body), registrationRequest(values));
  assert.ok(!requestedInit.body.includes("confirm_password"));
});

test("duplicate 409 has a safe, specific message", async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: "private backend detail" }), { status: 409 });

  await assert.rejects(registerUser(values), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 409);
    assert.match(registrationErrorMessage(error), /already registered/);
    assert.ok(!registrationErrorMessage(error).includes("private backend detail"));
    return true;
  });
});

test("validation 422 is reported safely even with non-JSON or empty errors", async () => {
  for (const body of ["not JSON", null]) {
    globalThis.fetch = async () => new Response(body, { status: 422 });
    await assert.rejects(registerUser(values), (error) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status, 422);
      assert.match(registrationErrorMessage(error), /check your details/);
      return true;
    });
  }
});

test("network and service failures use a generic retry message", async () => {
  for (const failure of [new TypeError("private network detail"), new Error("private service detail")]) {
    globalThis.fetch = async () => { throw failure; };
    await assert.rejects(registerUser(values), (error) => {
      assert.equal(error, failure);
      assert.match(registrationErrorMessage(error), /try again/);
      assert.ok(!registrationErrorMessage(error).includes("private"));
      return true;
    });
  }

  globalThis.fetch = async () => new Response("private stack trace", { status: 503 });
  await assert.rejects(registerUser(values), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 503);
    assert.match(registrationErrorMessage(error), /try again/);
    assert.ok(!registrationErrorMessage(error).includes("private"));
    return true;
  });
});
