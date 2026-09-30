export type SearchValues = {
  destination: string;
  checkIn: string;
  checkOut: string;
  guests: number;
};

function isCalendarDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

export function hotelSearchParams(values: SearchValues): URLSearchParams {
  const destination = values.destination.trim();
  if (
    !destination ||
    !isCalendarDate(values.checkIn) ||
    !isCalendarDate(values.checkOut) ||
    values.checkOut <= values.checkIn ||
    !Number.isInteger(values.guests) ||
    values.guests < 1 ||
    values.guests > 20
  ) {
    throw new Error("Enter a destination, valid stay dates, and 1–20 guests. Check-out must be after check-in.");
  }

  return new URLSearchParams({
    q: destination,
    check_in_date: values.checkIn,
    check_out_date: values.checkOut,
    adults: String(values.guests),
  });
}
