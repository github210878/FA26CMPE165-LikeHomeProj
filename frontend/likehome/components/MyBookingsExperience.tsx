"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";
import { ApiError } from "@/lib/api";
import type { BookingListResponse } from "@/lib/api-types";
import { getMyBookings } from "@/lib/bookings";

type LoadState =
  | { kind: "loading" }
  | { kind: "empty" }
  | { kind: "success"; bookings: BookingListResponse }
  | { kind: "error" };

export default function MyBookingsExperience() {
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
    getMyBookings().then((bookings) => {
      if (!active) return;
      setLoad(bookings.length === 0 ? { kind: "empty" } : { kind: "success", bookings });
    }).catch((error: unknown) => {
      if (!active) return;
      if (error instanceof ApiError && error.status === 401) {
        invalidateSession();
        router.replace("/login");
        return;
      }
      setLoad({ kind: "error" });
    });
    return () => { active = false; };
  }, [status, attempt, invalidateSession, router]);

  if (status === "restoring") {
    return <p role="status" className="mt-8 text-slate-600">Checking your session…</p>;
  }
  if (status === "unauthenticated") {
    return <p role="status" className="mt-8 text-slate-600">Redirecting to sign in…</p>;
  }
  if (load.kind === "loading") {
    return <p role="status" className="mt-8 text-slate-600">Loading your bookings…</p>;
  }
  if (load.kind === "error") {
    return (
      <div role="alert" className="mt-8 rounded-lg border border-red-200 bg-red-50 p-5 text-red-900">
        <p>We could not load your bookings. Please try again.</p>
        <button type="button" onClick={() => { setLoad({ kind: "loading" }); setAttempt((previous) => previous + 1); }}
          className="mt-4 min-h-11 rounded-md bg-teal-700 px-4 font-medium text-white hover:bg-teal-800">
          Retry
        </button>
      </div>
    );
  }
  if (load.kind === "empty") {
    return (
      <div className="mt-8 border-y border-slate-200 py-10">
        <p className="text-lg font-medium text-slate-950">You don&apos;t have any bookings yet.</p>
        <Link href="/search" className="mt-5 inline-flex min-h-11 items-center rounded-md bg-teal-700 px-4 font-medium text-white hover:bg-teal-800">
          Find a stay
        </Link>
      </div>
    );
  }

  return (
    <ul className="mt-8 space-y-4">
      {load.bookings.map((booking) => (
        <li key={booking.reservation_id} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-xl font-semibold text-slate-950">{booking.hotel_name}</h2>
              <p className="mt-1 text-slate-700">{booking.room_type_name}</p>
            </div>
            <span className="rounded-full bg-slate-100 px-3 py-1 text-sm capitalize text-slate-700">{booking.status}</span>
          </div>
          {booking.hotel_address && <p className="mt-3 text-sm text-slate-600">{booking.hotel_address}</p>}
          <dl className="mt-4 grid gap-3 text-sm text-slate-700 sm:grid-cols-2">
            <div><dt className="font-medium text-slate-900">Check-in</dt><dd><time dateTime={booking.check_in_date}>{booking.check_in_date.slice(0, 10)}</time></dd></div>
            <div><dt className="font-medium text-slate-900">Check-out</dt><dd><time dateTime={booking.check_out_date}>{booking.check_out_date.slice(0, 10)}</time></dd></div>
            <div><dt className="font-medium text-slate-900">Total price</dt><dd>{booking.total_price.toFixed(2)}</dd></div>
            <div><dt className="font-medium text-slate-900">Reservation ID</dt><dd>{booking.reservation_id}</dd></div>
          </dl>
        </li>
      ))}
    </ul>
  );
}
