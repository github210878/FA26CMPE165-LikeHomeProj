import { ApiError } from "./api.ts";
import type { BookingListItem } from "./api-types.ts";

export type CancellationPhase =
  | { kind: "idle" }
  | { kind: "confirming"; reservationId: number }
  | { kind: "submitting"; reservationId: number };

export function canCancelBooking(status: BookingListItem["status"]): boolean {
  return status === "confirmed";
}

export function requestCancellation(
  phase: CancellationPhase,
  reservationId: number,
  status: BookingListItem["status"],
): CancellationPhase {
  return phase.kind === "submitting" || !canCancelBooking(status)
    ? phase
    : { kind: "confirming", reservationId };
}

export function keepBooking(phase: CancellationPhase): CancellationPhase {
  return phase.kind === "submitting" ? phase : { kind: "idle" };
}

export function startCancellation(phase: CancellationPhase, reservationId: number): CancellationPhase {
  return phase.kind === "confirming" && phase.reservationId === reservationId
    ? { kind: "submitting", reservationId }
    : phase;
}

export function createCancellationSubmissionGuard() {
  let activeReservationId: number | null = null;
  return {
    tryStart(reservationId: number): boolean {
      if (activeReservationId !== null) return false;
      activeReservationId = reservationId;
      return true;
    },
    finish(): void {
      activeReservationId = null;
    },
  };
}

export function cancellationErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) return "This booking could not be found or is no longer available.";
    if (error.status === 409) return "This booking can no longer be cancelled.";
  }
  return "We couldn't cancel this booking right now. Please try again.";
}
