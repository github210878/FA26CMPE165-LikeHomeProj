"use client";

import { useRef, useState } from "react";
import HotelResultCard from "@/components/HotelResultCard";
import { ApiError } from "@/lib/api";
import type { HotelSearchResponse } from "@/lib/api-types";
import { searchHotels, type SearchValues } from "@/lib/search";
import SearchForm from "./search-form";

type SearchStatus = "idle" | "loading" | "error" | "success";

export default function SearchExperience() {
  const [status, setStatus] = useState<SearchStatus>("idle");
  const [errorMessage, setErrorMessage] = useState("");
  const [results, setResults] = useState<HotelSearchResponse | null>(null);
  const requestId = useRef(0);

  async function handleSearch(values: SearchValues) {
    const currentRequest = ++requestId.current;
    setStatus("loading");
    setResults(null);
    setErrorMessage("");

    try {
      const response = await searchHotels(values);
      if (currentRequest !== requestId.current) return;
      setResults(response);
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
            <p className="mt-2 text-sm leading-6 text-slate-600">{results.result_count} stays found for {results.search_query}.</p>
            <ul className="mt-6 grid gap-4 md:grid-cols-2">
              {results.properties.map((hotel, index) => (
                <li key={hotel.property_token ?? `${hotel.name ?? "hotel"}-${index}`} className="min-w-0">
                  <HotelResultCard hotel={hotel} />
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </>
  );
}
