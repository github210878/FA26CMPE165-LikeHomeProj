"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";
import { ApiError } from "@/lib/api";
import type { ReservationChangeReviewRequest, ReservationDateChangeResponse } from "@/lib/api-types";
import { changeReservationDates } from "@/lib/bookings";

type Props = {
  reservationId: number;
  checkInDate: string;
  checkOutDate: string;
  onDatesSaved?: (result: ReservationDateChangeResponse) => Promise<void>;
};

type SaveState =
  | { kind: "idle" | "loading" | "unauthorized" }
  | { kind: "error"; message: string }
  | { kind: "saved"; result: ReservationDateChangeResponse; refreshing: boolean; refreshFailed: boolean };

const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const conflictMessages: Record<string, string> = {
  dates_overlap: "These dates overlap with another reservation. Please select different dates.",
  booking_context_missing: "The original booking details are missing. This reservation cannot be changed online.",
  payment_unsupported: "Online date changes are available only for bookings with an unpaid, unadjusted payment.",
  price_increase: "The new dates cost more than your approved booking amount. Choose different dates.",
  reservation_not_confirmed: "This reservation is no longer eligible for a date change.",
  reservation_changed: "The reservation changed while we checked availability. Reload MyBookings and try again.",
};

function initialDate(value: string): string {
  const candidate = value.slice(0, 10);
  const date = new Date(`${candidate}T00:00:00Z`);
  return candidate.length === 10 && Number.isFinite(date.getTime()) &&
    date.toISOString().slice(0, 10) === candidate ? candidate : "";
}

function saveError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) return "This reservation is unavailable or you do not have access to it.";
    if (error.status === 409) {
      return (error.code && Object.hasOwn(conflictMessages, error.code) && conflictMessages[error.code])
        || "The hotel could not confirm availability for these dates. Choose different dates.";
    }
    if (error.status === 422) return "Enter valid check-in and check-out dates with check-out after check-in.";
    if ([502, 504].includes(error.status)) return "The hotel provider is unavailable. Please try again.";
  }
  if (error instanceof Error && error.message === "Invalid reservation change review") {
    return "Enter valid check-in and check-out dates with check-out after check-in.";
  }
  return "We could not confirm whether your dates were saved. Reload MyBookings to check before trying again.";
}

function DateChangeForm({ reservationId, checkInDate, checkOutDate, onDatesSaved }: Props) {
  const router = useRouter();
  const { invalidateSession } = useAuth();
  const [fields, setFields] = useState<ReservationChangeReviewRequest>(() => ({
    check_in_date: initialDate(checkInDate), check_out_date: initialDate(checkOutDate),
  }));
  const [state, setState] = useState<SaveState>({ kind: "idle" });
  const active = useRef(false);
  const pending = useRef(false);
  const generation = useRef(0);

  useEffect(() => {
    active.current = true;
    return () => { active.current = false; generation.current += 1; pending.current = false; };
  }, []);

  function edit(field: keyof ReservationChangeReviewRequest, value: string) {
    if (pending.current) return;
    setFields((current) => ({ ...current, [field]: value }));
    setState({ kind: "idle" });
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!active.current || pending.current) return;
    pending.current = true;
    const requestGeneration = ++generation.current;
    const isCurrent = () => active.current && generation.current === requestGeneration;
    setState({ kind: "loading" });
    try {
      const result = await changeReservationDates(reservationId, fields);
      if (!isCurrent()) return;
      setState({ kind: "saved", result, refreshing: !!onDatesSaved, refreshFailed: false });
      try {
        await onDatesSaved?.(result);
        if (isCurrent()) setState({ kind: "saved", result, refreshing: false, refreshFailed: false });
      } catch {
        if (isCurrent()) setState({ kind: "saved", result, refreshing: false, refreshFailed: true });
      }
    } catch (error: unknown) {
      if (!isCurrent()) return;
      if (error instanceof ApiError && error.status === 401) {
        setState({ kind: "unauthorized" });
        invalidateSession();
        router.replace("/login");
      } else {
        setState({ kind: "error", message: saveError(error) });
      }
    } finally {
      if (isCurrent()) pending.current = false;
    }
  }

  const loading = state.kind === "loading" || (state.kind === "saved" && state.refreshing);
  const helpId = `change-dates-help-${reservationId}`;
  const errorId = `change-dates-error-${reservationId}`;
  const inputClass = "mt-1 min-h-11 w-full min-w-0 max-w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-slate-950 disabled:bg-slate-100";

  if (state.kind === "unauthorized") return <p role="status" className="mt-3 text-sm text-slate-600">Redirecting to sign in…</p>;
  return (
    <section id={`reservation-change-${reservationId}`} aria-label="Change reservation dates"
      className="mt-3 min-w-0 rounded-lg border border-slate-200 bg-slate-50 p-3 sm:p-4">
      <h4 className="font-semibold text-slate-950">Change reservation dates</h4>
      <p id={helpId} className="mt-2 break-words text-sm text-slate-700">
        Choose new stay dates. We’ll check hotel availability and save if the price stays the same or goes down.
      </p>
      <form noValidate aria-label="Reservation date change" aria-busy={loading}
        aria-describedby={`${helpId}${state.kind === "error" ? ` ${errorId}` : ""}`}
        onSubmit={(event) => void submit(event)} className="mt-4 min-w-0">
        <fieldset disabled={loading} className="grid min-w-0 gap-4 sm:grid-cols-2">
          <legend className="sr-only">New stay dates</legend>
          <label className="min-w-0 text-sm font-medium text-slate-900">New check-in date
            <input type="date" name="check_in_date" required value={fields.check_in_date}
              onChange={(event) => edit("check_in_date", event.target.value)} className={inputClass} />
          </label>
          <label className="min-w-0 text-sm font-medium text-slate-900">New check-out date
            <input type="date" name="check_out_date" required value={fields.check_out_date}
              onChange={(event) => edit("check_out_date", event.target.value)} className={inputClass} />
          </label>
        </fieldset>
        {state.kind === "loading" && <p role="status" className="mt-3 text-sm text-slate-700">Checking availability…</p>}
        {state.kind === "error" && <p id={errorId} role="alert" className="mt-3 break-words text-sm text-red-800">{state.message}</p>}
        <button type="submit" disabled={loading}
          className="mt-4 min-h-11 max-w-full rounded-md bg-teal-700 px-4 py-2 font-medium text-white hover:bg-teal-800 disabled:cursor-wait disabled:opacity-60">
          {loading ? "Saving…" : "Save reservation changes"}
        </button>
      </form>
      {state.kind === "saved" && (
        <div role="status" className="mt-5 min-w-0 rounded-md border border-teal-200 bg-teal-50 p-3 text-teal-950">
          <p className="font-semibold">{state.result.changed ? "Reservation dates saved." : "These dates are already saved."}</p>
          <p className="mt-1 break-words">
            {state.result.booking_reference} · {state.result.check_in_date} to {state.result.check_out_date}
          </p>
          <p className="mt-1">Reservation total: {usd.format(state.result.total_price)}</p>
          <p>Pending payment: {usd.format(state.result.payment_amount)}</p>
          {state.refreshFailed && <p className="mt-1">Reload MyBookings to refresh your booking list.</p>}
        </div>
      )}
    </section>
  );
}

export default function ReservationChangeForm(props: Props) {
  const { status, user } = useAuth();
  if (status !== "authenticated") return null;
  return <DateChangeForm key={`${user?.user_id}:${props.reservationId}`} {...props} />;
}
