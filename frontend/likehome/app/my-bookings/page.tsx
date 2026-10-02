import type { Metadata } from "next";
import MyBookingsExperience from "@/components/MyBookingsExperience";

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

      <MyBookingsExperience />
    </section>
  );
}
