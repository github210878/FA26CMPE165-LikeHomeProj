"use client";

type RetryButtonProps = {
  onRetry: () => void;
  isRetrying?: boolean;
};

export default function RetryButton({ onRetry, isRetrying = false }: RetryButtonProps) {
  return (
    <button
      type="button"
      onClick={onRetry}
      disabled={isRetrying}
      aria-busy={isRetrying}
      className="min-h-11 rounded-md bg-teal-700 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-teal-800 disabled:cursor-not-allowed disabled:opacity-60"
    >
      {isRetrying ? "Trying again…" : "Try again"}
    </button>
  );
}
