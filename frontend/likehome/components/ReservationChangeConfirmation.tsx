"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";
import { ApiError } from "@/lib/api";
import type { ReservationChangeConfirmRequest, ReservationChangeQuoteResponse, ReservationChangeReceiptResponse } from "@/lib/api-types";
import { confirmReservationChange } from "@/lib/bookings";

export type ReservationChangeConfirmationProps = {
  reservationId: number;
  reviewedQuote: Readonly<ReservationChangeQuoteResponse>;
  acceptedRequest: Readonly<ReservationChangeConfirmRequest>;
  /** Optional read-only reload of authoritative booking/financial information. */
  onRefreshCurrent?: (reservationId: number) => Promise<void>;
};

type Review = Readonly<{
  reservationId: number; expiresAt: string; hotel: string; adults: number; children: number;
  nights: number; reservationTotal: number; request: Readonly<ReservationChangeConfirmRequest>;
}>;
type ConfirmationState =
  | { kind: "idle" | "unauthorized" }
  | { kind: "pending" | "uncertain"; review: Review }
  | { kind: "rejected"; review: Review; message: string }
  | { kind: "success"; review: Review; receipt: ReservationChangeReceiptResponse };

function captureReview({ reservationId, reviewedQuote: review, acceptedRequest: request }: ReservationChangeConfirmationProps): Review | null {
  const quote = review?.quote;
  const fields = ["check_in_date", "check_out_date", "quote_id", "accept_quote", "price_per_night", "accepted_payment_amount"];
  if (!review || !quote || !request || !Number.isSafeInteger(reservationId) || reservationId <= 0 ||
      review.reservation_id !== reservationId || Object.keys(request).length !== fields.length ||
      !fields.every((field) => Object.prototype.hasOwnProperty.call(request, field)) || request.accept_quote !== true ||
      typeof review.quote_id !== "string" || !review.quote_id.trim() || request.quote_id !== review.quote_id ||
      request.check_in_date !== quote.check_in_date || request.check_out_date !== quote.check_out_date ||
      request.price_per_night !== quote.current_price_per_night || request.accepted_payment_amount !== quote.likehome_payment_amount ||
      ![request.price_per_night, request.accepted_payment_amount, quote.likehome_reservation_total].every((value) => Number.isFinite(value) && value > 0) ||
      quote.currency !== "USD" || typeof quote.hotel_name !== "string" || !quote.hotel_name.trim() ||
      !Number.isInteger(quote.adults) || quote.adults < 1 || !Number.isInteger(quote.children) || quote.children < 0 ||
      !Number.isFinite(Date.parse(review.expires_at))) return null;
  // Copy primitive accepted values exactly. Never round prices, trim the signed
  // quote ID, mutate the caller's object, or derive new amounts for a retry.
  return Object.freeze({ reservationId, expiresAt: review.expires_at, hotel: quote.hotel_name,
    adults: quote.adults, children: quote.children, nights: quote.number_of_nights, reservationTotal: quote.likehome_reservation_total,
    request: Object.freeze({ check_in_date: request.check_in_date, check_out_date: request.check_out_date,
      quote_id: request.quote_id, accept_quote: request.accept_quote, price_per_night: request.price_per_night,
      accepted_payment_amount: request.accepted_payment_amount }) });
}

function sameReview(first: Review | null, second: Review | null): boolean {
  return JSON.stringify(first) === JSON.stringify(second);
}

function ReviewedQuote({ review }: { review: Review }) {
  return <dl className="mt-4 grid min-w-0 gap-3 text-sm sm:grid-cols-2">
    {[
      ["Reservation ID", review.reservationId], ["Hotel", review.hotel],
      ["Proposed check-in", review.request.check_in_date], ["Proposed check-out", review.request.check_out_date],
      ["Number of nights", review.nights], ["Adults", review.adults], ["Children", review.children],
      ["Accepted nightly price", `${review.request.price_per_night} USD`],
      ["Proposed reservation total (before tax)", `${review.reservationTotal} USD`],
      ["Accepted payment obligation (including tax)", `${review.request.accepted_payment_amount} USD`],
    ].map(([label, value]) => <div key={label} className="min-w-0">
      <dt className="font-medium text-slate-900">{label}</dt><dd className="mt-1 break-words tabular-nums text-slate-700">{value}</dd>
    </div>)}
    <div className="min-w-0"><dt className="font-medium text-slate-900">Quote expires</dt>
      <dd className="mt-1 break-words text-slate-700"><time dateTime={review.expiresAt}>
        {new Date(review.expiresAt).toLocaleString("en-US", { timeZoneName: "short" })}
      </time></dd>
    </div>
  </dl>;
}

