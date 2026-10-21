import { HiOutlineChevronDown } from "react-icons/hi2";
import { HOTEL_SORT_OPTIONS, type HotelSort } from "@/lib/hotel-sort";

type Props = {
  id: string;
  value: HotelSort;
  onChange: (value: HotelSort) => void;
};

export default function HotelSortSelector({ id, value, onChange }: Props) {
  return (
    <div className="w-full space-y-2 sm:w-72">
      <label htmlFor={id} className="block text-sm font-semibold text-slate-900">Sort stays</label>
      <div className="relative">
        <select
          id={id}
          value={value}
          onChange={(event) => {
            const option = HOTEL_SORT_OPTIONS.find((option) => option.value === event.target.value);
            if (option) onChange(option.value);
          }}
          aria-describedby={`${id}-hint`}
          className="min-h-12 w-full appearance-none rounded-xl border border-slate-300 bg-white py-3 pl-4 pr-11 text-sm font-medium text-slate-900 shadow-sm transition-colors hover:border-teal-700 focus-visible:border-teal-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700"
        >
          {HOTEL_SORT_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
        <HiOutlineChevronDown aria-hidden="true" className="pointer-events-none absolute right-4 top-1/2 h-4 w-4 -translate-y-1/2 text-teal-800" />
      </div>
      <p id={`${id}-hint`} className="text-xs text-slate-600">Applies to loaded stays matching your filters.</p>
    </div>
  );
}
