import { ApiError, getAuthorizedJson, postAuthorizedJson, postJson } from "./api.ts";
import type {
  CurrentUserResponse,
  LoginUserRequest,
  LoginUserResponse,
  LogoutUserResponse,
} from "./api-types.ts";
import { clearAccessToken, getAccessToken, saveAccessToken } from "./token-storage.ts";

export async function loginUser(credentials: LoginUserRequest): Promise<LoginUserResponse> {
  const response = await postJson<LoginUserResponse, LoginUserRequest>("/users/login", credentials);
  if (!response || typeof response.access_token !== "string" || !response.access_token ||
    response.token_type !== "bearer") {
    throw new Error("Login returned an unexpected response");
  }
  return response;
}

export async function getCurrentUser(accessToken: string): Promise<CurrentUserResponse> {
  const response = await getAuthorizedJson<CurrentUserResponse>("/users/me", accessToken);
  if (!response || !Number.isInteger(response.user_id) || response.user_id <= 0 ||
    typeof response.message !== "string") {
    throw new Error("Session verification returned an unexpected response");
  }
  return response;
}

export function logoutUser(accessToken: string): Promise<LogoutUserResponse> {
  return postAuthorizedJson<LogoutUserResponse>("/users/logout", accessToken);
}

export async function createSession(credentials: LoginUserRequest): Promise<CurrentUserResponse> {
  const login = await loginUser(credentials);
  let user: CurrentUserResponse;
  try {
    user = await getCurrentUser(login.access_token);
  } catch {
    throw new Error("Session verification failed");
  }
  saveAccessToken(login.access_token);
  return user;
}

export async function restoreSession(): Promise<CurrentUserResponse | null> {
  const token = getAccessToken();
  if (!token) return null;

  try {
    return await getCurrentUser(token);
  } catch {
    clearAccessToken();
    return null;
  }
}

export async function endSession(): Promise<boolean> {
  const token = getAccessToken();
  try {
    if (token) await logoutUser(token);
    return true;
  } catch {
    return false;
  } finally {
    clearAccessToken();
  }
}

export function loginErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return "Incorrect email or password.";
    if (error.status === 422) return "Please check your email and password.";
  }
  return "We could not sign you in right now. Please try again.";
}
