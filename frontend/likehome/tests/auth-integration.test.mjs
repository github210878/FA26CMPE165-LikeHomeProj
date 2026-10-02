import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { ApiError, getJson } from "../lib/api.ts";
import {
  createSession,
  endSession,
  getCurrentUser,
  loginErrorMessage,
  loginUser,
  restoreSession,
} from "../lib/auth.ts";
import { clearAccessToken, getAccessToken, saveAccessToken } from "../lib/token-storage.ts";
import { registerUser } from "../lib/register.ts";

const originalFetch = globalThis.fetch;
const originalWindow = globalThis.window;
afterEach(() => {
  globalThis.fetch = originalFetch;
  globalThis.window = originalWindow;
});

function mockSessionStorage() {
  const entries = new Map();
  globalThis.window = {
    sessionStorage: {
      getItem: (key) => entries.get(key) ?? null,
      setItem: (key, value) => entries.set(key, value),
      removeItem: (key) => entries.delete(key),
    },
  };
  return entries;
}

const baseUrl = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
const credentials = { email: "person@example.com", password: "secret123" };
const loginResponse = {
  user_id: 7,
  email: "person@example.com",
  full_name: "Person Example",
  phone: null,
  access_token: "issued-token",
  token_type: "bearer",
};
const currentUser = { message: "Protected route accessed successfully", user_id: 7 };

test("login posts credentials in JSON body and accepts the backend token response", async () => {
  let request;
  globalThis.fetch = async (url, init) => {
    request = { url, init };
    return new Response(JSON.stringify(loginResponse));
  };

  assert.deepEqual(await loginUser(credentials), loginResponse);
  assert.equal(request.url, `${baseUrl}/users/login`);
  assert.equal(request.init.method, "POST");
  assert.equal(request.init.headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(request.init.body), credentials);
  assert.ok(!request.url.includes(credentials.password));
  assert.ok(!JSON.stringify(request.init.headers).includes(credentials.password));
});

test("login 401, 422, network, and malformed success responses have safe messages", async () => {
  for (const [status, expected] of [[401, /Incorrect email or password/], [422, /check your email/], [503, /try again/]]) {
    globalThis.fetch = async () => new Response("private error", { status });
    await assert.rejects(loginUser(credentials), (error) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status, status);
      assert.match(loginErrorMessage(error), expected);
      assert.ok(!loginErrorMessage(error).includes("private"));
      return true;
    });
  }

  globalThis.fetch = async () => { throw new TypeError("private network detail"); };
  await assert.rejects(loginUser(credentials), (error) => {
    assert.match(loginErrorMessage(error), /try again/);
    assert.ok(!loginErrorMessage(error).includes("private"));
    return true;
  });

  globalThis.fetch = async () => new Response(JSON.stringify({ access_token: "", token_type: "bearer" }));
  await assert.rejects(loginUser(credentials), /unexpected response/);
});

test("token storage saves, retrieves, and clears only the token", () => {
  const entries = mockSessionStorage();
  saveAccessToken("issued-token");
  assert.equal(getAccessToken(), "issued-token");
  assert.equal(entries.size, 1);
  assert.deepEqual([...entries.values()], ["issued-token"]);
  clearAccessToken();
  assert.equal(getAccessToken(), null);
});

test("login verifies /users/me with Bearer before storing the token", async () => {
  mockSessionStorage();
  const requests = [];
  globalThis.fetch = async (url, init) => {
    requests.push({ url, init, stored: getAccessToken() });
    if (url.endsWith("/users/login")) return new Response(JSON.stringify(loginResponse));
    if (url.endsWith("/users/me")) return new Response(JSON.stringify(currentUser));
    throw new Error("Unexpected request");
  };

  assert.deepEqual(await createSession(credentials), currentUser);
  assert.equal(requests.length, 2);
  assert.equal(requests[0].stored, null);
  assert.equal(requests[1].url, `${baseUrl}/users/me`);
  assert.equal(requests[1].init.headers.Authorization, "Bearer issued-token");
  assert.equal(requests[1].init.cache, "no-store");
  assert.equal(requests[1].stored, null);
  assert.equal(getAccessToken(), "issued-token");
});

test("stored sessions are restored only after /users/me verifies them", async () => {
  mockSessionStorage();
  saveAccessToken("stored-token");
  let request;
  globalThis.fetch = async (url, init) => {
    request = { url, init };
    return new Response(JSON.stringify(currentUser));
  };

  assert.deepEqual(await restoreSession(), currentUser);
  assert.equal(request.url, `${baseUrl}/users/me`);
  assert.equal(request.init.headers.Authorization, "Bearer stored-token");
  assert.equal(getAccessToken(), "stored-token");
});

test("failed /users/me verification after login never stores a token", async () => {
  mockSessionStorage();
  globalThis.fetch = async (url) => url.endsWith("/users/login")
    ? new Response(JSON.stringify(loginResponse))
    : new Response("unauthorized", { status: 401 });

  await assert.rejects(createSession(credentials), /Session verification failed/);
  assert.equal(getAccessToken(), null);
});

test("invalid, expired, revoked, or unavailable sessions clear the stored token", async () => {
  mockSessionStorage();
  for (const response of [
    () => new Response("invalid token", { status: 401 }),
    () => new Response("service unavailable", { status: 503 }),
    () => new Response(JSON.stringify({ user_id: "not-a-number" })),
  ]) {
    saveAccessToken("old-token");
    globalThis.fetch = async () => response();
    assert.equal(await restoreSession(), null);
    assert.equal(getAccessToken(), null);
  }

  let called = false;
  globalThis.fetch = async () => { called = true; throw new Error("Should not fetch"); };
  assert.equal(await restoreSession(), null);
  assert.equal(called, false);
});

test("logout posts with Bearer and clears the local token", async () => {
  mockSessionStorage();
  saveAccessToken("issued-token");
  let request;
  globalThis.fetch = async (url, init) => {
    request = { url, init };
    return new Response(JSON.stringify({ status: true, message: "Logged out successfully" }));
  };

  assert.equal(await endSession(), true);
  assert.equal(request.url, `${baseUrl}/users/logout`);
  assert.equal(request.init.method, "POST");
  assert.equal(request.init.headers.Authorization, "Bearer issued-token");
  assert.equal(request.init.body, undefined);
  assert.equal(getAccessToken(), null);
});

test("logout clears local state even when the backend cannot be reached", async () => {
  mockSessionStorage();
  saveAccessToken("issued-token");
  globalThis.fetch = async () => { throw new TypeError("Failed to fetch"); };

  assert.equal(await endSession(), false);
  assert.equal(getAccessToken(), null);
});

test("public requests remain free of Authorization headers", async () => {
  mockSessionStorage();
  saveAccessToken("issued-token");
  let init;
  globalThis.fetch = async (_url, options) => {
    init = options;
    return new Response(JSON.stringify({ ok: true }));
  };

  assert.deepEqual(await getJson("/hotels/search"), { ok: true });
  assert.equal(init, undefined);

  const registration = {
    email: "person@example.com", password: "secret123",
    confirm_password: "secret123", full_name: "", phone: "",
  };
  await registerUser(registration);
  assert.equal(init.headers.Authorization, undefined);
});

test("/users/me rejects a malformed current-user response", async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({ user_id: "7", message: "ok" }));
  await assert.rejects(getCurrentUser("token"), /unexpected response/);
});
