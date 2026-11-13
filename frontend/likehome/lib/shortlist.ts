import { ApiError, deleteAuthorized, getAuthorizedJson, postAuthorizedJson } from "./api.ts";
import { getAccessToken } from "./token-storage.ts";

export function shortlistToken(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const token = value.trim();
  return token && token.length <= 255 && !token.startsWith("legacy:") && !token.startsWith("partner:") ? token : null;
}

function accessToken(): string {
  const token = getAccessToken();
  if (!token) throw new ApiError(401);
  return token;
}

export async function getShortlist(): Promise<string[]> {
  const result = await getAuthorizedJson<unknown>("/shortlist", accessToken());
  if (!result || typeof result !== "object" || !("properties" in result) || !Array.isArray(result.properties)) {
    throw new Error("Unexpected shortlist response");
  }
  const tokens = result.properties.map((item: unknown) => {
    if (!item || typeof item !== "object" || !("property_token" in item)) throw new Error("Unexpected shortlist entry");
    const token = shortlistToken(item.property_token);
    if (!token) throw new Error("Unexpected shortlist entry");
    return token;
  });
  return [...new Set(tokens)];
}

export async function saveShortlistHotel(propertyToken: string): Promise<void> {
  const token = shortlistToken(propertyToken);
  if (!token) throw new Error("Invalid property token");
  try {
    const result = await postAuthorizedJson<unknown, { property_token: string }>("/shortlist", accessToken(), { property_token: token });
    if (!result || typeof result !== "object" || !("property_token" in result) || result.property_token !== token) {
      throw new Error("Unexpected saved hotel response");
    }
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 409) throw error;
  }
}

export async function removeShortlistHotel(propertyToken: string): Promise<void> {
  const token = shortlistToken(propertyToken);
  if (!token) throw new Error("Invalid property token");
  await deleteAuthorized(`/shortlist/${encodeURIComponent(token)}`, accessToken());
}
