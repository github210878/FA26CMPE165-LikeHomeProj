import type { Metadata } from "next";
import { parseCheckoutSelection } from "@/lib/checkout-selection";
import CheckoutExperience from "./checkout-experience";

export const metadata: Metadata = {
  title: "Checkout | LikeHome",
};

export default async function CheckoutPage({ searchParams }: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const selection = parseCheckoutSelection(await searchParams);
  return (
    <section className="mx-auto w-full max-w-4xl px-4 py-10 sm:px-6 sm:py-14">
      <p className="text-sm font-semibold text-teal-700">Checkout</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950 sm:text-4xl">Review your booking</h1>
      <CheckoutExperience selection={selection} />
    </section>
  );
}
