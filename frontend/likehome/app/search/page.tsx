import type { Metadata } from "next";
import SearchExperience from "./search-experience";

export const metadata: Metadata = {
  title: "Find a stay | LikeHome",
};

export default function SearchPage() {
  return (
    <section className="mx-auto w-full max-w-7xl px-4 py-10 sm:px-6 sm:py-14 lg:px-8">
      <div className="max-w-3xl">
        <p className="text-sm font-semibold text-teal-700">Find a stay</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950 sm:text-4xl">
          Where would you like to stay?
        </h1>
      </div>
      <SearchExperience />
    </section>
  );
}
