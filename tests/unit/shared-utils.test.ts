import { describe, expect, it } from 'vitest';

import { isNonEmptyString, percentChange, roundTo, safeDivide } from '@harsh-quant-os/shared';

describe('percentChange', () => {
  it('computes ordinary growth', () => {
    expect(percentChange(100, 150)).toBe(50);
    expect(percentChange(200, 100)).toBe(-50);
  });

  it('returns 0 when both values are zero', () => {
    expect(percentChange(0, 0)).toBe(0);
  });

  it('does not silently coerce unbounded growth from zero', () => {
    expect(percentChange(0, 10)).toBe(Number.POSITIVE_INFINITY);
    expect(percentChange(0, -10)).toBe(Number.NEGATIVE_INFINITY);
  });

  it('rejects non-finite inputs', () => {
    expect(() => percentChange(Number.NaN, 1)).toThrow(RangeError);
    expect(() => percentChange(1, Number.POSITIVE_INFINITY)).toThrow(RangeError);
  });
});

describe('safeDivide', () => {
  it('divides normally', () => {
    expect(safeDivide(10, 4)).toBe(2.5);
  });

  it('returns the fallback for a zero denominator', () => {
    expect(safeDivide(1, 0)).toBe(0);
    expect(safeDivide(1, 0, -1)).toBe(-1);
  });

  it('returns the fallback for non-finite inputs', () => {
    expect(safeDivide(Number.NaN, 2, 7)).toBe(7);
    expect(safeDivide(1, Number.NaN, 7)).toBe(7);
  });
});

describe('roundTo', () => {
  it('rounds to the requested precision', () => {
    expect(roundTo(1.23456, 2)).toBe(1.23);
    expect(roundTo(12.345, 0)).toBe(12);
    expect(roundTo(1.005, 2)).toBe(1.01);
  });

  it('rejects invalid precision', () => {
    expect(() => roundTo(1, -1)).toThrow(RangeError);
    expect(() => roundTo(1, 1.5)).toThrow(RangeError);
    expect(() => roundTo(1, 16)).toThrow(RangeError);
  });

  it('rejects non-finite values', () => {
    expect(() => roundTo(Number.NaN, 2)).toThrow(RangeError);
  });
});

describe('isNonEmptyString', () => {
  it('accepts only trimmed non-empty strings', () => {
    expect(isNonEmptyString('a')).toBe(true);
    expect(isNonEmptyString('')).toBe(false);
    expect(isNonEmptyString('   ')).toBe(false);
    expect(isNonEmptyString(0)).toBe(false);
    expect(isNonEmptyString(null)).toBe(false);
  });
});
