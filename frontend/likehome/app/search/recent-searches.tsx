"use client";

import { useSyncExternalStore } from "react";
import type { SearchValues } from "@/lib/search";
import {
  clearRecentSearches,
  getRecentSearchSnapshot,
  getServerSearchSnapshot,
  parseRecentSearches,
  subscribeRecentSearches,
} from "@/lib/recent-searches";

export default function RecentSearches({
  onReplay,
  isLoading,
}: {
  onReplay: (values: SearchValues) => void;
  isLoading: boolean;
}) {
  const snapshot = useSyncExternalStore(
    subscribeRecentSearches, getRecentSearchSnapshot, getServerSearchSnapshot,
  );
  const searches = parseRecentSearches(snapshot);
  if (searches.length === 0) return null;

  return (
    <section className="mt-6 max-w-3xl" aria-labelledby="recent-searches-heading">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="recent-searches-heading" className="text-lg font-semibold text-slate-950">Recent searches</h2>
        <button type="button" onClick={clearRecentSearches} className="min-h-11 rounded-md px-3 text-sm font-medium text-teal-700 hover:bg-teal-50">
          Clear history
        </button>
      </div>
      <ul className="mt-2 grid gap-2">
        {searches.map((values) => (
          <li key={JSON.stringify(values)} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4">
            <div className="min-w-0">
              <p className="break-words font-medium text-slate-950">{values.destination}</p>
              <p className="text-sm leading-6 text-slate-600">
                {values.checkIn} – {values.checkOut} · {values.guests} {values.guests === "1" ? "guest" : "guests"}
              </p>
            </div>
            <button
              type="button"
              disabled={isLoading}
              onClick={() => onReplay(values)}
              aria-label={`Search again for ${values.destination}, ${values.checkIn} to ${values.checkOut}, ${values.guests} guests`}
              className="min-h-11 rounded-md px-3 text-sm font-medium text-teal-700 hover:bg-teal-50 disabled:cursor-not-allowed disabled:opacity-60"
            >
              Search again
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
