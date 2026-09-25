import type { Metadata } from "next";
import SignupForm from "@/components/SignupForm";

export const metadata: Metadata = {
  title: "Sign up | LikeHome",
};

export default function SignupPage() {
  return (
    <section className="mx-auto w-full max-w-lg px-4 py-10 sm:px-6 sm:py-16">
      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
        <h1 className="text-3xl font-semibold tracking-tight text-slate-950">Sign up for LikeHome</h1>
        <p className="mt-3 text-base leading-7 text-slate-600">A place to start your next stay. Enter your details below.</p>
        <SignupForm />
      </div>
    </section>
  );
}
