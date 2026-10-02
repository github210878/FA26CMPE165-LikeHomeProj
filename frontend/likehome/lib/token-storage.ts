const ACCESS_TOKEN_KEY = "likehome_access_token";

function browserStorage(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function saveAccessToken(token: string): void {
  const storage = browserStorage();
  if (!storage) throw new Error("Session storage is unavailable");
  storage.setItem(ACCESS_TOKEN_KEY, token);
}

export function getAccessToken(): string | null {
  try {
    const token = browserStorage()?.getItem(ACCESS_TOKEN_KEY) ?? null;
    if (token !== null && !token.trim()) {
      clearAccessToken();
      return null;
    }
    return token;
  } catch {
    return null;
  }
}

export function clearAccessToken(): void {
  try {
    browserStorage()?.removeItem(ACCESS_TOKEN_KEY);
  } catch {
    // A blocked storage API cannot retain frontend authenticated state.
  }
}
