import Link from "next/link";
import { CgClose } from "react-icons/cg";
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
  const position = showHead ? "translate-x-0" : "-translate-x-full";

  return (
    <div className="lg:hidden">
      <div aria-hidden="true" className={`fixed inset-0 z-[1002] h-screen bg-black opacity-70 transition-transform duration-500 ${position}`} />
      <nav aria-label="Mobile navigation" aria-hidden={!showHead} inert={!showHead}
        className={`fixed inset-y-0 left-0 z-[1050] flex h-full w-[80%] flex-col justify-center space-y-6 bg-teal-600 text-white transition-transform duration-500 sm:w-[60%] ${position}`}>
        {links.map((link) => (
          <Link href={link.url} key={link.id} onClick={closeHead}
            className="ml-12 w-fit border-b border-white pb-1 text-xl text-white sm:text-3xl">
            {link.label}
          </Link>
        ))}
        {status === "authenticated" && (
          <>
            <span className="ml-12 text-sm text-white">Signed in</span>
            <button type="button" onClick={signOut} disabled={signingOut}
              className="ml-12 w-fit border-b border-white pb-1 text-left text-xl text-white disabled:opacity-60 sm:text-3xl">
              {signingOut ? "Signing out…" : "Log out"}
            </button>
          </>
        )}
        {status === "restoring" && <span className="ml-12 text-sm text-white">Checking session…</span>}
        <button type="button" onClick={closeHead} aria-label="Close navigation menu"
          className="absolute right-5 top-3 text-white">
          <CgClose aria-hidden="true" className="h-7 w-7" />
        </button>
      </nav>
    </div>
  );
}
