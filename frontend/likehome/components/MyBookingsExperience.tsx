"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";
import { ApiError } from "@/lib/api";
import type { BookingListItem, BookingListResponse, PaymentResponse } from "@/lib/api-types";
import { canCancelBooking, cancellationErrorMessage, createCancellationSubmissionGuard, keepBooking, requestCancellation, startCancellation, type CancellationPhase } from "@/lib/booking-cancellation";
import { cancelBookingAndRefresh, getBookingDetails, getMyBookings, getMyPayments } from "@/lib/bookings";
import { bookingPaymentForReservation, paymentHref } from "@/lib/payment";
import { BookingDetailsSkeleton, BookingListSkeleton, SessionLoadingSkeleton } from "@/components/LoadingSkeletons";
import ReservationChangeFlow from "@/components/ReservationChangeFlow";


type LoadState =
  | { kind: "loading" }
  | { kind: "empty" }
  | { kind: "success"; bookings: BookingListResponse; payments: PaymentResponse[] }
  | { kind: "error" };

type RecordedCancellation = { booking: BookingListItem; payments: PaymentResponse[] };

function bookingListState(
  bookings: BookingListResponse, payments: PaymentResponse[], recorded: Map<number, RecordedCancellation>,
): LoadState {
  // A validated cancellation acknowledgement remains authoritative when a later
  // list read is stale or incomplete. Retain recorded amounts, never calculate them.
  const currentBookings = bookings.map((booking) => booking.status !== "cancelled"
    ? recorded.get(booking.reservation_id)?.booking ?? booking : booking);
  const currentPayments = payments.map((payment) => {
    const known = recorded.get(payment.reservation_id)?.payments.find((entry) => entry.payment_id === payment.payment_id);
    return known?.payment_type === "booking" && known.payment_status === "refunded"
      ? { ...payment, payment_status: known.payment_status } : payment;
  });
  for (const entry of recorded.values()) {
    if (!currentBookings.some((booking) => booking.reservation_id === entry.booking.reservation_id)) {
      currentBookings.push(entry.booking);
    }
    for (const payment of entry.payments) {
      if (!currentPayments.some((current) => current.payment_id === payment.payment_id)) currentPayments.push(payment);
    }
  }
  return currentBookings.length === 0 ? { kind: "empty" }
    : { kind: "success", bookings: currentBookings, payments: currentPayments };
}

type DetailState =
  | { kind: "loading" }
  | { kind: "success"; booking: BookingListItem }
  | { kind: "not-found" }
  | { kind: "error" };

function BookingDetailPanel({ reservationId, reservationStatus }: {
  reservationId: number; reservationStatus: BookingListItem["status"];
}) {
  const router = useRouter();
  const { invalidateSession } = useAuth();
  const [detail, setDetail] = useState<DetailState>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    getBookingDetails(reservationId).then((booking) => {
      if (!active) return;
      setDetail(booking ? { kind: "success", booking } : { kind: "not-found" });
    }).catch((error: unknown) => {
      if (!active) return;
      if (error instanceof ApiError && error.status === 401) {
        invalidateSession();
        router.replace("/login");
        return;
      }
      setDetail(error instanceof ApiError && error.status === 404 ? { kind: "not-found" } : { kind: "error" });
    });
    return () => { active = false; };
  }, [reservationId, attempt, invalidateSession, router]);

  if (detail.kind === "loading") {
    return <BookingDetailsSkeleton />;
  }
  if (detail.kind === "not-found") {
    return <p className="mt-4 text-sm text-slate-700">This booking is no longer available.</p>;
  }
  if (detail.kind === "error") {
    return (
      <div role="alert" className="mt-4 text-sm text-red-800">
        <p>We could not load these booking details. Please try again.</p>
        <button type="button" onClick={() => { setDetail({ kind: "loading" }); setAttempt((previous) => previous + 1); }}
          className="mt-2 min-h-11 font-medium text-teal-700 underline">Retry details</button>
      </div>
    );
  }

  const booking = detail.booking;
  return (
    <div className="mt-4 border-t border-slate-200 pt-4">
      <h3 className="font-semibold text-slate-950">Booking details</h3>
      <dl className="mt-3 grid gap-3 text-sm text-slate-700 sm:grid-cols-2">
        <div><dt className="font-medium text-slate-900">Hotel</dt><dd>{booking.hotel_name}</dd></div>
        <div><dt className="font-medium text-slate-900">Room type</dt><dd>{booking.room_type_name}</dd></div>
        {booking.hotel_address && <div><dt className="font-medium text-slate-900">Address</dt><dd>{booking.hotel_address}</dd></div>}
        {booking.hotel_phone && <div><dt className="font-medium text-slate-900">Hotel phone</dt><dd>{booking.hotel_phone}</dd></div>}
        {booking.hotel_description && <div><dt className="font-medium text-slate-900">Hotel description</dt><dd>{booking.hotel_description}</dd></div>}
        {booking.room_description && <div><dt className="font-medium text-slate-900">Room description</dt><dd>{booking.room_description}</dd></div>}
        <div><dt className="font-medium text-slate-900">Price per night</dt><dd>{booking.price_per_night.toFixed(2)}</dd></div>
        <div><dt className="font-medium text-slate-900">Status</dt><dd className="capitalize">{reservationStatus === "cancelled" ? reservationStatus : booking.status}</dd></div>
      </dl>
    </div>
  );
}