function QuoteAcceptance({ review, onConfirm }: { review: Review; onConfirm: (review: Review) => void }) {
  const [accepted, setAccepted] = useState(false);
  const [expired, setExpired] = useState(() => Date.parse(review.expiresAt) <= Date.now());
  const acceptance = useRef(false);
  const active = useRef(false);

  useEffect(() => {
    active.current = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    function checkExpiration() {
      clearTimeout(timer);
      const remaining = Date.parse(review.expiresAt) - Date.now();
      if (remaining <= 0) {
        acceptance.current = false; setAccepted(false); setExpired(true);
      } else timer = setTimeout(checkExpiration, Math.min(remaining, 2147483647));
    }
    checkExpiration();
    window.addEventListener("focus", checkExpiration);
    document.addEventListener("visibilitychange", checkExpiration);
    return () => {
      active.current = false; acceptance.current = false; clearTimeout(timer);
      window.removeEventListener("focus", checkExpiration);
      document.removeEventListener("visibilitychange", checkExpiration);
    };
  }, [review]);

  if (expired) return <p role="status" className="mt-4 text-sm font-medium text-amber-900">
    This quote has expired. Request a fresh quote before accepting a new confirmation.
  </p>;
  return <div className="mt-4 border-t border-slate-200 pt-4">
    <p className="text-sm text-slate-700">Confirming changes your reservation to these reviewed dates and prices. Any additional internal charge is tracked separately.</p>
    <label className="mt-3 flex min-h-11 items-start gap-3 text-sm text-slate-900">
      <input type="checkbox" name="accept_quote" checked={accepted} className="mt-1 h-5 w-5 shrink-0"
        onChange={(event) => {
          if (!active.current) return;
          acceptance.current = event.target.checked; setAccepted(event.target.checked);
        }} />
      <span>I understand the new dates and reviewed price, and I authorize this change to my reservation.</span>
    </label>
    <button type="button" disabled={!accepted} onClick={() => {
      if (!active.current || !acceptance.current) return;
      if (Date.parse(review.expiresAt) <= Date.now()) {
        acceptance.current = false; setAccepted(false); setExpired(true); return;
      }
      acceptance.current = false;
      onConfirm(review);
    }} className="mt-3 min-h-11 max-w-full rounded-md bg-teal-700 px-4 py-2 font-medium text-white hover:bg-teal-800 disabled:opacity-60">
      Confirm reservation change
    </button>
  </div>;
}

function ConfirmationReceipt({ receipt }: { receipt: ReservationChangeReceiptResponse }) {
  return <div className="mt-5 min-w-0 rounded-md border border-teal-200 bg-teal-50 p-3">
    <h5 role="status" className="font-semibold text-teal-950">Reservation change confirmed.</h5>
    <p className="mt-2 text-sm text-slate-700">This is the historical confirmation receipt. Current settlement status must be read separately from the financial summary.</p>
    <dl className="mt-3 grid min-w-0 gap-3 text-sm sm:grid-cols-2">
      {[
        ["Change ID", receipt.change_id], ["Confirmed reservation ID", receipt.reservation_id], ["Confirmed revision", receipt.revision],
        ["Confirmed check-in", receipt.check_in_date], ["Confirmed check-out", receipt.check_out_date],
        ["Confirmed reservation total (before tax)", `${receipt.reservation_total} USD`],
        ["Confirmed payment obligation (including tax)", `${receipt.payment_obligation} USD`],
        ["Previous payment obligation", `${receipt.previous_payment_obligation} USD`],
        ["Payment difference at confirmation", `${receipt.payment_difference} USD`],
        ["Booking payment status at confirmation", receipt.booking_payment_status],
      ].map(([label, value]) => <div key={label} className="min-w-0">
        <dt className="font-medium text-slate-900">{label}</dt><dd className="mt-1 break-words tabular-nums text-slate-700">{value}</dd>
      </div>)}
    </dl>
    {receipt.adjustment ? <div className="mt-4 break-words text-sm text-slate-700">
      <p className="font-medium">{receipt.adjustment.kind === "charge" ? "At confirmation: pending additional internal charge" : "At confirmation: recorded internal credit"}</p>
      <p className="mt-1 tabular-nums">{receipt.adjustment.amount} USD</p>
      <p className="mt-2">{receipt.adjustment.kind === "credit" ? "This internal credit is not an external cash refund." : "Any required additional internal charge is tracked separately. No separate payment was submitted here."}</p>
    </div> : <p className="mt-4 text-sm text-slate-700">No adjustment was recorded at confirmation.</p>}
  </div>;
}

