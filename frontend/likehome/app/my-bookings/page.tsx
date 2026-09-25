import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "My bookings | LikeHome",
};

export default function MyBookingsPage() {
  return (
    <section className="mx-auto w-full max-w-7xl px-4 py-10 sm:px-6 sm:py-14 lg:px-8">
      <p className="text-sm font-semibold text-teal-700">Your account</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950 sm:text-4xl">
        My bookings
      </h1>

      <div className="mt-8 border-y border-slate-200 py-10">
        <h2 className="text-xl font-semibold text-slate-950">Your stays will show up here</h2>
        <p className="mt-2 max-w-xl text-sm leading-6 text-slate-600">
          Booking history is not connected yet. When it is, you can review upcoming and past stays here.
        </p>
        <Link
          href="/search"
          className="mt-5 inline-flex min-h-11 items-center justify-center rounded-md bg-teal-700 px-4 font-medium text-white transition-colors hover:bg-teal-800"
        >
          Find a stay
        </Link>
      </div>
    </section>
  );
}