"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";
import { loginErrorMessage } from "@/lib/auth";

export default function LoginForm({ returnTo }: { returnTo?: string | null }) {
  const router = useRouter();
  const { status, signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting || status !== "unauthenticated") return;

    setSubmitting(true);
    setError("");
    try {
      await signIn({ email: email.trim(), password });
      setPassword("");
      router.replace(returnTo ?? "/");
    } catch (failure) {
      setPassword("");
      setError(loginErrorMessage(failure));
    } finally {
      setSubmitting(false);
    }
  }

  if (status === "restoring") {
    return <p role="status" className="mt-8 text-sm text-slate-600">Checking your session…</p>;
  }

  if (status === "authenticated") {
    return <p className="mt-8 text-sm text-slate-700">You are signed in. <Link href={returnTo ?? "/"} className="font-medium text-teal-700 underline">Continue</Link>.</p>;
  }

  return (
    <form onSubmit={handleSubmit} className="mt-8 space-y-5">
      <div>
        <label htmlFor="login-email" className="block text-sm font-medium text-slate-900">Email address</label>
        <input id="login-email" name="email" type="email" autoComplete="email" required disabled={submitting} value={email}
          onChange={(event) => { setEmail(event.target.value); setError(""); }}
          className="mt-2 min-h-11 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-base text-slate-950" />
      </div>
      <div>
        <label htmlFor="login-password" className="block text-sm font-medium text-slate-900">Password</label>
        <input id="login-password" name="password" type="password" autoComplete="current-password" required disabled={submitting} value={password}
          onChange={(event) => { setPassword(event.target.value); setError(""); }}
          className="mt-2 min-h-11 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-base text-slate-950" />
      </div>
      <button type="submit" disabled={submitting}
        className="min-h-12 w-full rounded-lg bg-teal-700 px-4 py-3 text-sm font-semibold text-white hover:bg-teal-800 disabled:cursor-not-allowed disabled:opacity-60">
        {submitting ? "Signing in…" : "Sign in"}
      </button>
      {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">{error}</p>}
      <p className="text-sm text-slate-600">Don&apos;t have an account? <Link href="/signup" className="font-medium text-teal-700 underline">Sign up</Link></p>
    </form>
  );
}
