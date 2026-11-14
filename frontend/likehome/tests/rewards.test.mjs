import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { getMyRewardHistory } from "../lib/rewards.ts";

const originalFetch = globalThis.fetch;
const originalWindow = globalThis.window;

afterEach(() => {
  globalThis.fetch = originalFetch;
  globalThis.window = originalWindow;
});

test("reward history uses the signed-in session and a bounded request", async () => {
  globalThis.window = {
    sessionStorage: {
      getItem: (key) => key === "likehome_access_token" ? "session-token" : null,
    },
  };
  let request;
  globalThis.fetch = async (url, init) => {
    request = { url, init };
    return new Response(JSON.stringify({
      status: true,
      reward_points: 14,
      history: [{
        transaction_id: 8,
        points_change: 14,
        transaction_type: "earned",
        created_at: "2026-11-12T12:00:00",
      }],
    }));
  };

  const result = await getMyRewardHistory();

  assert.equal(request.url.endsWith("/users/rewards/history"), true);
  assert.equal(request.init.headers.Authorization, "Bearer session-token");
  assert.ok(request.init.signal instanceof AbortSignal);
  assert.equal(result.reward_points, 14);
  assert.equal(result.history[0].points_change, 14);
});
