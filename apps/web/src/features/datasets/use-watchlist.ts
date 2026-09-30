// Resilient watchlist persisted to localStorage (SSR-safe, corrupt-JSON→empty).
//
// The list is a set of dataset names kept in insertion order. Reading is
// defensive: storage that is absent, unreadable, or not a JSON array of
// non-empty strings is treated as an empty watchlist — corrupt storage is
// not data, and it never throws into a render. Writing happens only after
// the first successful read, so a render before hydration cannot wipe a
// previous session's list.

import { useEffect, useState } from 'react';

const STORAGE_KEY = 'hqos.watchlist.v1';

function readStoredWatchlist(): string[] {
  try {
    const raw = typeof window !== 'undefined' ? localStorage.getItem(STORAGE_KEY) : null;
    if (raw === null) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return [...new Set(parsed.filter((v): v is string => typeof v === 'string' && v.length > 0))];
  } catch {
    // corrupt storage is not data; treat as empty
    return [];
  }
}

/**
 * The persisted watchlist and its toggle.
 *
 * Returns `[names, toggle]`:
 * - `names` is empty on the server and before hydration, then the stored
 *   list — the UI renders an empty watchlist during that window rather
 *   than inventing contents.
 * - `toggle(name)` adds an absent name or removes a present one. It reads
 *   storage itself when state has not hydrated yet, so a click before the
 *   first effect can never replace a stored list with an empty one.
 */
export function useWatchlist(): [string[], (name: string) => void] {
  const [names, setNames] = useState<string[] | null>(null); // null = not loaded yet

  // Initial load (runs once on mount; hydrated value carries through SSR)
  useEffect(() => {
    setNames(readStoredWatchlist());
  }, []);

  // Effective list (empty before hydration — never null)
  const effective = names ?? [];

  // Toggle a dataset name in the watchlist (dedupe, preserve insertion order)
  const toggle = (name: string) =>
    setNames((prev) => {
      const current = prev ?? readStoredWatchlist();
      return current.includes(name) ? current.filter((n) => n !== name) : [...current, name];
    });

  // Persist only after hydration so an early render cannot overwrite a
  // previous session's watchlist with the pre-hydration empty list.
  useEffect(() => {
    if (names !== null) {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(names));
      } catch {
        // private mode / quota exceeded – keep in-memory state only; UI stays functional
      }
    }
  }, [names]);

  return [effective, toggle];
}
