"use client";

import RetryButton from "./RetryButton";

type ErrorStateProps = {
  title?: string;
  message: string;
  onRetry?: () => void;
  isRetrying?: boolean;
};

export default function ErrorState({
  title = "Something went wrong",
  message,
  onRetry,
  isRetrying = false,
}: ErrorStateProps) {
  return (
    <div className="rounded-xl border border-red-200 bg-white p-5 sm:p-6">
      <div role="alert" aria-atomic="true">
        <h3 className="text-base font-semibold text-slate-950">{title}</h3>
        <p className="mt-2 text-sm leading-6 text-slate-700">{message}</p>
      </div>
      {onRetry && (
        <div className="mt-4">
          <RetryButton onRetry={onRetry} isRetrying={isRetrying} />
        </div>
      )}
    </div>
  );
}
