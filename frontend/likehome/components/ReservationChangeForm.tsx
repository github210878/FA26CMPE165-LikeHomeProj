"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";
import { ApiError } from "@/lib/api";
import type { ReservationChangeQuoteResponse } from "@/lib/api-types";
import { getReservationChangeQuote } from "@/lib/bookings";

type Props = { reservationId: number; checkInDate: string; checkOutDate: string; onQuoteReady?: (quote: ReservationChangeQuoteResponse | null) => void; };
type Fields = { check_in_date: string; check_out_date: string; q: string; adults: string; children: string };
type ReviewState =
  | { kind: "idle" | "loading" | "expired" | "unauthorized" }
  | { kind: "error"; message: string; retryable: boolean }
  | { kind: "success"; review: ReservationChangeQuoteResponse };

const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const invalidQuoteMessage = "We could not get a valid, current price quote. Please request a fresh quote.";

// Initialize dates only when the booking supplies a real calendar date. Submission
// rules, including whether dates are upcoming, remain in the existing adapter.
function initialDate(value: string): string {
  const candidate = value.slice(0, 10);
  const date = new Date(`${candidate}T00:00:00Z`);
  return candidate.length === 10 && Number.isFinite(date.getTime()) &&
    date.toISOString().slice(0, 10) === candidate ? candidate : "";
}

function quoteError(error: unknown): { kind: "error"; message: string; retryable: boolean } {
  if (error instanceof ApiError) {
    const messages: Record<number, string> = {
      400: "These dates may overlap another booking, or this change is not allowed. Review your request.",
      404: "This booking is unavailable or cannot be accessed with your account.",
      409: "This booking has changed or cannot support this request. Review its current details before trying again.",
      422: "Check your dates, destination, and whole-number guest counts, then request a quote again.",
      502: "The hotel provider is unavailable. Please try requesting a quote again.",
      504: "The hotel provider took too long to respond. Please try requesting a quote again.",
    };
    return { kind: "error", message: messages[error.status] ?? "We could not request a price quote. Please try again.",
      retryable: ![400, 404, 409, 422].includes(error.status) };
  }
  if (error instanceof Error && error.message === "Invalid reservation change review") {
    return { kind: "error", message: "Check your dates, destination, and whole-number guest counts, then request a quote again.", retryable: false };
  }
  return { kind: "error", message: invalidQuoteMessage, retryable: true };
}

