/**
 * @vitest-environment jsdom
 *
 * The watchlist is the only state in this app that survives a reload, so
 * this hook is the boundary that must be honest with storage: corrupt or
 * hostile content is treated as an empty list (never thrown into a render),
 * entries that are not non-empty strings are dropped, order is preserved,
 * and every toggle is written back so a reload sees the same list.
 */
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { act, cleanup, renderHook } from '@testing-library/react';

import { useWatchlist } from '../../apps/web/src/features/datasets/use-watchlist';

const STORAGE_KEY = 'hqos.watchlist.v1';

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  cleanup();
  localStorage.clear();
});

describe('useWatchlist', () => {
  it('starts empty when nothing is stored', () => {
    const { result } = renderHook(() => useWatchlist());
    expect(result.current[0]).toEqual([]);
  });

  it('treats corrupt JSON as an empty list instead of throwing', () => {
    localStorage.setItem(STORAGE_KEY, '{not json');
    const { result } = renderHook(() => useWatchlist());
    expect(result.current[0]).toEqual([]);
  });

  it('treats a stored value that is not an array as an empty list', () => {
    localStorage.setItem(STORAGE_KEY, '{"a":1}');
    const { result } = renderHook(() => useWatchlist());
    expect(result.current[0]).toEqual([]);
  });

  it('keeps only non-empty strings, deduplicated, in stored order', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(['b', 5, '', 'a', null, 'b', true]));
    const { result } = renderHook(() => useWatchlist());
    expect(result.current[0]).toEqual(['b', 'a']);
  });

  it('adds a name, persists it, and toggles it back off', () => {
    const { result } = renderHook(() => useWatchlist());

    act(() => result.current[1]('kraken.xbtusd.1h'));
    expect(result.current[0]).toEqual(['kraken.xbtusd.1h']);
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]')).toEqual(['kraken.xbtusd.1h']);

    // The same call toggles it back off, and storage follows the state.
    act(() => result.current[1]('kraken.xbtusd.1h'));
    expect(result.current[0]).toEqual([]);
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]')).toEqual([]);
  });

  it('removes a name and persists the removal', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(['kraken.xbtusd.1h', 'example.pending.1d']));
    const { result } = renderHook(() => useWatchlist());
    expect(result.current[0]).toEqual(['kraken.xbtusd.1h', 'example.pending.1d']);

    act(() => result.current[1]('kraken.xbtusd.1h'));
    expect(result.current[0]).toEqual(['example.pending.1d']);
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]')).toEqual(['example.pending.1d']);
  });

  it('survives a remount: what one instance wrote, the next instance reads', () => {
    const first = renderHook(() => useWatchlist());
    act(() => first.result.current[1]('kraken.xbtusd.1h'));
    first.unmount();

    const second = renderHook(() => useWatchlist());
    expect(second.result.current[0]).toEqual(['kraken.xbtusd.1h']);
  });

  it('keeps working when storage refuses to write (private mode)', () => {
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = () => {
      throw new DOMException('QuotaExceededError');
    };
    try {
      const { result } = renderHook(() => useWatchlist());
      act(() => result.current[1]('kraken.xbtusd.1h'));
      // The in-memory list still works even though nothing could be written.
      expect(result.current[0]).toEqual(['kraken.xbtusd.1h']);
    } finally {
      Storage.prototype.setItem = original;
    }
  });
});
