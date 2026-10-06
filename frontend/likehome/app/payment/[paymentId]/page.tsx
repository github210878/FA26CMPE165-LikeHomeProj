import type { Metadata } from "next";
import PaymentExperience from "./payment-experience";

export const metadata: Metadata = { title: "Payment review | LikeHome" };

export default async function PaymentPage({ params }: { params: Promise<{ paymentId: string }> }) {
  const { paymentId } = await params;
  return <section className="mx-auto w-full max-w-4xl px-4 py-10 sm:px-6 sm:py-14">
    <p className="text-sm font-semibold text-teal-700">Payment</p>
    <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950 sm:text-4xl">Review your payment</h1>
    <PaymentExperience key={paymentId} paymentId={paymentId} />
  </section>;
}
