import assert from "node:assert/strict";
import { test } from "node:test";
import { ApiError } from "../lib/api.ts";
import { searchError } from "../lib/search-error.ts";

test("invalid search details require correction instead of retry", () => {
  const result = searchError(new ApiError(422));
  assert.equal(result.retryable, false);
  assert.match(result.message, /destination, dates, and guest count/);
});

test("timeouts and network failures offer relevant recovery instructions", () => {
  const timeout = searchError(new ApiError(504));
  assert.equal(timeout.retryable, true);
  assert.match(timeout.title, /too long/);
  const network = searchError(new TypeError("private network details"));
  assert.equal(network.retryable, true);
  assert.match(network.message, /internet connection/);
});

test("service failures and unexpected errors never expose internal details", () => {
  for (const error of [new ApiError(502), new ApiError(500), new Error("secret API key"), null]) {
    const result = searchError(error);
    assert.equal(result.retryable, true);
    assert.equal(result.title, "Unable to load stays");
    assert.doesNotMatch(result.message, /secret|API key|502|500/);
  }
});
