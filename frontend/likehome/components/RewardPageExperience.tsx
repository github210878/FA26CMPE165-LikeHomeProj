"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";
import { ApiError } from "@/lib/api";
import type { RewardHistoryResponse } from "@/lib/api-types";
import { getMyRewardHistory } from "@/lib/rewards";

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "success"; rewards: RewardHistoryResponse };

const pointsFormat = new Intl.NumberFormat("en-US");
const dateFormat = new Intl.DateTimeFormat("en-US", {
  dateStyle: "medium",
  timeStyle: "short",
});

export default function RewardPageExperience() {
  const router = useRouter();
  const { status, invalidateSession } = useAuth();
  const [load, setLoad] = useState<LoadState>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (status === "unauthenticated") {
      router.replace("/login");
      return;
    }
    if (status !== "authenticated") return;

    let active = true;
    getMyRewardHistory().then((rewards) => {
      if (active) setLoad({ kind: "success", rewards });
    }).catch((error: unknown) => {
      if (!active) return;
      if (error instanceof ApiError && error.status === 401) {
        invalidateSession();
        router.replace("/login");
        return;
      }
      setLoad({
        kind: "error",
        message: error instanceof ApiError
          ? `The rewards service returned HTTP ${error.status}.`
          : error instanceof Error && error.name === "TimeoutError"
            ? "The request timed out. Check that the backend is running and try again."
          : error instanceof Error
            ? error.message
            : "An unexpected error occurred.",
      });
    });

    return () => { active = false; };
  }, [attempt, invalidateSession, router, status]);

  return (
    <section className="mx-auto w-full max-w-7xl px-4 py-10 sm:px-6 sm:py-14 lg:px-8">
      <p className="text-sm font-semibold text-teal-700">Your account</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950 sm:text-4xl">
        Reward points
      </h1>

      {load.kind === "loading" && (
        <p role="status" className="mt-8 text-sm text-slate-700">Loading your reward points…</p>
      )}

      {load.kind === "error" && (
        <div role="alert" className="mt-8 rounded-xl border border-red-200 bg-white p-5 text-sm text-red-800">
          <p>We could not load your reward points. {load.message}</p>
          <button
            type="button"
            onClick={() => {
              setLoad({ kind: "loading" });
              setAttempt((previous) => previous + 1);
            }}
            className="mt-3 min-h-11 font-medium text-teal-700 underline"
          >
            Retry
          </button>
        </div>
      )}

      {load.kind === "success" && (
        <>
          <section aria-labelledby="reward-balance-heading" className="mt-8 rounded-2xl border border-teal-200 bg-teal-50 p-6 sm:p-8">
            <h2 id="reward-balance-heading" className="text-sm font-semibold text-teal-800">
              Reward point balance
            </h2>
            <p className="mt-2 text-4xl font-semibold tabular-nums tracking-tight text-slate-950 sm:text-5xl">
              {pointsFormat.format(load.rewards.reward_points)}
              <span className="ml-2 text-base font-medium text-slate-700">points</span>
            </p>
          </section>

          <section aria-labelledby="reward-history-heading" className="mt-10">
            <h2 id="reward-history-heading" className="text-xl font-semibold text-slate-950">
              Reward point history
            </h2>
            {load.rewards.history.length === 0 ? (
              <p className="mt-4 rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-700">
                No reward point activity yet.
              </p>
            ) : (
              <ul className="mt-4 divide-y divide-slate-200 overflow-hidden rounded-xl border border-slate-200 bg-white">
                {load.rewards.history.map((entry) => (
                  <li key={entry.transaction_id} className="flex flex-col gap-2 p-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
                    <div>
                      <p className="font-medium capitalize text-slate-950">{entry.transaction_type}</p>
                      <p className="mt-1 text-sm text-slate-600">
                        <time dateTime={entry.created_at}>
                          {dateFormat.format(new Date(entry.created_at))}
                        </time>
                      </p>
                    </div>
                    <p className={`font-semibold tabular-nums ${entry.points_change < 0 ? "text-slate-700" : "text-teal-700"}`}>
                      {entry.points_change > 0 ? "+" : ""}
                      {pointsFormat.format(entry.points_change)} points
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </section>
  );
}
