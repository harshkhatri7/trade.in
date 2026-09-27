/**
 * Shared runtime utilities.
 *
 * Constraints:
 * - Pure and deterministic: same input, same output, no I/O.
 * - No `any`, no floating point surprises left unchecked.
 * - Financial calculations belong in the Python quant packages; the helpers
 *   here exist so UI and tooling agree on formatting/rounding conventions.
 */

/** Result of a division that would otherwise be undefined. */
export type Ratio = number;

/**
 * Percentage change from `previous` to `current`.
 *
 * Returns `0` when `previous` is `0` and `current` is `0`, and `Infinity`
 * when growth from zero is mathematically unbounded. Callers must handle the
 * non-finite case explicitly - it is never silently coerced.
 */
export function percentChange(previous: number, current: number): Ratio {
  if (!Number.isFinite(previous) || !Number.isFinite(current)) {
    throw new RangeError('percentChange requires finite inputs');
  }
  if (previous === 0) {
    return current === 0 ? 0 : Math.sign(current) * Number.POSITIVE_INFINITY;
  }
  return ((current - previous) / previous) * 100;
}

/**
 * Divide safely. Returns `fallback` instead of `NaN`/`Infinity` so that a bad
 * denominator can never propagate into a displayed or logged figure.
 */
export function safeDivide(numerator: number, denominator: number, fallback = 0): number {
  if (!Number.isFinite(numerator) || !Number.isFinite(denominator) || denominator === 0) {
    return fallback;
  }
  const result = numerator / denominator;
  return Number.isFinite(result) ? result : fallback;
}

/**
 * Round to a fixed number of decimal places using integer arithmetic, so that
 * `roundTo(1.005, 2)` behaves consistently with the Python quant layer.
 */
export function roundTo(value: number, decimals: number): number {
  if (!Number.isFinite(value)) {
    throw new RangeError('roundTo requires a finite value');
  }
  if (!Number.isInteger(decimals) || decimals < 0 || decimals > 15) {
    throw new RangeError('decimals must be an integer between 0 and 15');
  }
  const factor = 10 ** decimals;
  return Math.round((value + Number.EPSILON) * factor) / factor;
}

/** Narrow an unknown value to a non-empty string. */
export function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}
