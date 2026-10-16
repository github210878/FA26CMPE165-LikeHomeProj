import type { ReactNode } from "react";
import Link from "next/link";
import Image from "next/image";
import { HiOutlineCalendarDays, HiOutlineMapPin, HiOutlineAdjustmentsHorizontal } from "react-icons/hi2";

export default function AccountLayout({ title, description, children, signup = false }: {
  title: string;
  description: string;
  children: ReactNode;
  signup?: boolean;
}) {
  return (
    <section className="auth-layout">
      {signup ? (
        <aside className="hidden overflow-hidden rounded-3xl bg-teal-50 md:grid md:grid-rows-[auto_minmax(50%,1fr)] md:self-stretch">
          <div className="relative px-6 py-5">
            <p className="eyebrow">A stay to look forward to</p>
            <h2 className="mt-3 text-3xl font-medium leading-tight tracking-tight text-slate-950">A little adventure.<br />A lot of comfort.</h2>
            <p className="mt-4 text-sm leading-6 text-slate-900">Create an account to keep your bookings together and make room for your next getaway.</p>
            <ul className="mt-4 space-y-3 text-slate-950">
              <li className="flex gap-3">
                <HiOutlineCalendarDays aria-hidden="true" className="mt-1 h-6 w-6 shrink-0 text-teal-900" />
                <div><h3 className="text-sm font-semibold">Your bookings, together</h3><p className="mt-1 text-sm leading-5">Keep track of your upcoming stays.</p></div>
              </li>
              <li className="flex gap-3">
                <HiOutlineAdjustmentsHorizontal aria-hidden="true" className="mt-1 h-6 w-6 shrink-0 text-teal-900" />
                <div><h3 className="text-sm font-semibold">Find your kind of stay</h3><p className="mt-1 text-sm leading-5">Compare prices and amenities.</p></div>
              </li>
              <li className="flex gap-3">
                <HiOutlineMapPin aria-hidden="true" className="mt-1 h-6 w-6 shrink-0 text-teal-900" />
                <div><h3 className="text-sm font-semibold">Somewhere new awaits</h3><p className="mt-1 text-sm leading-5">Explore destinations near and far.</p></div>
              </li>
            </ul>
          </div>
          <div className="relative min-h-[300px]">
            <Image src="/images/signup-greece.png" alt="Blue-domed churches and white buildings overlooking the sea in Santorini, Greece" fill sizes="(min-width: 768px) 45vw, 100vw" className="object-cover object-[center_55%]" />
          </div>
        </aside>
      ) : (
        <aside className="hidden overflow-hidden rounded-3xl bg-teal-50 md:block">
          <div className="px-8 py-6">
            <p className="eyebrow">Good to have you back</p>
            <h2 className="mt-3 text-4xl font-medium leading-tight tracking-tight text-slate-950">Familiar comforts.<br />New places.</h2>
            <p className="mt-3 text-sm leading-6 text-slate-900">Your next chapter is just a stay away. Revisit your bookings or find somewhere new to unwind.</p>
            <Link href="/search" className="mt-2 inline-flex min-h-11 items-center text-sm font-semibold text-teal-900 underline underline-offset-4">Find your next getaway →</Link>
          </div>
          <div className="relative h-[280px]">
            <Image src="/images/signin-seaview.jpg" alt="Two cushioned wooden lounge chairs on a sunny balcony overlooking the blue sea" fill sizes="(min-width: 768px) 45vw, 100vw" className="object-cover object-[center_65%]" />
          </div>
        </aside>
      )}
      <div className="auth-card">
        <p className="eyebrow">{signup ? "Make yourself at home" : "Your next stay awaits"}</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight text-slate-950">{title}</h1>
        <p className="mt-3 text-sm leading-7 text-slate-600">{description}</p>
        {children}
        <p className="mt-6 border-t border-slate-200 pt-6 text-center text-sm text-slate-600">{signup ? "Already have an account? " : "New to LikeHome? "}<Link href={signup ? "/login" : "/signup"} className="font-semibold text-teal-700 underline underline-offset-4">{signup ? "Sign in" : "Create an account"}</Link></p>
      </div>
    </section>
  );
}