export default function MyBookingsExperience() {
  const router = useRouter();
  const { status, invalidateSession } = useAuth();
  const [load, setLoad] = useState<LoadState>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [expandedReservationId, setExpandedReservationId] = useState<number | null>(null);
  const [changingReservationId, setChangingReservationId] = useState<number | null>(null);
  const [cancellationPhase, setCancellationPhase] = useState<CancellationPhase>({ kind: "idle" });
  const [cancellationNotice, setCancellationNotice] = useState<{ kind: "success" | "error"; message: string } | null>(null);
  const [blockedReservationIds, setBlockedReservationIds] = useState<Set<number>>(() => new Set());
  const [refreshFailed, setRefreshFailed] = useState(false);
  const recordedCancellations = useRef(new Map<number, RecordedCancellation>());
  const requestGeneration = useRef(0);
  const submissionGuard = useRef(createCancellationSubmissionGuard());

  useEffect(() => {
    requestGeneration.current += 1;
    if (status !== "authenticated") recordedCancellations.current.clear();
    if (status === "unauthenticated") {
      router.replace("/login");
      return;
    }
    if (status !== "authenticated") return;

    let active = true;
    Promise.all([getMyBookings(), getMyPayments()]).then(([bookings, payments]) => {
      if (!active) return;
      setLoad(bookingListState(bookings, payments, recordedCancellations.current));
      setRefreshFailed(false);
    }).catch((error: unknown) => {
      if (!active) return;
      if (error instanceof ApiError && error.status === 401) {
        invalidateSession();
        router.replace("/login");
        return;
      }
      if (recordedCancellations.current.size > 0) setRefreshFailed(true);
      else setLoad({ kind: "error" });
    });
    return () => { active = false; requestGeneration.current += 1; };
  }, [status, attempt, invalidateSession, router]);

  async function refreshBookingsAfterCancellation() {
    const generation = requestGeneration.current;
    setLoad({ kind: "loading" });
    try {
      const [bookings, payments] = await Promise.all([getMyBookings(), getMyPayments()]);
      if (generation !== requestGeneration.current) return;
      setLoad(bookingListState(bookings, payments, recordedCancellations.current));
    } catch (error: unknown) {
      if (generation !== requestGeneration.current) return;
      if (error instanceof ApiError && error.status === 401) {
        invalidateSession();
        router.replace("/login");
        return;
      }
      setLoad({ kind: "error" });
    }
  }

  async function confirmCancellation(reservationId: number) {
    if (load.kind !== "success" || cancellationPhase.kind !== "confirming" ||
        cancellationPhase.reservationId !== reservationId) return;
    if (!submissionGuard.current.tryStart(reservationId)) return;

    setCancellationPhase((phase) => startCancellation(phase, reservationId));
    setCancellationNotice(null);
    setRefreshFailed(false);
    const generation = requestGeneration.current;
    let cancellationRecorded = false;
    try {
      const result = await cancelBookingAndRefresh(reservationId, (response) => {
        if (generation !== requestGeneration.current) return;
        cancellationRecorded = true;
        const booking = load.bookings.find((entry) => entry.reservation_id === reservationId);
        if (booking) {
          const payments = load.payments.filter((entry) => entry.payment_id === response.booking_payment_id)
            .map((entry) => ({ ...entry, payment_status: response.booking_payment_status }));
          if (Number.isSafeInteger(response.cancellation_payment_id) && Number.isFinite(response.cancellation_amount)
            && response.cancellation_payment_status === "pending") {
            payments.push({ payment_id: response.cancellation_payment_id, reservation_id: reservationId,
              amount: response.cancellation_amount, payment_type: "cancellation", payment_status: response.cancellation_payment_status });
          }
          recordedCancellations.current.set(reservationId, { booking: { ...booking, status: response.status }, payments });
        }
        setExpandedReservationId(null);
        setCancellationNotice({ kind: "success", message: "Cancellation recorded. The cancellation charge is recorded separately; no external payment was collected." });
        setLoad(bookingListState(load.bookings, load.payments, recordedCancellations.current));
      });
      if (generation !== requestGeneration.current) return;
      if (result.kind === "refresh-error") throw result.error;
      const payments = await getMyPayments();
      if (generation !== requestGeneration.current) return;
      setLoad(bookingListState(result.bookings, payments, recordedCancellations.current));
    } catch (error: unknown) {
      if (generation !== requestGeneration.current) return;
      if (error instanceof ApiError && error.status === 401) {
        invalidateSession();
        router.replace("/login");
        return;
      }
      if (cancellationRecorded) {
        setRefreshFailed(true);
        return;
      }
      setCancellationNotice({ kind: "error", message: cancellationErrorMessage(error) });
      if (error instanceof ApiError && error.status === 409) {
        setBlockedReservationIds((current) => new Set(current).add(reservationId));
        setExpandedReservationId(null);
        await refreshBookingsAfterCancellation();
      } else if (error instanceof ApiError && error.status === 404) {
        setExpandedReservationId(null);
      }
    } finally {
      submissionGuard.current.finish();
      if (generation === requestGeneration.current) setCancellationPhase({ kind: "idle" });
    }
  }

  if (status === "restoring") {
    return <SessionLoadingSkeleton />;
  }
  if (status === "unauthenticated") {
    return <p role="status" className="mt-8 text-slate-600">Redirecting to sign in…</p>;
  }
  const notice = <>
    {cancellationNotice && <p role={cancellationNotice.kind === "error" ? "alert" : "status"}
      className={`mt-6 rounded-lg border p-4 text-sm ${cancellationNotice.kind === "error" ? "border-red-200 bg-red-50 text-red-900" : "border-teal-200 bg-teal-50 text-teal-900"}`}>
      {cancellationNotice.message}
    </p>}
    {refreshFailed && <div role="alert" className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
      <p>We could not refresh your bookings and payment details. Your recorded cancellation is still shown.</p>
      <button type="button" onClick={() => { setRefreshFailed(false); setAttempt((previous) => previous + 1); }}
        className="mt-3 min-h-11 font-medium underline">Retry</button>
    </div>}
  </>;
  if (load.kind === "loading") {
    return <>{notice}<BookingListSkeleton /></>;
  }
  if (load.kind === "error") {
    return (
      <>{notice}
        <div role="alert" className="mt-8 rounded-lg border border-red-200 bg-red-50 p-5 text-red-900">
          <p>We could not load your bookings. Please try again.</p>
          <button type="button" onClick={() => { setLoad({ kind: "loading" }); setAttempt((previous) => previous + 1); }}
            className="mt-4 min-h-11 rounded-md bg-teal-700 px-4 font-medium text-white hover:bg-teal-800">
            Retry
          </button>
        </div>
      </>
    );
  }
  if (load.kind === "empty") {
    return (
      <>{notice}
        <div className="mt-8 border-y border-slate-200 py-10">
          <p className="text-lg font-medium text-slate-950">You don&apos;t have any bookings yet.</p>
          <Link href="/search" className="mt-5 inline-flex min-h-11 items-center rounded-md bg-teal-700 px-4 font-medium text-white hover:bg-teal-800">
            Find a stay
          </Link>
        </div>
      </>
    );
  }

  return (
    <>{notice}
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
          {(() => {
            const payment = bookingPaymentForReservation(load.payments, booking.reservation_id);
            const cancellation = load.payments.find((entry) => entry.reservation_id === booking.reservation_id && entry.payment_type === "cancellation");
            return (payment || cancellation) && <div className="mt-4 text-sm text-slate-700">
              {payment && <p>LikeHome booking payment: <span className="capitalize">{payment.payment_status}</span> ({payment.amount.toFixed(2)} USD)
                {payment.payment_status === "refunded" && <span> Internal record only; this does not confirm an external refund.</span>}</p>}
              {cancellation && <p>LikeHome cancellation charge: <span className="capitalize">{cancellation.payment_status}</span> ({cancellation.amount.toFixed(2)} USD). No external charge was made.</p>}
              {payment && booking.status === "confirmed" && payment.payment_status === "pending" &&
                <Link href={paymentHref(payment.payment_id)} className="mt-2 inline-block min-h-11 font-medium text-teal-700 underline">Complete payment</Link>}
            </div>;
          })()}
          <button type="button" aria-expanded={expandedReservationId === booking.reservation_id}
            onClick={() => setExpandedReservationId((current) => current === booking.reservation_id ? null : booking.reservation_id)}
            className="mt-4 min-h-11 font-medium text-teal-700 underline">
            {expandedReservationId === booking.reservation_id ? "Hide details" : "View details"}
          </button>

    {expandedReservationId === booking.reservation_id && (
        <BookingDetailPanel
            reservationId={booking.reservation_id}
            reservationStatus={booking.status}
        />
    )}

    {booking.status === "confirmed" && (
        <div className="mt-4">
          <button
              type="button"
              aria-expanded={changingReservationId === booking.reservation_id}
              onClick={() =>
                  setChangingReservationId((current) =>
                      current === booking.reservation_id
                          ? null
                          : booking.reservation_id
                  )
              }
              className="min-h-11 font-medium text-teal-700 underline"
          >
            {changingReservationId === booking.reservation_id
                ? "Hide Change Booking"
                : "Change Booking"}
          </button>

          {changingReservationId === booking.reservation_id && (
              <div className="mt-4 rounded-lg border border-slate-200 p-4">
                <ReservationChangeFlow
                    key={booking.reservation_id}
                    reservationId={booking.reservation_id}
                    checkInDate={booking.check_in_date}
                    checkOutDate={booking.check_out_date}
                    enableConfirmation={false}
                    onRefreshCurrent={async () => {
                      const [bookings, payments] = await Promise.all([
                        getMyBookings(),
                        getMyPayments(),
                      ]);

                      setLoad(
                          bookings.length === 0
                              ? { kind: "empty" }
                              : { kind: "success", bookings, payments }
                      );
                    }}
                />
              </div>
          )}
        </div>
    )}
          {canCancelBooking(booking.status) && !blockedReservationIds.has(booking.reservation_id) && (
            cancellationPhase.kind !== "idle" && cancellationPhase.reservationId === booking.reservation_id ? (
              <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-4">
                <p className="text-sm text-slate-800">Are you sure you want to cancel this booking?</p>
                <div className="mt-3 flex flex-wrap gap-3">
                  <button type="button" disabled={cancellationPhase.kind === "submitting"}
                    onClick={() => void confirmCancellation(booking.reservation_id)}
                    className="min-h-11 rounded-md bg-red-700 px-4 font-medium text-white hover:bg-red-800 disabled:cursor-wait disabled:opacity-60">
                    {cancellationPhase.kind === "submitting" ? "Cancelling…" : "Confirm cancellation"}
                  </button>
                  <button type="button" disabled={cancellationPhase.kind === "submitting"}
                    onClick={() => setCancellationPhase((phase) => keepBooking(phase))}
                    className="min-h-11 font-medium text-teal-700 underline disabled:opacity-60">
                    Keep booking
                  </button>
                </div>
              </div>
            ) : (
              <button type="button" disabled={cancellationPhase.kind === "submitting"}
                onClick={() => { setCancellationNotice(null); setCancellationPhase((phase) => requestCancellation(phase, booking.reservation_id, booking.status)); }}
                className="ml-5 mt-4 min-h-11 font-medium text-red-700 underline disabled:opacity-60">
                Cancel booking
              </button>
            )
          )}
        </li>
      ))}
    </ul>
    </>
  );
}
