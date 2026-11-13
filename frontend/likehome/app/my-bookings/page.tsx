import type { Metadata } from "next";
import Link from "next/link";
import MyBookingsExperience from "@/components/MyBookingsExperience";

export const metadata: Metadata = {
  title: "My bookings | LikeHome",
};

export default function MyBookingsPage() {
  return (
    <section className="mx-auto w-full max-w-7xl px-4 py-10 sm:px-6 sm:py-14 lg:px-8">
      <h1 className="text-sm font-semibold text-teal-700">Your account</h1>
      <div className="flex justify-between">
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950 sm:text-4xl">
          My Bookings
        </h1>
        <Link href="/rewardPage" className="bg-teal-700 hover:bg-teal-800 text-white text-center font-semibold py-3 px-4 rounded-full">
          My Reward Points
        </Link>
      </div>
      <MyBookingsExperience />
    </section>
  );
}
