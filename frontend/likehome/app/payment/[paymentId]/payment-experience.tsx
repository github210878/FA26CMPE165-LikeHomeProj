"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";
import { ApiError } from "@/lib/api";
import type { PaymentResponse } from "@/lib/api-types";
import { parseReservationId } from "@/lib/booking-confirmation";
import { getPaymentDetails, payBookingPayment } from "@/lib/bookings";
import { createBookingSubmissionGuard } from "@/lib/checkout";

type DetailState =
  | { kind: "loading" }
  | { kind: "ready"; payment: PaymentResponse }
  | { kind: "not-found" }
  | { kind: "error" };

const dollars = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

export default function PaymentExperience({ paymentId }: { paymentId: string }) {
  const router = useRouter();
  const { status, invalidateSession } = useAuth();
  const id = parseReservationId(paymentId);
  const [detail, setDetail] = useState<DetailState>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [paymentError, setPaymentError] = useState("");
  const guard = useRef(createBookingSubmissionGuard());

  useEffect(() => {
    if (status === "unauthenticated") {
      router.replace("/login");
      return;
    }
    if (status !== "authenticated" || id === null) return;
    let active = true;
    getPaymentDetails(id).then((payment) => {
      if (!active) return;
      setDetail(payment && payment.payment_type === "booking"
        ? { kind: "ready", payment } : { kind: "not-found" });
    }).catch((error: unknown) => {
      if (!active) return;
      if (error instanceof ApiError && error.status === 401) {
        invalidateSession();
        router.replace("/login");
      } else {
        setDetail(error instanceof ApiError && error.status === 404 ? { kind: "not-found" } : { kind: "error" });
      }
    });
    return () => { active = false; };
  }, [status, id, attempt, invalidateSession, router]);

  async function submitPayment(payment: PaymentResponse) {
    if (!guard.current.tryStart()) return;
    setSubmitting(true);
    setPaymentError("");
    try {
      const paid = await payBookingPayment(payment.payment_id);
      if (paid.reservation_id !== payment.reservation_id || paid.amount !== payment.amount) {
        throw new Error("Payment result did not match the reviewed payment");
      }
      setDetail({ kind: "ready", payment: paid });
      router.replace(`/booking-confirmation/${paid.reservation_id}`);
    } catch (error: unknown) {
      if (error instanceof ApiError && error.status === 401) {
        invalidateSession();
        router.replace("/login");
      } else {
        setPaymentError(error instanceof ApiError && error.status === 409
          ? "This payment can no longer be completed. Refresh its status or review My Bookings."
          : "Payment was not confirmed. Your reservation still exists. Refresh its status before retrying this same payment.");
      }
    } finally {
      setSubmitting(false);
      guard.current.finish();
    }
  }

  if (status !== "authenticated") return <p role="status" className="mt-8 text-slate-700">Checking your session…</p>;
  if (id === null || detail.kind === "not-found") return <p role="alert" className="mt-8 text-slate-800">This payment could not be found.</p>;
  if (detail.kind === "loading") return <p role="status" className="mt-8 text-slate-700">Loading payment…</p>;
  if (detail.kind === "error") return <div role="alert" className="mt-8 rounded-lg border border-red-200 bg-red-50 p-5 text-red-900">
    <p>We could not load this payment. Your reservation may still be available.</p>
    <button type="button" onClick={() => { setDetail({ kind: "loading" }); setAttempt((value) => value + 1); }} className="mt-3 font-medium text-teal-700 underline">Retry</button>
  </div>;

  const payment = detail.payment;
  return <div className="mt-8 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
    <dl className="grid gap-4 text-sm text-slate-700 sm:grid-cols-2">
      <div><dt className="font-medium text-slate-950">Reservation ID</dt><dd>{payment.reservation_id}</dd></div>
      <div><dt className="font-medium text-slate-950">Payment ID</dt><dd>{payment.payment_id}</dd></div>
      <div><dt className="font-medium text-slate-950">LikeHome payment status</dt><dd className="capitalize">{payment.payment_status}</dd></div>
      <div><dt className="font-medium text-slate-950">Booking payment amount</dt><dd className="text-lg font-semibold text-slate-950">{dollars.format(payment.amount)}</dd></div>
    </dl>
    <p className="mt-5 text-sm text-slate-600">This is an internal LikeHome demo payment. Completing it records payment in LikeHome; no card or bank is charged.</p>
    {paymentError && <p role="alert" className="mt-5 rounded-lg border border-red-200 bg-red-50 p-4 text-red-900">{paymentError}</p>}
    {payment.payment_status === "pending" && <div className="mt-5 flex flex-wrap gap-4">
      <button type="button" disabled={submitting || Boolean(paymentError)} onClick={() => void submitPayment(payment)}
        className="min-h-11 rounded-md bg-teal-700 px-5 font-semibold text-white hover:bg-teal-800 disabled:cursor-wait disabled:opacity-60">
        {submitting ? "Recording payment…" : "Complete LikeHome payment"}
      </button>
      {paymentError && <button type="button" onClick={() => { setPaymentError(""); setDetail({ kind: "loading" }); setAttempt((value) => value + 1); }} className="min-h-11 font-medium text-teal-700 underline">Refresh payment status</button>}
    </div>}
    {payment.payment_status === "paid" && <Link href={`/booking-confirmation/${payment.reservation_id}`} className="mt-5 inline-flex min-h-11 items-center rounded-md bg-teal-700 px-5 font-semibold text-white hover:bg-teal-800">View confirmation</Link>}
    {(payment.payment_status === "failed" || payment.payment_status === "refunded") && <p className="mt-5 text-slate-700">This payment cannot be completed.</p>}
    <Link href="/my-bookings" className="mt-5 block font-medium text-teal-700 underline">View My Bookings</Link>
  </div>;
}
