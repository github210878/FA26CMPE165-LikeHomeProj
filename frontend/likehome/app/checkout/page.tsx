import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Checkout | LikeHome",
};

export default function CheckoutPage() {
  return (
    <section className="mx-auto w-full max-w-7xl px-4 py-10 sm:px-6 sm:py-14 lg:px-8">
      <p className="text-sm font-semibold text-teal-700">Checkout</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950 sm:text-4xl">
        Complete your booking
      </h1>

      <div className="mt-8 grid gap-8 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <form className="grid gap-6">
          <fieldset className="grid gap-4 rounded-lg border border-slate-200 bg-white p-5 sm:grid-cols-2 sm:p-6">
            <legend className="px-2 text-lg font-semibold text-slate-950">Guest details</legend>
            <label className="grid gap-2 text-sm font-medium text-slate-800">
              Full name
              <input type="text" name="fullName" autoComplete="name" className="min-h-11 rounded-md border border-slate-300 px-3 font-normal" />
            </label>
            <label className="grid gap-2 text-sm font-medium text-slate-800">
              Email address
              <input type="email" name="email" autoComplete="email" className="min-h-11 rounded-md border border-slate-300 px-3 font-normal" />
            </label>
          </fieldset>

          <fieldset className="grid gap-4 rounded-lg border border-slate-200 bg-white p-5 sm:grid-cols-2 sm:p-6">
            <legend className="px-2 text-lg font-semibold text-slate-950">Payment</legend>
            <p className="text-sm leading-6 text-slate-600 sm:col-span-2">
              Secure payment options will be available here.
            </p>
          </fieldset>

          <button type="button" disabled className="min-h-11 rounded-md bg-slate-300 px-5 font-medium text-slate-600">
            Booking confirmation coming soon
          </button>
        </form>

        <aside className="h-fit rounded-lg border border-slate-200 bg-white p-5">
          <h2 className="text-lg font-semibold text-slate-950">Reservation summary</h2>
          <p className="mt-2 text-sm leading-6 text-slate-600">
            Stay dates, guest count, and price breakdown will appear here.
          </p>
        </aside>
      </div>
    </section>
  );
}