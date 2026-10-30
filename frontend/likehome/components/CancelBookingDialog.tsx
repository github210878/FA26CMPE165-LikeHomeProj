import { useEffect, useRef, type ReactNode } from "react";
import type { BookingListItem } from "@/lib/api-types";

type Props = {
  booking: BookingListItem;
  submitting: boolean;
  onKeep: () => void;
  onConfirm: () => void;
  feePreview?: ReactNode;
};

export default function CancelBookingDialog({ booking, submitting, onKeep, onConfirm, feePreview }: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const keepRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const opener = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    dialog.showModal();
    keepRef.current?.focus();
    document.body.style.overflow = "hidden";
    return () => {
      dialog.close();
      document.body.style.overflow = previousOverflow;
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
    };
  }, []);

  const headingId = `cancel-booking-${booking.reservation_id}-title`;
  const descriptionId = `cancel-booking-${booking.reservation_id}-description`;

  return (
    <dialog ref={dialogRef} tabIndex={-1} aria-labelledby={headingId} aria-describedby={descriptionId}
      onCancel={(event) => { event.preventDefault(); if (!submitting) onKeep(); }}
      onKeyDown={(event) => {
        if (event.key !== "Tab") return;
        const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>(
          'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]',
        )).filter((element) => element.getClientRects().length > 0);
        const first = controls[0];
        const last = controls[controls.length - 1];
        if (!first) {
          event.preventDefault();
          event.currentTarget.focus();
        } else if (event.shiftKey && (document.activeElement === first || document.activeElement === event.currentTarget)) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && (document.activeElement === last || document.activeElement === event.currentTarget)) {
          event.preventDefault();
          first.focus();
        }
      }}
      className="fixed inset-0 m-auto max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-lg overflow-y-auto rounded-2xl border border-slate-200 bg-white p-6 text-slate-900 shadow-xl backdrop:bg-slate-950/50 sm:p-8">
      <h2 id={headingId} className="text-2xl font-semibold text-slate-950">Cancel this booking?</h2>
      <p id={descriptionId} className="mt-3 text-sm leading-6 text-slate-700">Please review your stay before cancelling. This action cannot be undone.</p>
      <div className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4">
        <p className="font-semibold text-slate-950">{booking.hotel_name}</p>
        <p className="mt-1 text-sm text-slate-700">{booking.room_type_name}</p>
        <dl className="mt-4 grid grid-cols-2 gap-4 text-sm">
          <div><dt className="text-slate-600">Check-in</dt><dd className="mt-1 font-medium"><time dateTime={booking.check_in_date}>{booking.check_in_date.slice(0, 10)}</time></dd></div>
          <div><dt className="text-slate-600">Check-out</dt><dd className="mt-1 font-medium"><time dateTime={booking.check_out_date}>{booking.check_out_date.slice(0, 10)}</time></dd></div>
          <div className="col-span-2"><dt className="text-slate-600">Reservation ID</dt><dd className="mt-1 font-medium">{booking.reservation_id}</dd></div>
        </dl>
      </div>
      <div className="mt-4 text-sm leading-6 text-slate-700">{feePreview ?? <p>Cancellation charges may apply. Cancelling does not confirm an external refund.</p>}</div>
      <p role="status" className="mt-4 text-sm text-slate-700">{submitting ? "Cancelling your booking. Please wait…" : "Your booking stays active unless you confirm cancellation."}</p>
      <div className="mt-6 flex flex-col gap-3 sm:flex-row">
        <button ref={keepRef} type="button" disabled={submitting} onClick={onKeep}
          className="min-h-12 flex-1 rounded-xl border border-teal-700 px-4 font-semibold text-teal-800 hover:bg-teal-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700 disabled:cursor-wait disabled:opacity-60">Keep booking</button>
        <button type="button" disabled={submitting} onClick={onConfirm}
          className="min-h-12 flex-1 rounded-xl bg-red-700 px-4 font-semibold text-white hover:bg-red-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-700 disabled:cursor-wait disabled:opacity-60">{submitting ? "Cancelling…" : "Confirm cancellation"}</button>
      </div>
    </dialog>
  );
}
