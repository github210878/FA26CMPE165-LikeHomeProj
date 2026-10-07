"use client";

import { useRef, useState } from "react";
import HotelResultCard from "@/components/HotelResultCard";
import HotelFilters from "@/components/HotelFilters";
import { ApiError } from "@/lib/api";
import type { HotelSearchResponse } from "@/lib/api-types";
import { searchHotels, type SearchValues } from "@/lib/search";
import { checkoutHref } from "@/lib/checkout-selection";
import { filterHotels, getAmenityOptions, type HotelFilterValues } from "@/lib/hotel-filters";
import SearchForm from "./search-form";

type SearchStatus = "idle" | "loading" | "error" | "success";

export default function SearchExperience() {
  const [status, setStatus] = useState<SearchStatus>("idle");
  const [errorMessage, setErrorMessage] = useState("");
  const [results, setResults] = useState<HotelSearchResponse | null>(null);
  const [selectedSearch, setSelectedSearch] = useState<SearchValues | null>(null);
  const [filters, setFilters] = useState<HotelFilterValues>({ maxPrice: "", amenities: [] });
  const requestId = useRef(0);
  const filteredHotels = results ? filterHotels(results.properties, filters) : [];
  const amenityOptions = results ? getAmenityOptions(results.properties) : [];

  function clearFilters() {
    setFilters({ maxPrice: "", amenities: [] });
  }

  async function handleSearch(values: SearchValues) {
    const currentRequest = ++requestId.current;
    setStatus("loading");
    setResults(null);
    setSelectedSearch(null);
    setErrorMessage("");
    clearFilters();

    try {
      const response = await searchHotels(values);
      if (currentRequest !== requestId.current) return;
      setResults(response);
      setSelectedSearch(values);
      setStatus("success");
    } catch (error) {
      if (currentRequest !== requestId.current) return;
      if (error instanceof ApiError && error.status === 422) {
        setErrorMessage("The search details were not accepted. Please check the destination, dates, and guest count.");
      } else if (error instanceof ApiError && (error.status === 502 || error.status === 504)) {
        setErrorMessage("The hotel search provider is unavailable right now. Please try again later.");
      } else if (error instanceof TypeError) {
        setErrorMessage("Cannot reach the hotel search service. Please try again later.");
      } else {
        setErrorMessage("Hotel search is unavailable right now. Please try again later.");
      }
      setStatus("error");
    }
  }

  return (
    <>
      <SearchForm onSearch={handleSearch} isLoading={status === "loading"} />

      <div className="mt-12 border-t border-slate-200 pt-8" aria-live="polite">
        <h2 className="text-xl font-semibold text-slate-950">Available stays</h2>
        {status === "idle" && <p className="mt-2 text-sm leading-6 text-slate-600">Enter a destination and dates to find available stays.</p>}
        {status === "loading" && <p className="mt-2 text-sm leading-6 text-slate-600">Searching for stays…</p>}
        {status === "error" && <p role="alert" className="mt-2 text-sm leading-6 text-red-700">{errorMessage}</p>}
        {status === "success" && results?.properties.length === 0 && (
          <p className="mt-2 text-sm leading-6 text-slate-600">No hotels found for this search. Try a different destination or dates.</p>
        )}
        {status === "success" && results && results.properties.length > 0 && (
          <>
            <p role="status" className="mt-2 text-sm leading-6 text-slate-600">{filteredHotels.length} of {results.properties.length} loaded stays match for {results.search_query}.</p>
            <HotelFilters values={filters} amenityOptions={amenityOptions} onChange={setFilters} onClear={clearFilters} />
            {filteredHotels.length === 0 && (
              <div className="mt-6 rounded-xl border border-slate-200 bg-white p-5">
                <p className="text-sm leading-6 text-slate-600">No stays match your current filters.</p>
                <button type="button" onClick={clearFilters} className="mt-3 min-h-11 rounded-md px-3 text-sm font-medium text-teal-700 hover:bg-teal-50">Clear filters</button>
              </div>
            )}
            <ul className="mt-6 grid gap-4 md:grid-cols-2">
              {filteredHotels.map((hotel) => (
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
