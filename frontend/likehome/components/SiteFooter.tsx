import Link from "next/link";
import { HiOutlineHomeModern } from "react-icons/hi2";

export default function SiteFooter() {
  return (
    <footer className="border-t border-slate-200 bg-white">
      <div className="site-container py-9">
        <div className="flex flex-col justify-between gap-7 sm:flex-row sm:items-center">
          <div><Link href="/" className="brand"><span className="brand-mark"><HiOutlineHomeModern aria-hidden="true" className="h-5 w-5" /></span>LikeHome.</Link><p className="mt-3 text-sm text-slate-600">New places. Familiar comfort.</p></div>
          <nav aria-label="Footer navigation" className="flex flex-wrap gap-x-7 gap-y-3 text-sm font-medium text-slate-700"><Link href="/search" className="py-2 hover:text-teal-700">Find a stay</Link><Link href="/my-bookings" className="py-2 hover:text-teal-700">My bookings</Link><Link href="/signup" className="py-2 hover:text-teal-700">Create an account</Link></nav>
        </div>
        <div className="mt-8 flex flex-wrap justify-between gap-2 border-t border-slate-200 pt-5 text-xs text-slate-500"><p>© {new Date().getFullYear()} LikeHome</p><p>A comfortable place to begin.</p></div>
      </div>
    </footer>
  );
}
