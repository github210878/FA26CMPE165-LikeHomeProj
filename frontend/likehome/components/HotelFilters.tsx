"use client";

import { useEffect, useRef, useState } from "react";
import { HiOutlineAdjustmentsHorizontal, HiOutlineChevronDown, HiOutlineXMark } from "react-icons/hi2";
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
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const invalidPrice = values.maxPrice.trim() !== "" && parseMaxPrice(values.maxPrice) === null;
  const activeCount = (parseMaxPrice(values.maxPrice) !== null ? 1 : 0) + values.amenities.length;

  function dismiss() {
    setIsOpen(false);
    triggerRef.current?.focus();
  }

  useEffect(() => {
    if (!isOpen) return;
    function handleOutsidePointer(event: PointerEvent) {
      const container = containerRef.current;
      if (container && !container.contains(event.target as Node)) {
        // Restore focus if a non-focusable outside target would leave it hidden.
        if (container.contains(document.activeElement)) triggerRef.current?.focus();
        setIsOpen(false);
      }
    }
    document.addEventListener("pointerdown", handleOutsidePointer);
    return () => document.removeEventListener("pointerdown", handleOutsidePointer);
  }, [isOpen]);

  return (
    <div
      ref={containerRef}
      className="relative min-w-0 sm:shrink-0"
      onKeyDown={(event) => {
        if (isOpen && event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          dismiss();
        }
      }}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setIsOpen(false);
      }}
    >
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        aria-expanded={isOpen}
        aria-controls="hotel-filters-panel"
        aria-label={`Filters${activeCount > 0 ? `, ${activeCount} active` : ""}`}
        className="inline-flex min-h-12 items-center gap-2 rounded-xl border border-slate-300 bg-white px-4 text-sm font-semibold text-slate-900 shadow-sm hover:border-teal-700 hover:bg-teal-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700"
      >
        <HiOutlineAdjustmentsHorizontal aria-hidden="true" className="h-5 w-5 text-teal-800" />
        Filters
        {activeCount > 0 && <span aria-hidden="true" className="flex h-5 min-w-5 items-center justify-center rounded-full bg-teal-700 px-1 text-xs text-white">{activeCount}</span>}
        <HiOutlineChevronDown aria-hidden="true" className={`h-4 w-4 text-teal-800${isOpen ? " rotate-180" : ""}`} />
      </button>
      {isOpen && (
        <section id="hotel-filters-panel" aria-labelledby="hotel-filters-heading" className="mt-3 w-full min-w-0 rounded-2xl border border-slate-200 bg-white shadow-lg sm:absolute sm:left-0 sm:top-full sm:z-20 sm:w-[min(24rem,calc(100vw-4rem))]">
          <div className="flex items-center justify-between gap-2 border-b border-slate-200 px-4 py-3">
            <div>
              <h3 id="hotel-filters-heading" className="font-semibold text-slate-950">Filter your stays</h3>
              <button type="button" onClick={onClear} className="min-h-11 rounded-md text-sm font-medium text-teal-700 hover:underline focus-visible:outline-teal-700">
                Clear filters
              </button>
            </div>
            <button type="button" onClick={dismiss} aria-label="Close filters" className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-slate-600 hover:bg-slate-100 focus-visible:outline-teal-700">
              <HiOutlineXMark aria-hidden="true" className="h-5 w-5" />
            </button>
          </div>
          <div className="max-h-[min(28rem,55dvh)] space-y-5 overflow-y-auto overscroll-contain p-4">
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
                className={`min-h-11 w-full min-w-0 rounded-lg border px-3 focus-visible:outline-teal-700 ${invalidPrice ? "border-red-600" : "border-slate-300"}`}
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
                <div className="mt-2 grid grid-cols-2 gap-x-3">
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
                        className="h-5 w-5 shrink-0 accent-teal-700 focus-visible:outline-teal-700"
                      />
                      <span className="min-w-0 wrap-anywhere">{option.label}</span>
                    </label>
                  ))}
                </div>
              )}
            </fieldset>
          </div>
          <div className="border-t border-slate-200 p-4">
            <button type="button" onClick={dismiss} className="min-h-11 w-full rounded-xl bg-teal-700 px-4 text-sm font-semibold text-white hover:bg-teal-800 focus-visible:outline-teal-700">Show stays</button>
          </div>
        </section>
      )}
    </div>
  );
}
