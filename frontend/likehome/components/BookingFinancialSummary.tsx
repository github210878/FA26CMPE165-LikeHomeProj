"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";
import { ApiError } from "@/lib/api";
import type { AdjustmentDetailResponse, ReservationFinancialSummary } from "@/lib/api-types";
import { getReservationFinancialSummary } from "@/lib/bookings";

type SummaryState = { reservationId: number } & (
  | { kind: "loading" | "unavailable" | "error" | "unauthorized" }
  | { kind: "success"; summary: ReservationFinancialSummary }
);

const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

function Amount({ label, amount, status }: { label: string; amount: number; status?: string }) {
  return (
    <div className="min-w-0">
      <dt className="font-medium text-slate-900">{label}</dt>
      <dd className="mt-1 break-words tabular-nums text-slate-700">
        {usd.format(amount)}{status && <> · <span className="capitalize">{status}</span></>}
      </dd>
    </div>
  );
}

function History({ entries, reconciliation = false }: { entries: AdjustmentDetailResponse[]; reconciliation?: boolean }) {
  return (
    <ul className="mt-3 min-w-0 space-y-2 text-sm">
      {entries.map((entry) => (
        <li key={entry.adjustment_id} className="min-w-0 rounded-md border border-slate-200 bg-white p-3">
          <p className="break-words font-medium text-slate-900">
            {reconciliation ? `Reconciliation ${entry.kind}` : entry.kind === "credit" ? "Internal credit" : "Additional charge"}
            {" · "}<span className="capitalize">{entry.status}</span>
          </p>
          <p className="mt-1 break-words tabular-nums text-slate-700">{usd.format(entry.amount)}</p>
        </li>
      ))}
    </ul>
  );
}

function SummaryContent({ summary }: { summary: ReservationFinancialSummary }) {
  const categories = [
    ["Paid additional charges", summary.paid_additional_charges],
    ["Pending additional charges", summary.pending_additional_charges],
    ["Failed additional charges", summary.failed_additional_charges],
    ["Voided additional charges", summary.voided_additional_charges],
    ["Recorded internal credits", summary.recorded_internal_credits],
    ["Outstanding additional amount", summary.outstanding_additional_amount],
  ] as const;

  return (
    <>
      <dl className="mt-3 grid min-w-0 gap-3 text-sm sm:grid-cols-2">
        <Amount label="Current reservation total (before tax)" amount={summary.current_reservation_total} />
        <Amount label="Current booking obligation (including tax)" amount={summary.current_booking_obligation} />
        <Amount label="Original booking payment" amount={summary.original_booking_payment.amount}
          status={summary.original_booking_payment.payment_status} />
        {summary.outstanding_booking_amount > 0 &&
          <Amount label="Outstanding original booking amount" amount={summary.outstanding_booking_amount} />}
      </dl>
      <p className="mt-3 text-xs text-slate-500">Summary revision {summary.reservation_revision}</p>
      <p className="mt-3 text-sm text-slate-600">
        These are LikeHome internal demo records. No bank or payment processor charge or refund is made here.
      </p>

      {summary.adjustments.length === 0 ? (
        <p className="mt-4 text-sm text-slate-600">
          {summary.latest_change_id === null ? "No reservation changes have been recorded." : "No additional charges or credits were recorded."}
        </p>
      ) : (
        <div className="mt-5 min-w-0">
          <h5 className="font-semibold text-slate-950">Reservation adjustments</h5>
          <dl className="mt-3 grid min-w-0 gap-3 text-sm sm:grid-cols-2">
            {categories.filter(([, amount]) => amount > 0).map(([label, amount]) =>
              <Amount key={label} label={label} amount={amount} />)}
          </dl>
          <p className="mt-3 text-sm text-slate-600">
            Internal credits are recorded accounting entries, not cash refunds, spendable balances, or reward points.
            They are not deducted from the outstanding amounts shown here.
          </p>
          <h6 className="mt-4 text-sm font-semibold text-slate-900">Adjustment history</h6>
          <History entries={summary.adjustments} />
        </div>
      )}

      {summary.reservation_status === "cancelled" && (
        <div className="mt-5 min-w-0 border-t border-slate-200 pt-4">
          <h5 className="font-semibold text-slate-950">Cancellation accounting</h5>
          <dl className="mt-3 grid min-w-0 gap-3 text-sm sm:grid-cols-2">
            {summary.cancellation_payment && <Amount label="Separate cancellation payment" amount={summary.cancellation_payment.amount}
              status={summary.cancellation_payment.payment_status} />}
            {summary.outstanding_cancellation_amount > 0 &&
              <Amount label="Outstanding cancellation amount" amount={summary.outstanding_cancellation_amount} />}
            {summary.reconciliation_credits > 0 && <Amount label="Recorded reconciliation credits" amount={summary.reconciliation_credits} />}
            {summary.reconciliation_debits > 0 && <Amount label="Recorded reconciliation debits" amount={summary.reconciliation_debits} />}
          </dl>
          {!summary.cancellation_payment && <p className="mt-3 text-sm text-slate-600">No cancellation payment information is available.</p>}
          <p className="mt-3 text-sm text-slate-600">
            Reconciliation entries preserve and reverse historical accounting effects; they do not represent money paid or refunded.
          </p>
          {summary.cancellation_reconciliations.length > 0 ? (
            <>
              <h6 className="mt-4 text-sm font-semibold text-slate-900">Cancellation reconciliation history</h6>
              <History entries={summary.cancellation_reconciliations} reconciliation />
            </>
          ) : <p className="mt-3 text-sm text-slate-600">No cancellation reconciliation entries have been recorded.</p>}
        </div>
      )}
    </>
  );
}

