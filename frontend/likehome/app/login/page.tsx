import type { Metadata } from "next";
import LoginForm from "@/components/LoginForm";
import { safeCheckoutReturnTo } from "@/lib/checkout-selection";

export const metadata: Metadata = {
  title: "Sign in | LikeHome",
};

export default async function LoginPage({ searchParams }: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const returnTo = safeCheckoutReturnTo((await searchParams).next);
  return (
    <section className="mx-auto w-full max-w-lg px-4 py-10 sm:px-6 sm:py-16">
      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
        <h1 className="text-3xl font-semibold tracking-tight text-slate-950">Sign in to LikeHome</h1>
        <p className="mt-3 text-base leading-7 text-slate-600">Welcome back. Enter your account details below.</p>
        <LoginForm returnTo={returnTo} />
      </div>
    </section>
  );
}
