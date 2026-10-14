import Link from "next/link";
import type { HeaderLink } from "@/constants/constant";

type Props = {
  links: readonly HeaderLink[];
  status: "restoring" | "authenticated" | "unauthenticated";
  signingOut: boolean;
  showHead: boolean;
  closeHead: () => void;
  signOut: () => void;
};

export default function MobileHeader({ links, status, signingOut, showHead, closeHead, signOut }: Props) {
  return (
    <nav id="mobile-navigation" aria-label="Mobile navigation" hidden={!showHead} className="border-b border-slate-200 bg-white px-5 py-4 lg:hidden" onKeyDown={(event) => {
      if (event.key === "Escape") {
        closeHead();
        document.querySelector<HTMLButtonElement>('[aria-controls="mobile-navigation"]')?.focus();
      }
    }}>
      <div className="mx-auto flex max-w-7xl flex-col gap-2">
        {links.map((link) => (
          <Link href={link.url} key={link.id} onClick={closeHead} className="rounded-xl px-4 py-3 text-sm font-medium text-slate-900 hover:bg-teal-50">{link.label}</Link>
        ))}
        {status === "authenticated" && <button type="button" onClick={signOut} disabled={signingOut} className="rounded-xl px-4 py-3 text-left text-sm font-medium text-teal-700 disabled:opacity-60">{signingOut ? "Signing out…" : "Log out"}</button>}
        {status === "restoring" && <p className="px-4 py-3 text-sm text-slate-600">Checking session…</p>}
      </div>
    </nav>
  );
}
