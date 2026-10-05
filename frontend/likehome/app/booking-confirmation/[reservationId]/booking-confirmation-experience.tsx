"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";
import { ApiError } from "@/lib/api";
import type { BookingDetailItem } from "@/lib/api-types";
import { parseReservationId } from "@/lib/booking-confirmation";
import { getBookingDetails } from "@/lib/bookings";

type DetailState =
  | { kind: "loading"; key: string }
  | { kind: "success"; key: string; booking: BookingDetailItem }
  | { kind: "not-found"; key: string }
  | { kind: "error"; key: string };

const dollars = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

export default function BookingConfirmationExperience({ reservationId }: { reservationId: string }) {
  const router = useRouter();
  const { status, invalidateSession } = useAuth();
  const [attempt, setAttempt] = useState(0);
  const [detail, setDetail] = useState<DetailState>({ kind: "loading", key: "" });
  const key = `${reservationId}:${attempt}`;
  const id = parseReservationId(reservationId);

  useEffect(() => {
    if (status === "unauthenticated") {
      router.replace("/login");
      return;
    }
    if (status !== "authenticated") return;
    if (id === null) return;

    let active = true;
    getBookingDetails(id).then((booking) => {
      if (!active) return;
      setDetail(booking && booking.reservation_id === id
        ? { kind: "success", key, booking }
        : { kind: "not-found", key });
    }).catch((error: unknown) => {
      if (!active) return;
      if (error instanceof ApiError && error.status === 401) {
        invalidateSession();
        router.replace("/login");
        return;
      }
      setDetail(error instanceof ApiError && error.status === 404
        ? { kind: "not-found", key }
        : { kind: "error", key });
    });
    return () => { active = false; };
  }, [status, id, key, invalidateSession, router]);

  if (status === "restoring") {
    return <p role="status" className="mt-8 text-slate-700">Checking your session…</p>;
  }
  if (status === "unauthenticated") {
    return <p role="status" className="mt-8 text-slate-700">Taking you to sign in…</p>;
  }

  const current = id === null ? { kind: "not-found" as const } : detail.key === key ? detail : { kind: "loading" as const };
  if (current.kind === "loading") {
    return <p role="status" className="mt-8 text-slate-700">Loading booking details…</p>;
  }

  return <div className="mt-8 space-y-6">
    {current.kind === "not-found" && <div role="alert" className="rounded-lg border border-slate-200 bg-white p-6 text-slate-800">
      This booking could not be found.
    </div>}
    {current.kind === "error" && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-6 text-red-900">
      <p>We couldn&apos;t load your booking details right now. Your reservation may still be available.</p>
      <button type="button" onClick={() => setAttempt((value) => value + 1)}
        className="mt-4 min-h-11 font-medium text-teal-700 underline">Retry</button>
    </div>}
    {current.kind === "success" && <div className="rounded-xl border border-teal-200 bg-white p-6 shadow-sm sm:p-8">
      <h2 className="text-2xl font-semibold text-slate-950">
        {current.booking.status === "confirmed" ? "Booking created successfully" : "Reservation details"}
      </h2>
      {current.booking.status === "confirmed" && <p className="mt-2 text-slate-700">Your reservation has been created.</p>}
      <dl className="mt-6 grid gap-4 text-sm text-slate-700 sm:grid-cols-2">
        <div><dt className="font-medium text-slate-950">Reservation ID</dt><dd>{current.booking.reservation_id}</dd></div>
        <div><dt className="font-medium text-slate-950">Status</dt><dd className="capitalize">{current.booking.status}</dd></div>
        <div><dt className="font-medium text-slate-950">Hotel</dt><dd>{current.booking.hotel_name}</dd></div>
        <div><dt className="font-medium text-slate-950">Room type</dt><dd>{current.booking.room_type_name}</dd></div>
        {current.booking.guest_full_name && <div><dt className="font-medium text-slate-950">Primary guest</dt><dd>{current.booking.guest_full_name}</dd></div>}
        {current.booking.guest_email && <div><dt className="font-medium text-slate-950">Contact email</dt><dd>{current.booking.guest_email}</dd></div>}
        <div><dt className="font-medium text-slate-950">Check-in</dt><dd><time dateTime={current.booking.check_in_date}>{current.booking.check_in_date.slice(0, 10)}</time></dd></div>
        <div><dt className="font-medium text-slate-950">Check-out</dt><dd><time dateTime={current.booking.check_out_date}>{current.booking.check_out_date.slice(0, 10)}</time></dd></div>
        <div><dt className="font-medium text-slate-950">Total price</dt><dd>{dollars.format(current.booking.total_price)}</dd></div>
        {current.booking.hotel_address && <div><dt className="font-medium text-slate-950">Hotel address</dt><dd>{current.booking.hotel_address}</dd></div>}
        {current.booking.hotel_phone && <div><dt className="font-medium text-slate-950">Hotel phone</dt><dd>{current.booking.hotel_phone}</dd></div>}
        {current.booking.room_description && <div><dt className="font-medium text-slate-950">Room description</dt><dd>{current.booking.room_description}</dd></div>}
        {current.booking.hotel_description && <div><dt className="font-medium text-slate-950">Hotel description</dt><dd>{current.booking.hotel_description}</dd></div>}
      </dl>
    </div>}
    <Link href="/my-bookings" className="inline-flex min-h-11 items-center rounded-md bg-teal-700 px-5 font-medium text-white hover:bg-teal-800">
      View My Bookings
    </Link>
  </div>;
}