function ConfirmationReview(props: ReservationChangeConfirmationProps) {
  const router = useRouter();
  const { invalidateSession } = useAuth();
  const incoming = captureReview(props);
  const [review, setReview] = useState(() => ({ value: incoming, version: 0 }));
  const [confirmation, setConfirmation] = useState<ConfirmationState>({ kind: "idle" });
  const [currentRead, setCurrentRead] = useState<"loading" | "success" | "error" | null>(null);
  const active = useRef(false);
  const generation = useRef(0);
  const pending = useRef(false);
  const refreshPending = useRef(false);
  const stage = useRef<ConfirmationState["kind"]>("idle");
  const submitted = useRef<Review | null>(null);

  // Before submission, replacing any reviewed value remounts only acceptance.
  // A submitted/uncertain request stays frozen even if a new quote arrives.
  if (confirmation.kind === "idle" && !sameReview(review.value, incoming)) {
    setReview({ value: incoming, version: review.version + 1 });
  }
  useEffect(() => {
    active.current = true;
    return () => { active.current = false; generation.current += 1; submitted.current = null; };
  }, []);

  function transition(next: ConfirmationState) {
    stage.current = next.kind; setConfirmation(next);
  }

  function unauthorized() {
    submitted.current = null; transition({ kind: "unauthorized" });
    invalidateSession(); router.replace("/login");
  }

  async function refreshCurrent(snapshot: Review) {
    if (!props.onRefreshCurrent || !active.current || pending.current || refreshPending.current ||
        !["success", "uncertain", "rejected"].includes(stage.current)) return;
    refreshPending.current = true;
    const requestGeneration = generation.current;
    setCurrentRead("loading");
    try {
      await props.onRefreshCurrent(snapshot.reservationId);
      if (active.current && generation.current === requestGeneration) setCurrentRead("success");
    } catch (error: unknown) {
      if (!active.current || generation.current !== requestGeneration) return;
      if (error instanceof ApiError && error.status === 401) { unauthorized(); return; }
      setCurrentRead("error");
    } finally {
      if (active.current && generation.current === requestGeneration) refreshPending.current = false;
    }
  }

  async function send(snapshot: Review, retry = false) {
    if (!active.current || pending.current || refreshPending.current ||
        (retry ? stage.current !== "uncertain" || submitted.current !== snapshot
          : stage.current !== "idle" || snapshot !== review.value || Date.parse(snapshot.expiresAt) <= Date.now())) return;
    pending.current = true; submitted.current = snapshot;
    const requestGeneration = ++generation.current;
    transition({ kind: "pending", review: snapshot }); setCurrentRead(null);
    try {
      const receipt = await confirmReservationChange(snapshot.reservationId, snapshot.request);
      if (!active.current || generation.current !== requestGeneration) return;
      submitted.current = null;
      transition({ kind: "success", review: snapshot, receipt });
      pending.current = false;
      await refreshCurrent(snapshot);
    } catch (error: unknown) {
      if (!active.current || generation.current !== requestGeneration) return;
      if (error instanceof ApiError && error.status === 401) { unauthorized(); return; }
      if (error instanceof ApiError && [400, 404, 409, 422].includes(error.status)) {
        const message = error.status === 404 ? "This booking is unavailable or cannot be accessed with your account."
          : error.status === 409 ? "The reviewed quote or reservation state may conflict. Check current booking information before requesting a fresh review."
            : "This change cannot be accepted as reviewed. Check the booking information and request a fresh review.";
        submitted.current = null; transition({ kind: "rejected", review: snapshot, message });
      } else {
        // A lost or malformed response can follow a commit. Only an explicit
        // retry may replay this exact request, even after quote/stay expiry.
        transition({ kind: "uncertain", review: snapshot });
      }
    } finally {
      if (active.current && generation.current === requestGeneration) pending.current = false;
    }
  }

  if (confirmation.kind === "unauthorized") return null;
  const displayed = "review" in confirmation ? confirmation.review : review.value;
  return <section aria-label="Reservation change confirmation" className="mt-3 min-w-0 rounded-lg border border-slate-200 bg-slate-50 p-3 sm:p-4">
    <h4 className="font-semibold text-slate-950">Review confirmation</h4>
    {displayed && <ReviewedQuote review={displayed} />}
    {confirmation.kind === "idle" && review.value && review.version > 0 && <p role="status" className="mt-4 text-sm text-slate-700">
      The reviewed quote changed. Review these values and accept again.
    </p>}
    {confirmation.kind === "idle" && (review.value ?
      <QuoteAcceptance key={review.version} review={review.value} onConfirm={(snapshot) => { void send(snapshot); }} /> :
      <p role="alert" className="mt-4 text-sm text-red-800">The reviewed quote and accepted request do not match. Request a fresh review.</p>)}
    {confirmation.kind === "pending" && <p role="status" className="mt-4 text-sm font-medium text-slate-700">Confirming reservation change…</p>}
    {confirmation.kind === "success" && <ConfirmationReceipt receipt={confirmation.receipt} />}
    {confirmation.kind === "uncertain" && <div role="alert" className="mt-4 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">
      <h5 className="font-semibold">Confirmation status uncertain</h5>
      <p className="mt-2">Your reservation may already have changed. We could not verify whether this request completed.</p>
      <p className="mt-2">Checking current information does not establish whether this exact request committed. An identical retry uses the same accepted request shown here.</p>
      <button type="button" disabled={currentRead === "loading"} onClick={() => {
        const snapshot = submitted.current;
        if (snapshot) void send(snapshot, true);
      }} className="mt-3 min-h-11 font-medium underline disabled:opacity-60">Retry identical confirmation</button>
    </div>}
    {confirmation.kind === "rejected" && <div className="mt-4 text-sm text-red-800">
      <p role="alert">{confirmation.message}</p>
      {incoming && !sameReview(incoming, confirmation.review) && <button type="button" disabled={currentRead === "loading"} onClick={() => {
        if (!active.current || refreshPending.current || stage.current !== "rejected") return;
        setReview({ value: incoming, version: review.version + 1 }); setCurrentRead(null); transition({ kind: "idle" });
      }} className="mt-2 min-h-11 font-medium text-teal-700 underline disabled:opacity-60">Review updated quote</button>}
    </div>}
    {props.onRefreshCurrent && displayed && ["success", "uncertain", "rejected"].includes(confirmation.kind) && <div className="mt-4 text-sm text-slate-700">
      {currentRead === "loading" && <p role="status">Reloading current booking and financial information…</p>}
      {currentRead === "error" && <p role="alert">Current booking or financial information could not be reloaded. {confirmation.kind === "success" ? "Your confirmed receipt is preserved." : confirmation.kind === "uncertain" ? "The confirmation status remains unresolved." : "You can check the current information again."}</p>}
      {currentRead === "success" && <p role="status">Current booking and financial information reloaded. {confirmation.kind === "uncertain" && "This does not establish whether this exact request committed."}</p>}
      <button type="button" disabled={currentRead === "loading"} onClick={() => { void refreshCurrent(displayed); }}
        className="mt-2 min-h-11 font-medium text-teal-700 underline disabled:opacity-60">
        {currentRead === "error" ? "Retry current booking refresh" : "Check current booking information"}
      </button>
    </div>}
  </section>;
}

export default function ReservationChangeConfirmation(props: ReservationChangeConfirmationProps) {
  const { status } = useAuth();
  if (status !== "authenticated") return null;
  return <ConfirmationReview key={props.reservationId} {...props} />;
}
