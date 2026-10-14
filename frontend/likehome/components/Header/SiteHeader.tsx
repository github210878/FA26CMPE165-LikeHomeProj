import Link from "next/link";
import { HiOutlineBars3, HiOutlineHomeModern, HiOutlineXMark } from "react-icons/hi2";
import type { HeaderLink } from "@/constants/constant";

type Props = {
  links: readonly HeaderLink[];
  status: "restoring" | "authenticated" | "unauthenticated";
  signingOut: boolean;
  showHead: boolean;
  openHead: () => void;
  signOut: () => void;
};

export default function SiteHeader({ links, status, signingOut, showHead, openHead, signOut }: Props) {
  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="site-container flex min-h-16 items-center justify-between gap-6">
        <Link href="/" className="brand" aria-label="LikeHome home">
          <span className="brand-mark"><HiOutlineHomeModern aria-hidden="true" className="h-5 w-5" /></span>
          LikeHome<span className="-ml-2 text-teal-600">.</span>
        </Link>
        <nav aria-label="Primary navigation" className="hidden items-center gap-8 lg:flex">
          <Link href="/#destinations" className="inline-flex min-h-11 items-center text-sm font-semibold text-slate-950 hover:text-teal-700">Destinations</Link>
          {links.map((link) => (
            <Link href={link.url} key={link.id} className={link.url === "/signup" ? "primary-button !min-h-11 !px-5" : "inline-flex min-h-11 items-center text-sm font-semibold text-slate-950 transition-colors hover:text-teal-700"}>
              {link.label}
            </Link>
          ))}
          {status === "authenticated" && (
            <>
              <span className="rounded-full bg-teal-50 px-3 py-1.5 text-xs text-teal-800">Signed in</span>
              <button type="button" onClick={signOut} disabled={signingOut} className="min-h-11 text-sm font-semibold text-slate-950 hover:text-teal-700 disabled:opacity-60">{signingOut ? "Signing out…" : "Log out"}</button>
            </>
          )}
          {status === "restoring" && <span className="text-sm text-slate-600">Checking session…</span>}
        </nav>
        <button type="button" onClick={openHead} aria-label={showHead ? "Close navigation menu" : "Open navigation menu"} aria-expanded={showHead} aria-controls="mobile-navigation" className="flex h-11 w-11 items-center justify-center rounded-xl border border-slate-200 text-slate-900 lg:hidden">
          {showHead ? <HiOutlineXMark aria-hidden="true" className="h-6 w-6" /> : <HiOutlineBars3 aria-hidden="true" className="h-6 w-6" />}
        </button>
      </div>
    </header>
  );
}
