"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";
import { ApiError } from "@/lib/api";
import type { HotelRevalidationResponse } from "@/lib/api-types";
import { paymentHref } from "@/lib/payment";
import { createBookingSubmissionGuard, revalidateHotel, submitAcceptedQuote } from "@/lib/checkout";
import type { CheckoutSelection } from "@/lib/checkout-selection";
import { checkoutPriceBreakdown } from "@/lib/checkout-pricing";
import { normalizedGuestInformation, validateGuestInformation, type GuestInformation, type GuestInformationErrors } from "@/lib/guest-information";

type Phase = "loading" | "ready" | "unavailable" | "provider-error" | "error" |
  "submitting" | "conflict" | "booking-error" | "success";

const dollars = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

export default function CheckoutExperience({ selection }: { selection: CheckoutSelection | null }) {
  const router = useRouter();
  const { status: sessionStatus, invalidateSession } = useAuth();
  const [phase, setPhase] = useState<Phase>("loading");
  const [quote, setQuote] = useState<HotelRevalidationResponse | null>(null);
  const [notice, setNotice] = useState("");
  const [bookingError, setBookingError] = useState("");
  const [guest, setGuest] = useState<GuestInformation>({ guest_full_name: "", guest_email: "" });
  const [guestErrors, setGuestErrors] = useState<GuestInformationErrors>({});
  const initialRequest = useRef<{ key: string; promise: Promise<HotelRevalidationResponse> } | null>(null);
  const submissionGuard = useRef(createBookingSubmissionGuard());
  const refreshing = useRef(false);

  const handleQuoteFailure = useCallback((error: unknown) => {
    setQuote(null);
    if (error instanceof ApiError && error.status === 401) {
      invalidateSession();
      router.replace("/login");
      return;
    }
    if (error instanceof ApiError && error.status === 409) {
      setPhase("unavailable");
    } else if (error instanceof ApiError && [500, 502, 504].includes(error.status)) {
      setPhase("provider-error");
    } else {
      setPhase("error");
    }
  }, [invalidateSession, router]);

  useEffect(() => {
    if (sessionStatus === "unauthenticated") {
      const returnTo = `${window.location.pathname}${window.location.search}`;
      router.replace(`/login?next=${encodeURIComponent(returnTo)}`);
      return;
    }
    if (sessionStatus !== "authenticated" || !selection) return;

    let active = true;
    const key = JSON.stringify(selection);
    if (!initialRequest.current || initialRequest.current.key !== key) {
      initialRequest.current = { key, promise: revalidateHotel(selection) };
    }
    const request = initialRequest.current.promise;
    request.then((current) => {
      if (!active) return;
      setQuote(current);
      setPhase("ready");
    }).catch((error: unknown) => {
      if (!active) return;
      handleQuoteFailure(error);
    });
    return () => { active = false; };
  }, [sessionStatus, selection, router, handleQuoteFailure]);

  async function refreshQuote() {
    if (!selection || refreshing.current) return;
    refreshing.current = true;
    setQuote(null);
    setPhase("loading");
    try {
      const current = await revalidateHotel(selection);
      setQuote(current);
      setNotice("");
      setPhase("ready");
    } catch (error: unknown) {
      handleQuoteFailure(error);
    } finally {
      refreshing.current = false;
    }
  }

  async function confirmBooking() {
    if (!selection || !quote || phase !== "ready") return;
    const errors = validateGuestInformation(guest);
    setGuestErrors(errors);
    if (Object.keys(errors).length > 0 || !submissionGuard.current.tryStart()) return;
    setBookingError("");
    setPhase("submitting");
    let hadQuoteConflict = false;
    try {
      const result = await submitAcceptedQuote(selection, quote, normalizedGuestInformation(guest), () => {
        hadQuoteConflict = true;
        setQuote(null);
        setNotice("");
        setPhase("conflict");
      });
      if (result.kind === "created") {
        setPhase("success");
        router.replace(paymentHref(result.booking.payment_id));
      } else {
        setQuote(result.quote);
        setNotice("The quote changed while you were confirming. Review this current quote and confirm again.");
        setPhase("ready");
      }
    } catch (error: unknown) {
      if (error instanceof ApiError && error.status === 401) {
        invalidateSession();
        router.replace("/login");
      } else if (hadQuoteConflict) {
        handleQuoteFailure(error);
      } else {
        setBookingError(error instanceof ApiError && error.status === 400
          ? "You already have a booking that overlaps these dates. Review your bookings before trying again."
          : "We could not create the booking. No booking success was confirmed. Please try again.");
        setPhase("booking-error");
      }
    } finally {
      submissionGuard.current.finish();
    }
  }

  if (sessionStatus === "restoring") {
    return <p role="status" className="mt-8 text-slate-700">Checking your session…</p>;
  }
  if (sessionStatus === "unauthenticated") {
    return <p role="status" className="mt-8 text-slate-700">Taking you to sign in…</p>;
  }
  if (!selection) {
    return <div className="mt-8 rounded-lg border border-amber-200 bg-amber-50 p-5 text-amber-950">
      <p>Choose a stay from search to continue checkout.</p>
      <Link href="/search" className="mt-3 inline-block font-medium text-teal-700 underline">Return to search</Link>
    </div>;
  }
  if (phase === "loading" || phase === "conflict") {
    return <p role="status" className="mt-8 text-slate-700">
      {phase === "conflict" ? "The quote changed. Checking the current rate…" : "Checking the current rate…"}
    </p>;
  }
  if (phase === "unavailable") {
    return <div role="alert" className="mt-8 rounded-lg border border-amber-200 bg-amber-50 p-5 text-amber-950">
      <p>This stay is no longer available at a usable rate. Please search again.</p>
      <Link href="/search" className="mt-3 inline-block font-medium text-teal-700 underline">Return to search</Link>
    </div>;
  }
  if (phase === "provider-error" || phase === "error") {
    return <div role="alert" className="mt-8 rounded-lg border border-red-200 bg-red-50 p-5 text-red-900">
      <p>{phase === "provider-error"
        ? "The hotel rate service is unavailable right now. Please try again later."
        : "We could not load a valid quote for this stay. Please try again or search again."}</p>
      <button type="button" onClick={() => void refreshQuote()} className="mt-3 min-h-11 font-medium text-teal-700 underline">Retry quote</button>
      <Link href="/search" className="ml-5 inline-block font-medium text-teal-700 underline">Return to search</Link>
    </div>;
  }
  if (phase === "success") {
    return <p role="status" className="mt-8 text-slate-700">Opening payment review…</p>;
  }
  if (!quote) return null;
  const priceBreakdown = checkoutPriceBreakdown(quote);

  return <div className="mt-8 space-y-6">
    <div className="grid gap-4 rounded-lg border border-slate-200 bg-white p-5 sm:grid-cols-2 sm:p-6">
      <h2 className="text-xl font-semibold text-slate-950 sm:col-span-2">Primary guest details</h2>
      <div>
        <label htmlFor="guest-full-name" className="block text-sm font-medium text-slate-800">Full name</label>
        <input id="guest-full-name" name="guest_full_name" type="text" autoComplete="name" required maxLength={100}
          value={guest.guest_full_name} onChange={(event) => { setGuest((current) => ({ ...current, guest_full_name: event.target.value })); setGuestErrors((current) => ({ ...current, guest_full_name: undefined })); }}
          aria-invalid={Boolean(guestErrors.guest_full_name)} aria-describedby={guestErrors.guest_full_name ? "guest-full-name-error" : undefined}
          className="mt-2 min-h-11 w-full rounded-md border border-slate-300 px-3 text-slate-950" />
        {guestErrors.guest_full_name && <p id="guest-full-name-error" className="mt-1 text-sm text-red-700">{guestErrors.guest_full_name}</p>}
      </div>
      <div>
        <label htmlFor="guest-email" className="block text-sm font-medium text-slate-800">Email address</label>
        <input id="guest-email" name="guest_email" type="email" autoComplete="email" required maxLength={100}
          value={guest.guest_email} onChange={(event) => { setGuest((current) => ({ ...current, guest_email: event.target.value })); setGuestErrors((current) => ({ ...current, guest_email: undefined })); }}
          aria-invalid={Boolean(guestErrors.guest_email)} aria-describedby={guestErrors.guest_email ? "guest-email-error" : undefined}
          className="mt-2 min-h-11 w-full rounded-md border border-slate-300 px-3 text-slate-950" />
        {guestErrors.guest_email && <p id="guest-email-error" className="mt-1 text-sm text-red-700">{guestErrors.guest_email}</p>}
      </div>
    </div>
    {quote.price_changed === true && <p role="alert" className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-amber-950">
      The current price has changed since your search. Review the updated quote below.
    </p>}
    {notice && <p role="alert" className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-amber-950">{notice}</p>}
    <div className="rounded-lg border border-slate-200 bg-white p-5 sm:p-6">
      <h2 className="text-xl font-semibold text-slate-950">{quote.hotel_name}</h2>
      <p className="mt-2 text-sm text-slate-700">Lowest eligible provider rate for this property and stay</p>
      <dl className="mt-6 grid gap-4 text-sm text-slate-700 sm:grid-cols-2">
        <div><dt className="font-medium text-slate-950">Check-in</dt><dd>{quote.check_in_date}</dd></div>
        <div><dt className="font-medium text-slate-950">Check-out</dt><dd>{quote.check_out_date}</dd></div>
        <div><dt className="font-medium text-slate-950">Nights</dt><dd>{quote.number_of_nights}</dd></div>
        <div><dt className="font-medium text-slate-950">Guests</dt><dd>{quote.adults} adults, {quote.children} children</dd></div>
        <div><dt className="font-medium text-slate-950">Provider listing</dt><dd>{quote.source}</dd></div>
        <div><dt className="font-medium text-slate-950">Guest capacity</dt><dd>{quote.guest_capacity}</dd></div>
        <div><dt className="font-medium text-slate-950">Current base nightly average</dt><dd>{dollars.format(quote.current_price_per_night)}</dd></div>
        {quote.provider_total_with_taxes_fees !== null && <div><dt className="font-medium text-slate-950">Provider listed stay total (reference)</dt><dd>{dollars.format(quote.provider_total_with_taxes_fees)}</dd></div>}
        <div><dt className="font-medium text-slate-950">Stay subtotal</dt><dd>{dollars.format(priceBreakdown.baseStayTotal)}</dd></div>
        <div><dt className="font-medium text-slate-950">LikeHome service fee</dt><dd>{dollars.format(priceBreakdown.serviceFee)}</dd></div>
        <div><dt className="font-medium text-slate-950">LikeHome total with service fee</dt><dd>{dollars.format(quote.likehome_reservation_total)}</dd></div>
        <div><dt className="font-medium text-slate-950">Tax</dt><dd>{dollars.format(priceBreakdown.tax)}</dd></div>
        <div className="border-t border-slate-200 pt-4 sm:col-span-2"><dt className="font-semibold text-slate-950">Final booking total</dt><dd className="text-lg font-semibold text-slate-950">{dollars.format(priceBreakdown.finalTotal)} USD</dd></div>
      </dl>
      <p className="mt-5 text-sm text-slate-600">Creating your reservation records a pending LikeHome payment. You will review its persisted amount before completing the internal demo payment step. No card is charged.</p>
    </div>
    {phase === "booking-error" && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-900">{bookingError}</p>}
    <button type="button" disabled={phase === "submitting" || phase === "booking-error"}
      onClick={() => void confirmBooking()}
      className="min-h-12 rounded-md bg-teal-700 px-6 font-semibold text-white hover:bg-teal-800 disabled:cursor-wait disabled:opacity-60">
      {phase === "submitting" ? "Creating booking…" : "Reserve and continue to payment"}
    </button>
    {phase === "booking-error" && <button type="button" onClick={() => void refreshQuote()} className="ml-4 min-h-11 font-medium text-teal-700 underline">Refresh quote</button>}
  </div>;
}
