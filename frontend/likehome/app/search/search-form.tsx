"use client";

import { useState, type ChangeEvent, type FormEvent } from "react";
import { validateSearchValues } from "@/lib/search-validation.mjs";
import type { SearchValues } from "@/lib/search";

type SearchFormErrors = Partial<Record<"destination" | "checkIn" | "checkOut" | "guests", string>>;

function readForm(form: HTMLFormElement): SearchValues {
  const data = new FormData(form);
  return {
    destination: String(data.get("destination") ?? "").trim(),
    checkIn: String(data.get("checkIn") ?? ""),
    checkOut: String(data.get("checkOut") ?? ""),
    guests: String(data.get("guests") ?? "").trim(),
  };
}

function inputClass(invalid: boolean) {
  return `min-h-11 rounded-md border px-3 font-normal ${invalid ? "border-red-600" : "border-slate-300"}`;
}

export default function SearchForm({
  onSearch,
  isLoading,
  initialValues,
}: {
  onSearch: (values: SearchValues) => void;
  isLoading: boolean;
  initialValues?: SearchValues;
}) {
  const [errors, setErrors] = useState<SearchFormErrors>(() => initialValues ? validateSearchValues(initialValues) : {});
  const [submitted, setSubmitted] = useState(Boolean(initialValues));

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    const form = event.currentTarget;
    const values = readForm(form);
    const nextErrors = validateSearchValues(values);
    setSubmitted(true);
    setErrors(nextErrors);
    event.preventDefault();
    if (Object.keys(nextErrors).length > 0) {
      for (const name of ["destination", "checkIn", "checkOut", "guests"] as const) {
        if (nextErrors[name]) {
          (form.elements.namedItem(name) as HTMLInputElement | null)?.focus();
          break;
        }
      }
      return;
    }

    onSearch(values);
  }

  function handleChange(event: ChangeEvent<HTMLFormElement>) {
    if (submitted) setErrors(validateSearchValues(readForm(event.currentTarget)));
  }

  return (
    <form
      noValidate
      onSubmit={handleSubmit}
      onChange={handleChange}
      className="mt-8 grid max-w-3xl gap-4 rounded-xl border border-slate-200 bg-white p-5 sm:grid-cols-2 sm:p-6"
    >
      <div className="grid gap-2 text-sm font-medium text-slate-800 sm:col-span-2">
        <label htmlFor="destination">Destination</label>
        <input
          id="destination"
          type="search"
          name="destination"
          defaultValue={initialValues?.destination ?? ""}
          placeholder="City or neighborhood"
          required
          aria-invalid={Boolean(errors.destination)}
          aria-describedby={errors.destination ? "destination-error" : undefined}
          className={inputClass(Boolean(errors.destination))}
        />
        {errors.destination && <p id="destination-error" className="text-red-700">{errors.destination}</p>}
      </div>
      <div className="grid gap-2 text-sm font-medium text-slate-800">
        <label htmlFor="checkIn">Check-in</label>
        <input
          id="checkIn"
          type="date"
          name="checkIn"
          defaultValue={initialValues?.checkIn ?? ""}
          required
          aria-invalid={Boolean(errors.checkIn)}
          aria-describedby={errors.checkIn ? "checkIn-error" : undefined}
          className={inputClass(Boolean(errors.checkIn))}
        />
        {errors.checkIn && <p id="checkIn-error" className="text-red-700">{errors.checkIn}</p>}
      </div>
      <div className="grid gap-2 text-sm font-medium text-slate-800">
        <label htmlFor="checkOut">Check-out</label>
        <input
          id="checkOut"
          type="date"
          name="checkOut"
          defaultValue={initialValues?.checkOut ?? ""}
          required
          aria-invalid={Boolean(errors.checkOut)}
          aria-describedby={errors.checkOut ? "checkOut-error" : undefined}
          className={inputClass(Boolean(errors.checkOut))}
        />
        {errors.checkOut && <p id="checkOut-error" className="text-red-700">{errors.checkOut}</p>}
      </div>
      <div className="grid gap-2 text-sm font-medium text-slate-800">
        <label htmlFor="guests">Guests</label>
        <input
          id="guests"
          type="number"
          name="guests"
          min="1"
          max="20"
          step="1"
          defaultValue={initialValues?.guests ?? "1"}
          required
          aria-invalid={Boolean(errors.guests)}
          aria-describedby={errors.guests ? "guests-error" : undefined}
          className={inputClass(Boolean(errors.guests))}
        />
        {errors.guests && <p id="guests-error" className="text-red-700">{errors.guests}</p>}
      </div>
      <div className="flex items-end">
        <button type="submit" disabled={isLoading} className="min-h-11 w-full rounded-md bg-teal-700 px-5 font-medium text-white transition-colors hover:bg-teal-800 disabled:cursor-not-allowed disabled:opacity-60">
          {isLoading ? "Searching…" : "Search stays"}
        </button>
      </div>
      {Object.keys(errors).length > 0 && (
        <p role="alert" className="text-sm text-red-700 sm:col-span-2">
          Please correct the highlighted fields before searching.
        </p>
      )}
    </form>
  );
}
