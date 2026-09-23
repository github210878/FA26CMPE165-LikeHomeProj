import Link from "next/link";

export default function SiteHeader() {
  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex min-h-16 w-full max-w-7xl flex-wrap items-center justify-between gap-x-6 gap-y-3 px-4 py-3 sm:flex-nowrap sm:px-6 sm:py-0 lg:px-8">
        <Link
          href="/"
          className="shrink-0 rounded-sm text-xl font-semibold tracking-tight text-slate-950"
        >
          LikeHome
        </Link>

        <nav aria-label="Primary navigation">
          <ul className="flex flex-wrap items-center justify-end gap-x-4 gap-y-2 text-sm sm:gap-x-6">
            <li>
              <Link
                href="/"
                className="rounded-sm font-medium text-slate-700 transition-colors hover:text-slate-950"
              >
                Home
              </Link>
            </li>
            <li>
              <span className="text-slate-500">
                Find a Stay
                <span className="sr-only"> (coming soon)</span>
              </span>
            </li>
            <li>
              <span className="text-slate-500">
                My Bookings
                <span className="sr-only"> (coming soon)</span>
              </span>
            </li>
            <li>
              <span className="text-slate-500">
                Sign In
                <span className="sr-only"> (coming soon)</span>
              </span>
            </li>
          </ul>
        </nav>
      </div>
    </header>
  );
}