function ChangeReview({ reservationId, checkInDate, checkOutDate, onQuoteReady }: Props) {
  const router = useRouter();
  const { invalidateSession } = useAuth();
  const [fields, setFields] = useState<Fields>(() => ({
    check_in_date: initialDate(checkInDate), check_out_date: initialDate(checkOutDate),
    q: "", adults: "", children: "",
  }));
  const [state, setState] = useState<ReviewState>({ kind: "idle" });
  const active = useRef(false);
  const pending = useRef(false);
  const generation = useRef(0);
  const onQuoteReadyRef = useRef(onQuoteReady);

  useEffect(() => {
    onQuoteReadyRef.current = onQuoteReady;
  }, [onQuoteReady]);

  useEffect(() => {
    active.current = true;
    return () => { active.current = false; generation.current += 1; pending.current = false; };
  }, []);

  useEffect(() => {
    if (state.kind !== "success") return;
    const review = state.review;
    let timer: ReturnType<typeof setTimeout> | undefined;

    function checkExpiration() {
      clearTimeout(timer);

      const remaining = Date.parse(review.expires_at) - Date.now();

      if (remaining <= 0) {
        setState((current) =>
            current.kind === "success" && current.review === review
                ? { kind: "expired" }
                : current
        );

        onQuoteReadyRef.current?.(null);
      } else {
        timer = setTimeout(
            checkExpiration,
            Math.min(remaining, 2147483647)
        );
      }
    }
    checkExpiration();
    window.addEventListener("focus", checkExpiration);
    document.addEventListener("visibilitychange", checkExpiration);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("focus", checkExpiration);
      document.removeEventListener("visibilitychange", checkExpiration);
    };
  }, [state]);
  function edit(field: keyof Fields, value: string) {
    if (pending.current) return;
    setFields((current) => ({ ...current, [field]: value }));
    setState({ kind: "idle" });
    onQuoteReady?.(null);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!active.current || pending.current) return;
    pending.current = true;
    const requestGeneration = ++generation.current;
    setState({ kind: "loading" });
    onQuoteReady?.(null);
    try {
      const review = await getReservationChangeQuote(reservationId, {
        check_in_date: fields.check_in_date, check_out_date: fields.check_out_date, q: fields.q,
        adults: fields.adults.trim() ? Number(fields.adults) : NaN,
        children: fields.children.trim() ? Number(fields.children) : NaN,
        currency: "USD", gl: "us", hl: "en",
      });
      if (!active.current || generation.current !== requestGeneration) return;
      const expiration = Date.parse(review.expires_at);
      const valid = Number.isFinite(expiration) && expiration > Date.now();
      setState(valid
          ? { kind: "success", review }
          : { kind: "error", message: invalidQuoteMessage, retryable: true });

      onQuoteReady?.(valid ? review : null);
    } catch (error: unknown) {
      if (!active.current || generation.current !== requestGeneration) return;
      if (error instanceof ApiError && error.status === 401) {
        setState({ kind: "unauthorized" });
        invalidateSession();
        router.replace("/login");
        return;
      }
      setState(quoteError(error));
    } finally {
      if (active.current && generation.current === requestGeneration) pending.current = false;
    }
  }

  const loading = state.kind === "loading";
  const expired = state.kind === "expired";
  const review = state.kind === "success" && !expired ? state.review : null;
  const helpId = `change-review-help-${reservationId}`;
  const errorId = `change-review-error-${reservationId}`;
  const inputClass = "mt-1 min-h-11 w-full min-w-0 max-w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-slate-950 disabled:bg-slate-100";

  if (state.kind === "unauthorized") return <p role="status" className="mt-3 text-sm text-slate-600">Redirecting to sign in…</p>;
  return (
    <section id={`reservation-change-${reservationId}`} aria-label="Review a reservation change"
      className="mt-3 min-w-0 rounded-lg border border-slate-200 bg-slate-50 p-3 sm:p-4">
      <h4 className="font-semibold text-slate-950">Request a change quote</h4>
      <p id={helpId} className="mt-2 break-words text-sm text-slate-700">
        Reconfirm your destination and both guest counts. Requesting a quote does not change your booking.
        Eligibility and availability will be checked when you request a quote.
      </p>
      <form noValidate aria-label="Reservation change quote" aria-busy={loading}
        aria-describedby={`${helpId}${state.kind === "error" ? ` ${errorId}` : ""}`}
        onSubmit={(event) => void submit(event)} className="mt-4 min-w-0">
        <fieldset disabled={loading} className="grid min-w-0 gap-4 sm:grid-cols-2">
          <legend className="sr-only">Proposed stay and reconfirmed guests</legend>
          <label className="min-w-0 text-sm font-medium text-slate-900">New check-in date
            <input type="date" name="check_in_date" required value={fields.check_in_date}
              onChange={(event) => edit("check_in_date", event.target.value)} className={inputClass} />
          </label>
          <label className="min-w-0 text-sm font-medium text-slate-900">New check-out date
            <input type="date" name="check_out_date" required value={fields.check_out_date}
              onChange={(event) => edit("check_out_date", event.target.value)} className={inputClass} />
          </label>
          <label className="min-w-0 text-sm font-medium text-slate-900 sm:col-span-2">Reconfirmed destination
            <input type="text" name="q" required value={fields.q} autoComplete="off"
              onChange={(event) => edit("q", event.target.value)} className={inputClass} />
          </label>
          <label className="min-w-0 text-sm font-medium text-slate-900">Number of adults
            <input type="number" name="adults" required min={1} max={20} step={1} value={fields.adults}
              onChange={(event) => edit("adults", event.target.value)} className={inputClass} />
          </label>
          <label className="min-w-0 text-sm font-medium text-slate-900">Number of children
            <input type="number" name="children" required min={0} max={20} step={1} value={fields.children}
              onChange={(event) => edit("children", event.target.value)} className={inputClass} />
          </label>
        </fieldset>
        {loading && <p role="status" className="mt-3 text-sm text-slate-700">Requesting price quote…</p>}
        {state.kind === "error" && <p id={errorId} role="alert" className="mt-3 break-words text-sm text-red-800">{state.message}</p>}
        {expired && <p role="status" className="mt-3 text-sm font-medium text-amber-900">This quote has expired. Request a fresh quote to review current prices.</p>}
        <button type="submit" disabled={loading}
          className="mt-4 min-h-11 max-w-full rounded-md bg-teal-700 px-4 py-2 font-medium text-white hover:bg-teal-800 disabled:cursor-wait disabled:opacity-60">
          {loading ? "Requesting quote…" : expired || review ? "Request a fresh quote" : state.kind === "error" && state.retryable ? "Retry quote" : "Request a quote"}
        </button>
      </form>
      {review && (
        <div className="mt-5 min-w-0 border-t border-slate-200 pt-4">
          <h5 className="font-semibold text-slate-950">Price quote (USD)</h5>
          <p role="status" className="mt-3 rounded-md border border-teal-200 bg-teal-50 p-3 font-semibold text-teal-950">
            This is a price quote only. Your reservation has not been changed.
          </p>
          <dl className="mt-4 grid min-w-0 gap-3 text-sm sm:grid-cols-2">
            {[
              ["Hotel", review.quote.hotel_name], ["Proposed check-in", review.quote.check_in_date],
              ["Proposed check-out", review.quote.check_out_date], ["Number of nights", review.quote.number_of_nights],
              ["Adults", review.quote.adults], ["Children", review.quote.children],
              ["Current nightly price", usd.format(review.quote.current_price_per_night)],
              ["Proposed reservation total (before tax)", usd.format(review.quote.likehome_reservation_total)],
              ["LikeHome payment amount (including tax)", usd.format(review.quote.likehome_payment_amount)],
            ].map(([label, value]) => <div key={label} className="min-w-0">
              <dt className="font-medium text-slate-900">{label}</dt>
              <dd className="mt-1 break-words tabular-nums text-slate-700">{value}</dd>
            </div>)}
            <div className="min-w-0"><dt className="font-medium text-slate-900">Quote expires</dt>
              <dd className="mt-1 break-words text-slate-700"><time dateTime={review.expires_at}>
                {new Date(review.expires_at).toLocaleString("en-US", { timeZoneName: "short" })}
              </time></dd>
            </div>
          </dl>
        </div>
      )}
    </section>
  );
}

export default function ReservationChangeForm(props: Props) {
  const { status } = useAuth();
  if (status !== "authenticated") return null;
  return <ChangeReview key={props.reservationId} {...props} />;
}
