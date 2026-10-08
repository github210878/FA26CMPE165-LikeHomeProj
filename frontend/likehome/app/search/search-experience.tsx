"use client";

import { useRef, useState } from "react";
import HotelResultCard from "@/components/HotelResultCard";
import HotelFilters from "@/components/HotelFilters";
import ErrorState from "@/components/ErrorState";
import { searchError, type SearchError } from "@/lib/search-error";
import type { HotelSearchResponse } from "@/lib/api-types";
import { searchHotels, type SearchValues } from "@/lib/search";
import { checkoutHref } from "@/lib/checkout-selection";
import { filterHotels, getAmenityOptions, type HotelFilterValues } from "@/lib/hotel-filters";
import { HOTEL_SORT_OPTIONS, sortHotels, type HotelSort } from "@/lib/hotel-sort";
import SearchForm from "./search-form";

type SearchStatus = "idle" | "loading" | "error" | "success";

export default function SearchExperience() {
  const [status, setStatus] = useState<SearchStatus>("idle");
  const [error, setError] = useState<SearchError | null>(null);
  const [results, setResults] = useState<HotelSearchResponse | null>(null);
  const [selectedSearch, setSelectedSearch] = useState<SearchValues | null>(null);
  const [filters, setFilters] = useState<HotelFilterValues>({ maxPrice: "", amenities: [] });
  const [sort, setSort] = useState<HotelSort>("recommended");
  const requestId = useRef(0);
  const pending = useRef(false);
  const lastSearch = useRef<SearchValues | null>(null);
  const filteredHotels = results ? filterHotels(results.properties, filters) : [];
  const displayedHotels = sortHotels(filteredHotels, sort);
  const amenityOptions = results ? getAmenityOptions(results.properties) : [];

  function clearFilters() {
    setFilters({ maxPrice: "", amenities: [] });
  }

  async function handleSearch(values: SearchValues, retry = false) {
    if (pending.current) return;
    pending.current = true;
    lastSearch.current = { ...values };
    const currentRequest = ++requestId.current;
    setStatus("loading");
    setResults(null);
    setSelectedSearch(null);
    if (!retry) setError(null);
    clearFilters();
    setSort("recommended");

    try {
      const response = await searchHotels(values);
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
  }

  function retrySearch() {
    if (error?.retryable && lastSearch.current) {
      void handleSearch(lastSearch.current, true);
    }
  }

  return (
    <>
      <SearchForm onSearch={handleSearch} isLoading={status === "loading"} />

      <div className="mt-12 border-t border-slate-200 pt-8" aria-live="polite">
        <h2 className="text-xl font-semibold text-slate-950">Available stays</h2>
        {status === "idle" && <p className="mt-2 text-sm leading-6 text-slate-600">Enter a destination and dates to find available stays.</p>}
        {status === "loading" && <p className="mt-2 text-sm leading-6 text-slate-600">Searching for stays…</p>}
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
              <div className="grid gap-2 text-sm text-slate-800 sm:w-64">
                <label htmlFor="hotel-sort" className="font-medium">Sort stays</label>
                <select
                  id="hotel-sort"
                  value={sort}
                  onChange={(event) => setSort(event.target.value as HotelSort)}
                  className="min-h-11 w-full min-w-0 rounded-md border border-slate-300 bg-white px-3"
                >
                  {HOTEL_SORT_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </div>
            </div>
            <HotelFilters values={filters} amenityOptions={amenityOptions} onChange={setFilters} onClear={clearFilters} />
            {filteredHotels.length === 0 && (
              <div className="mt-6 rounded-xl border border-slate-200 bg-white p-5">
                <p className="text-sm leading-6 text-slate-600">No stays match your current filters.</p>
                <button type="button" onClick={clearFilters} className="mt-3 min-h-11 rounded-md px-3 text-sm font-medium text-teal-700 hover:bg-teal-50">Clear filters</button>
              </div>
            )}
            <ul className="mt-6 grid gap-4 md:grid-cols-2">
              {displayedHotels.map((hotel) => (
                <li key={hotel.property_token ?? `${hotel.name ?? "hotel"}-${results.properties.indexOf(hotel)}`} className="min-w-0">
                  <HotelResultCard hotel={hotel} checkoutHref={selectedSearch ? checkoutHref(selectedSearch, hotel) : null} />
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </>
  );
}
