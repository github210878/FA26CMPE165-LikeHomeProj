export default function SiteFooter() {
  const currentYear = new Date().getFullYear();

  return (
    <footer className="border-t border-slate-200 bg-white">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-1 px-4 py-6 text-slate-600 sm:flex-row sm:items-center sm:justify-between sm:px-6 lg:px-8">
        <p className="font-semibold text-slate-900">LikeHome</p>
        <p className="text-sm">© {currentYear} LikeHome</p>
      </div>
    </footer>
  );
}
