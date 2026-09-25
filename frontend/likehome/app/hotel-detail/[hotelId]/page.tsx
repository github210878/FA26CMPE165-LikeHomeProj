import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Stay details | LikeHome",
};

export default async function HotelDetailPage({
  params,
}: PageProps<"/hotel-detail/[hotelId]">) {
  const { hotelId } = await params;

  return (
    <section className="mx-auto w-full max-w-7xl px-4 py-10 sm:px-6 sm:py-14 lg:px-8">
      <p className="text-sm font-semibold text-teal-700">Stay details</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950 sm:text-4xl">
        Property {hotelId}
      </h1>

      <div className="mt-8 grid gap-8 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div>
          <div className="flex aspect-[16/8] items-center justify-center rounded-lg border border-slate-200 bg-slate-100 text-sm text-slate-500">
            Property photos will appear here
          </div>
          <div className="mt-8 border-b border-slate-200 pb-6">
            <h2 className="text-xl font-semibold text-slate-950">About this stay</h2>
            <p className="mt-2 text-sm leading-6 text-slate-600">
              Property information and amenities will appear here.
            </p>
          </div>
          <div className="mt-6">
            <h2 className="text-xl font-semibold text-slate-950">Location</h2>
            <p className="mt-2 text-sm leading-6 text-slate-600">Address and map details will appear here.</p>
          </div>
        </div>

        <aside className="h-fit rounded-lg border border-slate-200 bg-white p-5">
          <h2 className="text-lg font-semibold text-slate-950">Your stay</h2>
          <p className="mt-2 text-sm text-slate-600">Pricing and availability will appear here.</p>
          <Link
            href="/checkout"
            className="mt-5 inline-flex min-h-11 w-full items-center justify-center rounded-md bg-teal-700 px-4 font-medium text-white transition-colors hover:bg-teal-800"
          >
            Continue to checkout
          </Link>
        </aside>
      </div>
    </section>
  );
}