import type { Metadata } from "next";
import BookingConfirmationExperience from "./booking-confirmation-experience";

export const metadata: Metadata = {
  title: "Booking confirmation | LikeHome",
};

export default async function BookingConfirmationPage({ params }: {
  params: Promise<{ reservationId: string }>;
}) {
  const { reservationId } = await params;
  return (
    <section className="mx-auto w-full max-w-4xl px-4 py-10 sm:px-6 sm:py-14">
      <p className="text-sm font-semibold text-teal-700">Your reservation</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950 sm:text-4xl">Booking confirmation</h1>
      <BookingConfirmationExperience reservationId={reservationId} />
    </section>
  );
}