export default function BookingFinancialSummary({ reservationId, readSummary = getReservationFinancialSummary }: {
  reservationId: number; readSummary?: typeof getReservationFinancialSummary;
}) {
  const router = useRouter();
  const { status, invalidateSession } = useAuth();
  const [state, setState] = useState<SummaryState>({ kind: "loading", reservationId });
  const [attempt, setAttempt] = useState(0);
  const retryPending = useRef(true);
  const reader = useRef(readSummary);

  useEffect(() => {
    if (status !== "authenticated") return;
    let active = true;
    retryPending.current = true;
    reader.current(reservationId).then((summary) => {
      if (!active) return;
      setState({ kind: "success", reservationId, summary });
    }).catch((error: unknown) => {
      if (!active) return;
      if (error instanceof ApiError && error.status === 401) {
        setState({ kind: "unauthorized", reservationId });
        invalidateSession();
        router.replace("/login");
        return;
      }
      setState({ kind: error instanceof ApiError && error.status === 404 ? "unavailable" : "error", reservationId });
    }).finally(() => { if (active) retryPending.current = false; });
    return () => { active = false; };
  }, [reservationId, attempt, status, invalidateSession, router]);

  if (status !== "authenticated") return null;
  const current = state.reservationId === reservationId ? state : { kind: "loading" as const };
  return (
    <section aria-label="Reservation financial summary" className="mt-5 min-w-0 rounded-lg border border-slate-200 bg-slate-50 p-3 sm:p-4">
      <h4 className="font-semibold text-slate-950">Financial summary <span className="text-sm font-normal text-slate-600">(USD)</span></h4>
      {current.kind === "loading" && <p role="status" className="mt-3 text-sm text-slate-600">Loading financial summary…</p>}
      {current.kind === "unauthorized" && <p role="status" className="mt-3 text-sm text-slate-600">Redirecting to sign in…</p>}
      {current.kind === "unavailable" && <p role="status" className="mt-3 text-sm text-slate-700">This financial summary is unavailable.</p>}
      {current.kind === "error" && (
        <div role="alert" className="mt-3 text-sm text-red-800">
          <p>We could not load this financial summary. Please try again.</p>
          <button type="button" className="mt-2 min-h-11 font-medium text-teal-700 underline"
            onClick={() => {
              if (retryPending.current) return;
              retryPending.current = true;
              setState({ kind: "loading", reservationId });
              setAttempt((previous) => previous + 1);
            }}>Retry financial summary</button>
        </div>
      )}
      {current.kind === "success" && <SummaryContent summary={current.summary} />}
    </section>
  );
}
