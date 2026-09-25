import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Find a stay | LikeHome",
};

export default function SearchPage() {
  return (
    <section className="mx-auto w-full max-w-7xl px-4 py-10 sm:px-6 sm:py-14 lg:px-8">
      <div className="max-w-3xl">
        <p className="text-sm font-semibold text-teal-700">Find a stay</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950 sm:text-4xl">
          Where would you like to stay?
        </h1>

        <form action="/search" method="get" className="mt-8 grid gap-4 rounded-xl border border-slate-200 bg-white p-5 sm:grid-cols-2 sm:p-6">
          <label className="grid gap-2 text-sm font-medium text-slate-800 sm:col-span-2">
            Destination
            <input
              type="search"
              name="destination"
              placeholder="City or neighborhood"
              className="min-h-11 rounded-md border border-slate-300 px-3 font-normal"
            />
          </label>
          <label className="grid gap-2 text-sm font-medium text-slate-800">
            Check-in
            <input type="date" name="checkIn" className="min-h-11 rounded-md border border-slate-300 px-3 font-normal" />
          </label>
          <label className="grid gap-2 text-sm font-medium text-slate-800">
            Check-out
            <input type="date" name="checkOut" className="min-h-11 rounded-md border border-slate-300 px-3 font-normal" />
          </label>
          <label className="grid gap-2 text-sm font-medium text-slate-800">
            Guests
            <input type="number" name="guests" min="1" defaultValue="1" className="min-h-11 rounded-md border border-slate-300 px-3 font-normal" />
          </label>
          <div className="flex items-end">
            <button type="submit" className="min-h-11 w-full rounded-md bg-teal-700 px-5 font-medium text-white transition-colors hover:bg-teal-800">
              Search stays
            </button>
          </div>
        </form>
      </div>

      <div className="mt-12 border-t border-slate-200 pt-8" aria-live="polite">
        <h2 className="text-xl font-semibold text-slate-950">Available stays</h2>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          Search results will appear here when listings are connected.
        </p>
      </div>
    </section>
  );
}