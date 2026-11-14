import { ApiError, getAuthorizedJson } from "./api.ts";
import type { RewardHistoryItem, RewardHistoryResponse } from "./api-types.ts";
import { getAccessToken } from "./token-storage.ts";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isRewardHistoryItem(value: unknown): value is RewardHistoryItem {
  if (!isRecord(value)) return false;
  return Number.isSafeInteger(value.transaction_id) &&
    (value.transaction_id as number) !== 0 &&
    Number.isSafeInteger(value.points_change) &&
    (value.transaction_type === "earned" || value.transaction_type === "redeemed") &&
    (value.transaction_type === "earned"
      ? (value.points_change as number) >= 0
      : (value.points_change as number) <= 0) &&
    typeof value.created_at === "string" &&
    !Number.isNaN(Date.parse(value.created_at));
}

function isRewardHistoryResponse(value: unknown): value is RewardHistoryResponse {
  return isRecord(value) &&
    value.status === true &&
    Number.isSafeInteger(value.reward_points) &&
    (value.reward_points as number) >= 0 &&
    Array.isArray(value.history) &&
    value.history.every(isRewardHistoryItem);
}

export async function getMyRewardHistory(): Promise<RewardHistoryResponse> {
  const token = getAccessToken();
  if (!token) throw new ApiError(401);

  const response = await getAuthorizedJson<unknown>(
    "/users/rewards/history",
    token,
    AbortSignal.timeout(15_000),
  );
  if (!isRewardHistoryResponse(response)) {
    throw new Error("Reward history returned an unexpected response");
  }

  return response;
}
