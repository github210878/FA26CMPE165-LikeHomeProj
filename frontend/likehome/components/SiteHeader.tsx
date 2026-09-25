import Link from "next/link";

export default function SiteHeader() {
  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex min-h-16 w-full max-w-7xl flex-col items-stretch gap-1 px-4 py-2 sm:flex-row sm:items-center sm:justify-between sm:gap-6 sm:px-6 sm:py-0 lg:px-8">
        <Link
          href="/"
          className="inline-flex min-h-11 shrink-0 self-start items-center rounded-sm px-2 text-xl font-semibold tracking-tight text-slate-950"
        >
          LikeHome
        </Link>

        <nav aria-label="Primary navigation" className="w-full min-w-0 sm:w-auto">
          <ul className="flex flex-wrap items-center gap-x-1 text-sm sm:justify-end sm:gap-x-2">
            <li>
              <Link
                href="/"
                className="inline-flex min-h-11 items-center whitespace-nowrap rounded-sm px-2 font-medium text-slate-700 transition-colors hover:text-slate-950"
              >
                Home
              </Link>
            </li>
            <li>
              <span className="inline-flex min-h-11 items-center whitespace-nowrap px-2 text-slate-500">
                Find a Stay
                <span className="sr-only"> (coming soon)</span>
              </span>
            </li>
            <li>
              <span className="inline-flex min-h-11 items-center whitespace-nowrap px-2 text-slate-500">
                My Bookings
                <span className="sr-only"> (coming soon)</span>
              </span>
            </li>
            <li>
              <span className="inline-flex min-h-11 items-center whitespace-nowrap px-2 text-slate-500">
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
