import type { MarketRange } from "./market-data.ts";

export const CHART_RANGE_SEQUENCE: MarketRange[] = ["1D", "5D", "1M", "YTD", "1Y", "3Y", "5Y", "10Y"];

export function getWheelAdjustedRange(currentRange: MarketRange, deltaY: number): MarketRange {
  const currentIndex = CHART_RANGE_SEQUENCE.indexOf(currentRange);

  if (currentIndex === -1 || deltaY === 0) {
    return currentRange;
  }

  const direction = deltaY > 0 ? 1 : -1;
  const nextIndex = Math.min(Math.max(currentIndex + direction, 0), CHART_RANGE_SEQUENCE.length - 1);

  return CHART_RANGE_SEQUENCE[nextIndex];
}
