import Link from "next/link";
import type { RedemptionConfirmation } from "@/lib/redemption-confirmation";

const dollars = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const points = new Intl.NumberFormat("en-US");
const button = "inline-flex min-h-11 items-center rounded-md px-4 py-2 font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700";

export default function RedemptionConfirmationState({
  state, onRefresh,
}: {
  state: RedemptionConfirmation;
  onRefresh?: () => void;
}) {
  if (state.kind === "confirmed") {
    return (
      <div className="min-w-0 rounded-xl border border-teal-200 bg-white p-5 shadow-sm sm:p-8">
        <h2 className="text-xl font-semibold text-teal-950 sm:text-2xl">Reward redemption confirmed</h2>
        <p className="mt-2 break-words text-slate-700">{state.hotelName}</p>
        <dl className="mt-5 grid min-w-0 gap-4 text-sm text-slate-800 sm:grid-cols-2">
          <div><dt className="font-semibold">Booking reference</dt><dd className="break-words">{state.bookingReference}</dd></div>
          <div><dt className="font-semibold">Stay dates</dt><dd>
            <time dateTime={state.checkInDate}>{state.checkInDate.slice(0, 10)}</time>
            {" to "}
            <time dateTime={state.checkOutDate}>{state.checkOutDate.slice(0, 10)}</time>
          </dd></div>
          <div><dt className="font-semibold">Points redeemed</dt><dd>{points.format(state.pointsRedeemed)}</dd></div>
          <div><dt className="font-semibold">Points-funded value</dt><dd>{dollars.format(state.pointsFundedValueCents / 100)}</dd></div>
          <div><dt className="font-semibold">Remaining cash due</dt><dd>{dollars.format(state.remainingCashDueCents / 100)}</dd></div>
        </dl>
        <Link href="/my-bookings" className={`mt-5 ${button} bg-teal-700 text-white hover:bg-teal-800`}>View My Bookings</Link>
      </div>
    );
  }

  if (state.kind === "loading" || state.kind === "authentication-required") {
    return <p role="status" className="text-sm text-slate-700">
      {state.kind === "loading" ? "Checking redemption confirmation…" : "Sign in to check redemption confirmation."}
    </p>;
  }

  let title: string;
  let detail: string;
  switch (state.kind) {
    case "requested":
      title = "Reward redemption requested";
      detail = "Redemption has yet to be verified. Check your reservation before trying another payment.";
      break;
    case "unverified":
      title = "Redemption not yet verified";
      detail = "Your booking payment is recorded. The payment record does not identify how it was funded.";
      break;
    case "rejected":
      title = "Reward redemption declined";
      detail = state.reason === "insufficient_points"
        ? "You did not have enough points to cover this stay."
        : "This booking was ineligible for reward redemption.";
      break;
    case "unavailable":
      title = state.cancelled ? "Reservation cancelled" : "Reservation unavailable";
      detail = state.cancelled ? "Check My Bookings for the current reservation status." : "We could not find this reservation.";
      break;
    default:
      title = "Redemption status unavailable";
      detail = "We could not determine the outcome. Check the status before trying another payment.";
  }
  const alert = state.kind === "rejected" || state.kind === "unavailable" || state.kind === "uncertain";

  return (
    <div className={`min-w-0 rounded-lg border p-4 ${alert ? "border-amber-200 bg-amber-50 text-amber-950" : "border-slate-200 bg-slate-50 text-slate-800"}`}>
      <div role={alert ? "alert" : "status"}>
        <h2 className="font-semibold">{title}</h2>
        <p className="mt-1 break-words text-sm">{detail}</p>
      </div>
      {state.kind === "uncertain" && onRefresh &&
        <button type="button" onClick={onRefresh} className={`mt-2 ${button} text-teal-800 underline`}>
          Check status again
        </button>}
    </div>
  );
}
