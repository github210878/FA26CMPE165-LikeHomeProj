/** @param {Date} [now] */
export function getLocalToday(now = new Date()) {
  return [
    String(now.getFullYear()).padStart(4, "0"),
    String(now.getMonth() + 1).padStart(2, "0"),
    String(now.getDate()).padStart(2, "0"),
  ].join("-");
}

/** @param {string} value */
function isCalendarDate(value) {
  if (!/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value)) return false;
  const [year, month, day] = value.split("-").map(Number);
  if (year < 1 || month < 1 || month > 12 || day < 1) return false;
  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return day <= days[month - 1];
}

/**
 * Validate the existing search form without changing its request field names.
 * @param {{checkIn: string, checkOut: string, guests: string}} inputs
 * @param {string} [today] Local calendar date, injectable for deterministic tests.
 * @returns {{checkIn?: string, checkOut?: string, guests?: string}}
 */
export function validateSearchInputs(inputs, today = getLocalToday()) {
  /** @type {{checkIn?: string, checkOut?: string, guests?: string}} */
  const errors = {};
  const validCheckIn = isCalendarDate(inputs.checkIn);
  const validCheckOut = isCalendarDate(inputs.checkOut);

  if (!inputs.checkIn) {
    errors.checkIn = "Choose a check-in date.";
  } else if (!validCheckIn) {
    errors.checkIn = "Enter a valid check-in date in YYYY-MM-DD format.";
  } else if (inputs.checkIn < today) {
    errors.checkIn = "Check-in date cannot be in the past.";
  }

  if (!inputs.checkOut) {
    errors.checkOut = "Choose a check-out date.";
  } else if (!validCheckOut) {
    errors.checkOut = "Enter a valid check-out date in YYYY-MM-DD format.";
  } else if (validCheckIn && inputs.checkOut <= inputs.checkIn) {
    errors.checkOut = "Check-out date must be after check-in date.";
  }

  const guests = inputs.guests.trim();
  if (!guests) {
    errors.guests = "Enter the number of guests.";
  } else if (!/^[0-9]+$/.test(guests) || Number(guests) < 1 || Number(guests) > 20) {
    errors.guests = "Guests must be a whole number from 1 to 20.";
  }

  return errors;
}
