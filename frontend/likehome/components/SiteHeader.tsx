import Link from "next/link";

export default function SiteHeader() {
  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex min-h-16 w-full max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        <Link
          href="/"
          className="rounded-sm text-xl font-semibold tracking-tight text-slate-950"
        >
          LikeHome
        </Link>

        <div className="flex items-center gap-6">
          {/* Primary navigation will be added after route names are agreed on. */}
        </div>
      </div>
    </header>
  );
}
