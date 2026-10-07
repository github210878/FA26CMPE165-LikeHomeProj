"use client";

import { parseMaxPrice, type AmenityOption, type HotelFilterValues } from "@/lib/hotel-filters";

export default function HotelFilters({
  values,
  amenityOptions,
  onChange,
  onClear,
}: {
  values: HotelFilterValues;
  amenityOptions: AmenityOption[];
  onChange: (values: HotelFilterValues) => void;
  onClear: () => void;
}) {
  const invalidPrice = values.maxPrice.trim() !== "" && parseMaxPrice(values.maxPrice) === null;
  const hasFilters = values.maxPrice !== "" || values.amenities.length > 0;

  return (
    <section aria-labelledby="hotel-filters-heading" className="mt-6 min-w-0 rounded-xl border border-slate-200 bg-white p-5 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 id="hotel-filters-heading" className="font-semibold text-slate-950">Filter stays</h3>
        {hasFilters && (
          <button type="button" onClick={onClear} className="min-h-11 rounded-md px-3 text-sm font-medium text-teal-700 hover:bg-teal-50">
            Clear filters
          </button>
        )}
      </div>
      <div className="mt-4 grid gap-6 sm:grid-cols-[minmax(0,15rem)_minmax(0,1fr)]">
        <div className="grid content-start gap-2 text-sm text-slate-800">
          <label htmlFor="hotel-max-price" className="font-medium">Maximum nightly price ($ USD / night)</label>
          <input
            id="hotel-max-price"
            type="text"
            inputMode="decimal"
            value={values.maxPrice}
            onChange={(event) => onChange({ ...values, maxPrice: event.target.value })}
            placeholder="No limit"
            aria-invalid={invalidPrice}
            aria-describedby={`hotel-price-help${invalidPrice ? " hotel-price-error" : ""}`}
            className={`min-h-11 w-full min-w-0 rounded-md border px-3 ${invalidPrice ? "border-red-600" : "border-slate-300"}`}
          />
          <p id="hotel-price-help" className="text-slate-600">Stays without a price are excluded when a price limit is set.</p>
          {invalidPrice && (
            <p id="hotel-price-error" role="alert" className="text-red-700">Enter a nonnegative amount, such as 150 or 150.50. The price limit is not applied.</p>
          )}
        </div>
        <fieldset className="min-w-0">
          <legend className="text-sm font-medium text-slate-800">Amenities</legend>
          <p className="mt-2 text-sm text-slate-600">Stays must include every selected amenity.</p>
          {amenityOptions.length === 0 ? (
            <p className="mt-2 text-sm text-slate-600">No amenities listed in these results.</p>
          ) : (
            <div className="mt-2 grid gap-x-4 sm:grid-cols-2 lg:grid-cols-3">
              {amenityOptions.map((option) => (
                <label key={option.value} className="flex min-h-11 min-w-0 cursor-pointer items-center gap-3 py-2 text-sm text-slate-800">
                  <input
                    type="checkbox"
                    value={option.value}
                    checked={values.amenities.includes(option.value)}
                    onChange={(event) => onChange({
                      ...values,
                      amenities: event.target.checked
                        ? [...values.amenities, option.value]
                        : values.amenities.filter((amenity) => amenity !== option.value),
                    })}
                    className="h-4 w-4 shrink-0 accent-teal-700"
                  />
                  <span className="min-w-0 break-words">{option.label}</span>
                </label>
              ))}
            </div>
          )}
        </fieldset>
      </div>
    </section>
  );
}
