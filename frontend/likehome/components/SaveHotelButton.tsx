"use client";

import { useEffect } from "react";
import Link from "next/link";
import { HiHeart, HiOutlineHeart } from "react-icons/hi2";
import { useAuth } from "@/components/AuthProvider";
import { useShortlist } from "@/components/ShortlistProvider";
import { shortlistToken } from "@/lib/shortlist";

const controlClass = "inline-flex min-h-11 items-center justify-center gap-2 rounded-full border border-slate-300 bg-white px-4 text-sm font-semibold text-teal-800 transition-colors hover:border-teal-700 hover:bg-teal-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700 disabled:cursor-not-allowed disabled:opacity-60";

export default function SaveHotelButton({ propertyToken, hotelName }: { propertyToken: string | null; hotelName: string | null }) {
  const { status: authStatus } = useAuth();
  const { status, saved, operations, load, toggle } = useShortlist();
  const token = shortlistToken(propertyToken);

  useEffect(() => {
    if (token && authStatus === "authenticated") void load();
  }, [token, authStatus, load]);

  if (!token) return <p className="text-xs text-slate-600">Saving unavailable for this stay.</p>;
  if (authStatus === "unauthenticated") return <Link href="/login" className={controlClass} aria-label={`Sign in to save ${hotelName || "this stay"}`}><HiOutlineHeart aria-hidden="true" className="h-5 w-5" />Sign in to save</Link>;
  if (status === "error" && authStatus === "authenticated") return <div className="space-y-1">
    <p className="text-xs text-slate-600">Saved stays are unavailable right now.</p>
    <button type="button" onClick={() => void load(true)} className={controlClass}>Retry saved stays</button>
  </div>;

  const isSaved = saved.has(token);
  const operation = operations[token];
  const loading = authStatus === "restoring" || status === "idle" || status === "loading";
  const Icon = isSaved ? HiHeart : HiOutlineHeart;
  return <div className="space-y-2">
    <button type="button" aria-pressed={isSaved} aria-label={`${isSaved ? "Remove" : "Save"} ${hotelName || "this stay"}${isSaved ? " from" : " to"} shortlist`}
      disabled={loading || operation?.pending} onClick={() => void toggle(token)} className={controlClass}>
      <Icon aria-hidden="true" className="h-5 w-5 shrink-0" />
      {loading ? "Checking saved stays…" : operation?.pending ? isSaved ? "Removing…" : "Saving…" : isSaved ? "Saved · Remove" : "Save stay"}
    </button>
    <p role="status" aria-live="polite" className={`text-xs ${operation?.error ? "text-red-700" : "text-teal-800"}`}>{operation?.message}</p>
  </div>;
}
