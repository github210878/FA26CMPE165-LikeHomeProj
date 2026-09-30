"use client";

import { useState, type FormEvent } from "react";
import { ApiError, getJson } from "@/lib/api";
import type { HotelSearchResponse } from "@/lib/api-types";
import { hotelSearchParams } from "@/lib/search";

const dollarAmount = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
});

export default function HotelSearch() {
  const [status, setStatus] = useState<"idle" | "loading" | "error" | "success">("idle");
  const [errorMessage, setErrorMessage] = useState("");
  const [results, setResults] = useState<HotelSearchResponse | null>(null);

  async function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const destination = String(form.get("destination") || "");
    const checkIn = String(form.get("checkIn") || "");
    const checkOut = String(form.get("checkOut") || "");
    const guests = Number(form.get("guests"));

    setResults(null);
    let query: URLSearchParams;
    try {
      query = hotelSearchParams({ destination, checkIn, checkOut, guests });
    } catch {
      setStatus("error");
      setErrorMessage("Enter a destination, valid stay dates, and 1–20 guests. Check-out must be after check-in.");
      return;
    }

    setStatus("loading");
    setErrorMessage("");
    try {
      const response = await getJson<HotelSearchResponse>(`/hotels/search?${query}`);
      setResults(response);
      setStatus("success");
    } catch (error) {
      setStatus("error");
      if (error instanceof ApiError && error.status === 422) {
        setErrorMessage("The search details were not accepted. Please check the destination, dates, and guest count.");
      } else if (error instanceof ApiError && (error.status === 502 || error.status === 504)) {
        setErrorMessage("The hotel search provider is unavailable right now. Please try again later.");
      } else if (error instanceof TypeError) {
        setErrorMessage("Cannot reach the hotel search service. Please try again later.");
      } else {
        setErrorMessage("Hotel search is unavailable right now. Please try again later.");
      }
    }
  }

  return (
    <>
      <form onSubmit={handleSearch} noValidate className="mt-8 grid max-w-3xl gap-4 rounded-xl border border-slate-200 bg-white p-5 sm:grid-cols-2 sm:p-6">
        <label className="grid gap-2 text-sm font-medium text-slate-800 sm:col-span-2">
          Destination
          <input type="search" name="destination" placeholder="City or neighborhood" required className="min-h-11 rounded-md border border-slate-300 px-3 font-normal" />
        </label>
        <label className="grid gap-2 text-sm font-medium text-slate-800">
          Check-in
          <input type="date" name="checkIn" required className="min-h-11 rounded-md border border-slate-300 px-3 font-normal" />
        </label>
        <label className="grid gap-2 text-sm font-medium text-slate-800">
          Check-out
          <input type="date" name="checkOut" required className="min-h-11 rounded-md border border-slate-300 px-3 font-normal" />
        </label>
        <label className="grid gap-2 text-sm font-medium text-slate-800">
          Guests
          <input type="number" name="guests" min="1" max="20" defaultValue="1" required className="min-h-11 rounded-md border border-slate-300 px-3 font-normal" />
        </label>
        <div className="flex items-end">
          <button type="submit" disabled={status === "loading"} className="min-h-11 w-full rounded-md bg-teal-700 px-5 font-medium text-white transition-colors hover:bg-teal-800 disabled:cursor-not-allowed disabled:opacity-60">
            {status === "loading" ? "Searching…" : "Search stays"}
          </button>
        </div>
      </form>

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
                <li key={hotel.property_token ?? `${hotel.name ?? "hotel"}-${index}`} className="rounded-xl border border-slate-200 bg-white p-5">
                  <h3 className="text-lg font-semibold text-slate-950">{hotel.name ?? "Unnamed property"}</h3>
                  {hotel.price_per_night !== null && <p className="mt-2 text-sm text-slate-700">From {dollarAmount.format(hotel.price_per_night)} per night</p>}
                  {hotel.rating !== null && <p className="mt-1 text-sm text-slate-700">Rating: {hotel.rating} / 5</p>}
                  {hotel.amenities && hotel.amenities.length > 0 && <p className="mt-2 text-sm text-slate-600">{hotel.amenities.slice(0, 5).join(" · ")}</p>}
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </>
  );
}
