"use client";

import Image from "next/image";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import HotelResultCard from "@/components/HotelResultCard";
import HotelFilters from "@/components/HotelFilters";
import HotelSortSelector from "@/components/HotelSortSelector";
import ErrorState from "@/components/ErrorState";
import { searchError, type SearchError } from "@/lib/search-error";
import type { HotelSearchResponse } from "@/lib/api-types";
import { searchHotels, type SearchOptions, type SearchValues } from "@/lib/search";
import { rememberRecentSearch } from "@/lib/recent-searches";
import { validateSearchValues } from "@/lib/search-validation.mjs";
import { checkoutHref } from "@/lib/checkout-selection";
import { filterHotels, getAmenityOptions, type HotelFilterValues } from "@/lib/hotel-filters";
import { sortHotels, type HotelSort } from "@/lib/hotel-sort";
import SearchForm from "./search-form";
import RecentSearches from "./recent-searches";
import { SearchResultsSkeleton } from "@/components/LoadingSkeletons";

type SearchStatus = "idle" | "loading" | "error" | "success";

export default function SearchExperience({ initialSearch }: { initialSearch?: SearchValues } = {}) {
  const initialSearchStarted = useRef(false);
  const [status, setStatus] = useState<SearchStatus>(() => initialSearch && Object.keys(validateSearchValues(initialSearch)).length === 0 ? "loading" : "idle");
  const [error, setError] = useState<SearchError | null>(null);
  const [results, setResults] = useState<HotelSearchResponse | null>(null);
  const [selectedSearch, setSelectedSearch] = useState<SearchValues | null>(null);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [pageError, setPageError] = useState<SearchError | null>(null);
  const [filters, setFilters] = useState<HotelFilterValues>({ maxPrice: "", amenities: [] });
  const [sort, setSort] = useState<HotelSort>("recommended");
  const [restoredSearch, setRestoredSearch] = useState<{ values: SearchValues; version: number } | null>(null);
  const requestId = useRef(0);
  const pending = useRef(false);
  const pendingPage = useRef<number | null>(null);
  const needsFreshSearch = useRef(false);
  const lastSearch = useRef<{ values: SearchValues; fresh: boolean } | null>(null);
  const filteredHotels = results ? filterHotels(results.properties, filters) : [];
  const displayedHotels = sortHotels(filteredHotels, sort);
  const amenityOptions = results ? getAmenityOptions(results.properties) : [];

  const clearFilters = useCallback(() => {
    setFilters({ maxPrice: "", amenities: [] });
  }, []);

  const handleSearch = useCallback(async (values: SearchValues, { retry = false, fresh = false }: SearchOptions & { retry?: boolean } = {}) => {
    if (pending.current) return;
    pending.current = true;
    lastSearch.current = { values: { ...values }, fresh };
    rememberRecentSearch(values);
    const currentRequest = ++requestId.current;
    pendingPage.current = null;
    setStatus("loading");
    setResults(null);
    setSelectedSearch(null);
    setIsLoadingMore(false);
    setPageError(null);
    if (!retry) setError(null);
    clearFilters();
    setSort("recommended");

    try {
      const response = await searchHotels(values, { fresh });
      if (currentRequest !== requestId.current) return;
      setResults(response);
      setSelectedSearch(values);
      setError(null);
      setStatus("success");
    } catch (error) {
      if (currentRequest !== requestId.current) return;
      setError(searchError(error));
      setStatus("error");
    } finally {
      pending.current = false;
    }
  }, [clearFilters]);

  useEffect(() => {
    if (!initialSearch || initialSearchStarted.current || Object.keys(validateSearchValues(initialSearch)).length > 0) return;
    initialSearchStarted.current = true;
    pending.current = true;
    lastSearch.current = { values: { ...initialSearch }, fresh: false };
    rememberRecentSearch(initialSearch);
    searchHotels(initialSearch).then((response) => {
      setResults(response);
      setSelectedSearch(initialSearch);
      setStatus("success");
    }).catch((failure: unknown) => {
      setError(searchError(failure));
      setStatus("error");
    }).finally(() => { pending.current = false; });
  }, [initialSearch]);

  async function loadNextPage() {
    const currentRequest = requestId.current;
    if (pending.current || isLoadingMore || pendingPage.current === currentRequest || !selectedSearch || !results?.next_page_token) return;
    pendingPage.current = currentRequest;
    setIsLoadingMore(true);
    setPageError(null);
    try {
      const nextPage = await searchHotels(selectedSearch, {
        nextPageToken: results.next_page_token,
        fresh: lastSearch.current?.fresh ?? false,
      });
      if (currentRequest !== requestId.current) return;
      setResults((current) => current ? {
        ...current,
        result_count: current.result_count + nextPage.result_count,
        properties: [...current.properties, ...nextPage.properties],
        next_page_token: nextPage.next_page_token,
      } : current);
    } catch (loadError) {
      if (currentRequest !== requestId.current) return;
      setPageError(searchError(loadError));
    } finally {
      if (pendingPage.current === currentRequest) pendingPage.current = null;
      if (currentRequest === requestId.current) setIsLoadingMore(false);
    }
  }

  function retrySearch() {
    if (error?.retryable && lastSearch.current) {
      void handleSearch(lastSearch.current.values, { retry: true, fresh: lastSearch.current.fresh });
    }
  }

  function submitSearch(values: SearchValues) {
    if (pending.current) return;
    const fresh = needsFreshSearch.current;
    needsFreshSearch.current = false;
    void handleSearch(values, { fresh });
  }

  function replaySearch(values: SearchValues) {
    if (pending.current) return;
    const hasErrors = Object.keys(validateSearchValues(values)).length > 0;
    needsFreshSearch.current = hasErrors;
    setRestoredSearch((previous) => ({ values, version: (previous?.version ?? 0) + 1 }));
    if (hasErrors) {
      requestId.current += 1;
      pendingPage.current = null;
      setStatus("idle");
      setResults(null);
      setSelectedSearch(null);
      setIsLoadingMore(false);
      setPageError(null);
      setError(null);
      lastSearch.current = null;
      clearFilters();
      setSort("recommended");
      return;
    }
    void handleSearch(values, { fresh: true });
  }

  return (
    <>
      <section className="relative isolate bg-teal-900">
        <Image src="/images/italian-coast.jpg" alt="Colorful seaside homes above the Mediterranean in Cinque Terre, Italy" fill priority sizes="100vw" className="object-cover object-[center_40%]" />
        <div className="absolute inset-0 bg-gradient-to-r from-black/75 via-black/50 to-black/20" />
        <div className="site-container relative py-10 sm:py-14">
          <p className="text-xs font-semibold uppercase tracking-[.25em] text-white/90">Find a stay</p>
          <h1 className="mt-4 text-3xl font-semibold tracking-tight text-white sm:text-5xl">Where would you like to stay?</h1>
          <p className="mt-4 max-w-2xl text-base leading-7 text-white/90">Somewhere new, somewhere familiar, somewhere just for you.</p>
          <div className="mt-8">
      <SearchForm
        compact
        key={restoredSearch?.version ?? 0}
        initialValues={restoredSearch?.values ?? initialSearch}
        onSearch={submitSearch}
        isLoading={status === "loading"}
      />
          </div>
        </div>
      </section>
      <div className="site-container pb-12">
      <RecentSearches onReplay={replaySearch} isLoading={status === "loading"} />

      {status === "idle" && (
        <section className="mt-9" aria-labelledby="popular-destinations-heading">
          <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 id="popular-destinations-heading" className="text-2xl font-semibold tracking-tight text-slate-950">Popular destinations</h2>
              <p className="mt-2 text-sm text-slate-600">A little inspiration for your next trip.</p>
            </div>
            <Link href="/#destinations" className="inline-flex min-h-11 items-center text-sm font-semibold text-teal-800">Explore destinations →</Link>
          </div>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            {[
              { name: "New York City", image: "new-york-city", description: "Iconic sights & skyline nights" },
              { name: "Tokyo", image: "tokyo-skyline", description: "Neon streets & new discoveries" },
              { name: "Lake Tahoe", image: "lake-tahoe", description: "Lakeside days & mountain air" },
              { name: "Paris", image: "paris", description: "Riverside strolls & café mornings" },
            ].map((destination) => (
              <Link key={destination.name} href={`/search?destination=${encodeURIComponent(destination.name)}`} className="group relative aspect-[1.1] overflow-hidden rounded-2xl bg-slate-200 sm:aspect-[1.25]">
                <Image src={`/images/${destination.image}.jpg`} alt="" fill sizes="(max-width: 1023px) 50vw, 25vw" className="object-cover transition-transform duration-300 group-hover:scale-105" />
                <div className="absolute inset-0 bg-gradient-to-t from-black/85 via-black/10 to-transparent" />
                <div className="absolute inset-x-0 bottom-0 flex items-end justify-between gap-2 p-4 sm:p-5">
                  <div><h3 className="text-lg font-semibold text-white">{destination.name}</h3><p className="mt-1 text-xs leading-5 text-white/90">{destination.description}</p></div>
                  <span aria-hidden="true" className="hidden h-9 w-9 shrink-0 items-center justify-center rounded-full border border-white/70 text-xl text-white sm:flex">→</span>
                </div>
              </Link>
            ))}
          </div>
        </section>
      )}
      <div className="mt-10 border-t border-slate-200 pt-8" aria-live="polite">
        <h2 className="text-xl font-semibold text-slate-950">Available stays</h2>
        {status === "idle" && <p className="mt-2 text-sm leading-6 text-slate-600">Enter a destination and dates to find available stays.</p>}
        {status === "loading" && <SearchResultsSkeleton />}
        {error && (
          <div className="mt-4">
            <ErrorState
              title={error.title}
              message={error.message}
              onRetry={error.retryable ? retrySearch : undefined}
              isRetrying={status === "loading"}
            />
          </div>
        )}
        {status === "success" && results?.properties.length === 0 && (
          <p className="mt-2 text-sm leading-6 text-slate-600">No hotels found for this search. Try a different destination or dates.</p>
        )}
        {status === "success" && results && results.properties.length > 0 && (
          <>
            <div className="mt-2 flex flex-col gap-4 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
              <p role="status" className="text-sm leading-6 text-slate-600">{filteredHotels.length} of {results.properties.length} loaded stays match for {results.search_query}.</p>
              <HotelSortSelector id="hotel-sort" value={sort} onChange={setSort} />
            </div>
            <HotelFilters values={filters} amenityOptions={amenityOptions} onChange={setFilters} onClear={clearFilters} />
            {filteredHotels.length === 0 && (
              <div className="mt-6 rounded-xl border border-slate-200 bg-white p-5">
                <p className="text-sm leading-6 text-slate-600">No stays match your current filters.</p>
                <button type="button" onClick={clearFilters} className="mt-3 min-h-11 rounded-md px-3 text-sm font-medium text-teal-700 hover:bg-teal-50">Clear filters</button>
              </div>
            )}
            <ul className="mt-6 grid gap-4 md:grid-cols-2">
              {displayedHotels.map((hotel, displayIndex) => (
                <li
                  key={`${hotel.property_token ?? hotel.name ?? "hotel"}-${results.properties.indexOf(hotel)}-${displayIndex}`}
                  className="min-w-0"
                >
                  <HotelResultCard hotel={hotel} checkoutHref={selectedSearch ? checkoutHref(selectedSearch, hotel) : null} />
                </li>
              ))}
            </ul>
            {pageError && (
              <div className="mt-6">
                <ErrorState
                  title={pageError.title}
                  message={pageError.message}
                  onRetry={pageError.retryable ? loadNextPage : undefined}
                  isRetrying={isLoadingMore}
                />
              </div>
            )}
            {results.next_page_token && !pageError && (
              <div className="mt-6 flex justify-center">
                <button
                  type="button"
                  onClick={() => void loadNextPage()}
                  disabled={isLoadingMore}
                  aria-busy={isLoadingMore}
                  className="min-h-11 rounded-md border border-teal-700 px-5 font-medium text-teal-800 hover:bg-teal-50 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {isLoadingMore ? "Loading more stays…" : "Load more stays"}
                </button>
              </div>
            )}
          </>
        )}
      </div>
      </div>
    </>
  );
}
