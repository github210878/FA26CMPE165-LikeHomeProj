const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000"
).replace(/\/+$/, "");

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number) {
    super(`API request failed with status ${status}`);
    this.status = status;
  }
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init);

  if (!response.ok) {
    throw new ApiError(response.status);
  }

  try {
    return (await response.json()) as T;
  } catch {
    throw new Error("API returned an invalid JSON response");
  }
}

export function getJson<T>(path: string): Promise<T> {
  return requestJson<T>(path);
}

export function postJson<TResponse, TRequest>(path: string, body: TRequest): Promise<TResponse> {
  return requestJson<TResponse>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
