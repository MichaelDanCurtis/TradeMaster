import { NextResponse } from "next/server";

import { WATCHLIST } from "@/data/watchlist";
import { createTickerItemsFromSnapshots, fetchProviderBackedMarketSnapshot } from "@/lib/market-data-provider";

export const dynamic = "force-dynamic";

export async function GET() {
  const labelBySymbol = Object.fromEntries(WATCHLIST.map((item) => [item.symbol, item.name]));
  const snapshots = await Promise.all(
    WATCHLIST.map((item) => fetchProviderBackedMarketSnapshot(item.symbol, "1D"))
  );

  return NextResponse.json(
    {
      items: createTickerItemsFromSnapshots(snapshots, labelBySymbol),
      provider: snapshots.some((snapshot) => snapshot.provider !== "simulated") ? "alpaca" : "simulated"
    },
    {
      headers: {
        "Cache-Control": "no-store"
      }
    }
  );
}
