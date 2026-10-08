import type { SearchValues } from "./search.ts";
import { validateSearchValues } from "./search-validation.mjs";

const STORAGE_KEY = "likehome_recent_searches_v1";
const CHANGE_EVENT = "likehome:recent-searches-changed";
const MAX_RECENT_SEARCHES = 5;

function normalizeSearch(value: unknown): SearchValues | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  if (typeof record.destination !== "string" || typeof record.checkIn !== "string" ||
    typeof record.checkOut !== "string" || typeof record.guests !== "string") return null;

  const values: SearchValues = {
    destination: record.destination.trim(),
    checkIn: record.checkIn,
    checkOut: record.checkOut,
    guests: record.guests.trim(),
  };
  // Keep expired stays so the user can restore them and choose new dates.
  if (Object.keys(validateSearchValues(values, "0001-01-01")).length > 0) return null;
  values.guests = String(Number(values.guests));
  return values;
}

function searchKey(values: SearchValues): string {
  return JSON.stringify([
    values.destination.toLowerCase(), values.checkIn, values.checkOut, values.guests,
  ]);
}

export function parseRecentSearches(snapshot: string | null): SearchValues[] {
  if (!snapshot) return [];
  try {
    const stored: unknown = JSON.parse(snapshot);
    if (!Array.isArray(stored)) return [];
    const searches: SearchValues[] = [];
    const seen = new Set<string>();
    for (const item of stored) {
      const values = normalizeSearch(item);
      if (!values || seen.has(searchKey(values))) continue;
      seen.add(searchKey(values));
      searches.push(values);
      if (searches.length === MAX_RECENT_SEARCHES) break;
    }
    return searches;
  } catch {
    return [];
  }
}

// A primitive snapshot stays stable between renders for useSyncExternalStore.
export function getRecentSearchSnapshot(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function getServerSearchSnapshot(): null {
  return null;
}

export function subscribeRecentSearches(onChange: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  function onStorage(event: StorageEvent) {
    if (event.key === STORAGE_KEY || event.key === null) onChange();
  }
  window.addEventListener("storage", onStorage);
  window.addEventListener(CHANGE_EVENT, onChange);
  return () => {
    window.removeEventListener("storage", onStorage);
    window.removeEventListener(CHANGE_EVENT, onChange);
  };
}

export function rememberRecentSearch(value: SearchValues): void {
  if (typeof window === "undefined") return;
  const values = normalizeSearch(value);
  if (!values || Object.keys(validateSearchValues(values)).length > 0) return;
  const previous = parseRecentSearches(getRecentSearchSnapshot());
  const searches = [values, ...previous.filter((item) => searchKey(item) !== searchKey(values))]
    .slice(0, MAX_RECENT_SEARCHES);
  try {
    // Persist only parameters; hotel data and prices must come from a new request.
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(searches));
    window.dispatchEvent(new Event(CHANGE_EVENT));
  } catch {
    // A full or blocked browser store must not prevent a normal hotel search.
  }
}

export function clearRecentSearches(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
    window.dispatchEvent(new Event(CHANGE_EVENT));
  } catch {
    // Storage may be disabled by the browser.
  }
}
