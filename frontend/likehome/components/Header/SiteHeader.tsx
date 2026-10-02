import Link from "next/link";
import { HiBars3BottomRight } from "react-icons/hi2";
import type { HeaderLink } from "@/constants/constant";

type Props = {
  links: readonly HeaderLink[];
  status: "restoring" | "authenticated" | "unauthenticated";
  signingOut: boolean;
  openHead: () => void;
  signOut: () => void;
};

export default function SiteHeader({ links, status, signingOut, openHead, signOut }: Props) {
  return (
    <header className="flex border-b border-slate-200 bg-white">
      <div className="mx-auto flex h-full w-[90%] items-center justify-between xl:w-[80%]">
        <Link href="/" className="inline-flex min-h-16 shrink-0 items-center rounded-sm px-2 text-xl font-semibold tracking-tight text-slate-950">
          LikeHome
        </Link>
        <nav aria-label="Primary navigation" className="hidden items-center space-x-10 lg:flex">
          {links.map((link) => (
            <Link href={link.url} key={link.id} className="font-semibold text-black transition-colors hover:text-teal-600">
              {link.label}
            </Link>
          ))}
          {status === "authenticated" && (
            <>
              <span className="text-sm text-slate-600">Signed in</span>
              <button type="button" onClick={signOut} disabled={signingOut}
                className="font-semibold text-black hover:text-teal-600 disabled:opacity-60">
                {signingOut ? "Signing out…" : "Log out"}
              </button>
            </>
          )}
          {status === "restoring" && <span className="text-sm text-slate-600">Checking session…</span>}
        </nav>
        <button type="button" onClick={openHead} aria-label="Open navigation menu" className="lg:hidden">
          <HiBars3BottomRight aria-hidden="true" className="h-auto w-8 text-black" />
        </button>
      </div>
    </header>
  );
}
