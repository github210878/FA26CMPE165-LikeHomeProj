"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import type { PaymentResponse } from "@/lib/api-types";

type PaymentFormProps = {
  payment: PaymentResponse;
  submitting: boolean;
  paymentError: string;
  onSubmit: () => void;
  onRefresh: () => void;
};

export default function PaymentForm({
  payment,
  submitting,
  paymentError,
  onSubmit,
  onRefresh,
}: PaymentFormProps) {
  const [confirmed, setConfirmed] = useState(false);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!confirmed || submitting || paymentError) return;
    onSubmit();
  }

  if (payment.payment_status === "paid") {
    return (
      <div className="mt-6 space-y-4">
        <p role="status" className="rounded-md border border-emerald-200 bg-emerald-50 p-4 text-emerald-900">
          Payment recorded successfully.
        </p>
        <Link
          href={`/booking-confirmation/${payment.reservation_id}`}
          className="inline-flex min-h-11 items-center rounded-md bg-teal-700 px-5 font-semibold text-white hover:bg-teal-800"
        >
          View confirmation
        </Link>
      </div>
    );
  }

  if (payment.payment_status !== "pending") {
    return <p role="status" className="mt-6 text-slate-700">This payment cannot be completed.</p>;
  }

  return (
    <form onSubmit={handleSubmit} className="mt-6 space-y-5">
      <fieldset className="space-y-3">
        <legend className="text-sm font-semibold text-slate-950">Payment method</legend>
        <label className="flex min-h-12 items-center gap-3 rounded-md border border-teal-700 bg-teal-50 px-4 text-sm font-medium text-slate-900">
          <input type="radio" name="payment-method" value="demo" checked readOnly />
          LikeHome demo payment
        </label>
        <p className="text-sm leading-6 text-slate-600">
          This project records an internal demo payment. No card details are collected and no card or bank is charged.
        </p>
      </fieldset>

      <label className="flex items-start gap-3 text-sm leading-6 text-slate-700">
        <input
          type="checkbox"
          checked={confirmed}
          disabled={submitting || Boolean(paymentError)}
          onChange={(event) => setConfirmed(event.target.checked)}
          className="mt-1 size-4 accent-teal-700"
        />
        <span>I understand this is a demo payment and confirm the amount shown above.</span>
      </label>

      {paymentError && (
        <div role="alert" className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-900">
          <p>{paymentError}</p>
          <button type="button" onClick={onRefresh} className="mt-3 min-h-11 font-medium text-teal-700 underline">
            Refresh payment status
          </button>
        </div>
      )}

      {submitting && (
        <p role="status" aria-live="polite" className="text-sm font-medium text-teal-800">
          Recording payment. Please wait…
        </p>
      )}

      <button
        type="submit"
        disabled={!confirmed || submitting || Boolean(paymentError)}
        className="min-h-11 rounded-md bg-teal-700 px-5 font-semibold text-white hover:bg-teal-800 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {submitting ? "Recording payment…" : "Confirm demo payment"}
      </button>
    </form>
  );
}