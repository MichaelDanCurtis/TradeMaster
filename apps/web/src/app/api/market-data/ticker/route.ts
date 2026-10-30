import { NextResponse } from "next/server";

import { WATCHLIST } from "@/data/watchlist";
import { createTickerItemsFromSnapshots, fetchProviderBackedMarketSnapshot } from "@/lib/market-data-provider";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const requestedSymbols = parseRequestedSymbols(new URL(request.url).searchParams.get("symbols"));
  const labelBySymbol = Object.fromEntries(WATCHLIST.map((item) => [item.symbol, item.name]));
  const settledSnapshots = await Promise.allSettled(
    requestedSymbols.map((symbol) => fetchProviderBackedMarketSnapshot(symbol, "1D"))
  );
  const snapshots = settledSnapshots
    .filter((result): result is PromiseFulfilledResult<Awaited<ReturnType<typeof fetchProviderBackedMarketSnapshot>>> => result.status === "fulfilled")
    .map((result) => result.value);

  if (snapshots.length === 0) {
    return NextResponse.json(
      {
        errors: settledSnapshots
          .filter((result): result is PromiseRejectedResult => result.status === "rejected")
          .map((result) => (result.reason instanceof Error ? result.reason.message : "Provider request failed")),
        items: [],
        provider: "unavailable"
      },
      { status: 503, headers: { "Cache-Control": "no-store" } }
    );
  }

  return NextResponse.json(
    {
      items: createTickerItemsFromSnapshots(snapshots, labelBySymbol),
      provider: "alpaca"
    },
    {
      headers: {
        "Cache-Control": "no-store"
      }
    }
  );
}

function parseRequestedSymbols(value: string | null): string[] {
  if (!value) {
    return WATCHLIST.map((item) => item.symbol);
  }

  const symbols = value
    .split(",")
    .map((symbol) => symbol.trim().toUpperCase())
    .filter((symbol) => /^[A-Z0-9.-]{1,12}$/.test(symbol));

  return Array.from(new Set(symbols)).slice(0, 12);
}
