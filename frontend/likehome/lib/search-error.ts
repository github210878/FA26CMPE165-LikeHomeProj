import { ApiError } from "./api.ts";

export type SearchError = {
  title: string;
  message: string;
  retryable: boolean;
};

export function searchError(error: unknown): SearchError {
  if (error instanceof ApiError && error.status === 422) {
    return {
      title: "Check your search details",
      message: "Please check the destination, dates, and guest count, then search again.",
      retryable: false,
    };
  }

  if (error instanceof ApiError && error.status === 504) {
    return {
      title: "The search took too long",
      message: "We could not load your stays in time. Try the same search again.",
      retryable: true,
    };
  }

  if (error instanceof TypeError) {
    return {
      title: "Unable to connect",
      message: "Check your internet connection, then try the same search again.",
      retryable: true,
    };
  }

  return {
    title: "Unable to load stays",
    message: "Hotel search is unavailable right now. Try the same search again in a moment.",
    retryable: true,
  };
}
