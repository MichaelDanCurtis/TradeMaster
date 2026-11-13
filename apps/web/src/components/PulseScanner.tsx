"use client";
import { useState } from "react";
import {
  age,
  pct,
  price,
  tone,
  volume,
  type PulseBoard,
  type PulseAnalysis,
} from "@/lib/market-pulse";
import type { SecurityIdentity } from "@/lib/pulse-workbench";

type Sort = "symbol" | "price" | "change" | "volume";
export function PulseScanner({
  board,
  identities,
  selected,
  onSelect,
  analysis,
  matched,
  now,
}: {
  board: PulseBoard | null;
  identities: Record<string, SecurityIdentity>;
  selected: string | null;
  onSelect: (symbol: string) => void;
  analysis: PulseAnalysis | null;
  matched: boolean;
  now: number;
}) {
  const [view, setView] = useState<"movers" | "gainers" | "losers" | "active">(
    "movers",
  );
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<Sort>("change");
  const [ascending, setAscending] = useState(false);
  const movers = [...(board?.gainers ?? []), ...(board?.losers ?? [])];
  const rows = (
    view === "active"
      ? (board?.activity ?? []).map((row) => ({
          symbol: row.symbol,
          price: row.price,
          change: row.change_pct,
          volume: row.screener_volume,
          asOf: row.price_at,
          quote: row,
        }))
      : movers
          .filter((row) => view === "movers" || row.side === view)
          .map((row) => ({
            symbol: row.symbol,
            price: row.price,
            change: row.change_pct,
            volume: row.snapshot.volume,
            asOf: row.as_of,
            quote: row.snapshot,
          }))
  )
    .filter((row) =>
      `${row.symbol} ${identities[row.symbol]?.name ?? ""}`
        .toLowerCase()
        .includes(query.toLowerCase()),
    )
    .sort((a, b) => {
      const av = a[sort],
        bv = b[sort];
      if (av == null) return bv == null ? 0 : 1;
      if (bv == null) return -1;
      const difference =
        typeof av === "string" && typeof bv === "string"
          ? av.localeCompare(bv)
          : Number(av) - Number(bv);
      return ascending ? difference : -difference;
    });
  function sortBy(key: Sort) {
    setSort(key);
    setAscending(sort === key ? !ascending : key === "symbol");
  }
  return (
    <section className="pulse-scanner pulse-panel" aria-label="Market scanner">
      <div className="terminal-panel-title">
        <strong>Market scanner</strong>
        <span>{rows.length} securities · SIP rankings</span>
      </div>
      <div className="pulse-scanner-tools">
        <div aria-label="Scanner view">
          {(
            [
              ["movers", "All movers"],
              ["gainers", "Gainers"],
              ["losers", "Losers"],
              ["active", "Most active"],
            ] as const
          ).map(([id, label]) => (
            <button
              type="button"
              key={id}
              aria-pressed={view === id}
              onClick={() => {
                setView(id);
                setSort(id === "active" ? "volume" : "change");
                setAscending(id === "losers");
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <input
          aria-label="Filter securities"
          placeholder="Filter symbol / company"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <div
        className="pulse-scanner-scroll"
        tabIndex={0}
        aria-label="Scrollable securities table"
      >
        <table>
          <thead>
            <tr>
              <th
                aria-sort={
                  sort === "symbol"
                    ? ascending
                      ? "ascending"
                      : "descending"
                    : "none"
                }
              >
                <button onClick={() => sortBy("symbol")}>
                  Symbol {sort === "symbol" ? (ascending ? "↑" : "↓") : ""}
                </button>
              </th>
              <th>Company</th>
              {(
                [
                  ["price", "Last"],
                  ["change", "Chg %"],
                  [
                    "volume",
                    view === "active"
                      ? "SIP vol."
                      : `${board?.feed.toUpperCase() ?? "—"} vol.`,
                  ],
                ] as const
              ).map(([key, label]) => (
                <th
                  key={key}
                  aria-sort={
                    sort === key
                      ? ascending
                        ? "ascending"
                        : "descending"
                      : "none"
                  }
                >
                  <button onClick={() => sortBy(key)}>
                    {label} {sort === key ? (ascending ? "↑" : "↓") : ""}
                  </button>
                </th>
              ))}
              <th>Gap %</th>
              <th>vs VWAP</th>
              <th>Catalyst</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const explanation =
                matched && analysis?.state === "completed"
                  ? analysis.receipt?.proposal?.explanations.find(
                      (item) => item.symbol === row.symbol,
                    )
                  : null;
              return (
                <tr
                  key={row.symbol}
                  className={row.symbol === selected ? "selected" : ""}
                  onClick={() => onSelect(row.symbol)}
                >
                  <th scope="row">
                    <button
                      type="button"
                      aria-label={`Inspect ${row.symbol}`}
                      aria-pressed={row.symbol === selected}
                      onClick={(e) => {
                        e.stopPropagation();
                        onSelect(row.symbol);
                      }}
                      onKeyDown={(e) => {
                        if (e.key !== "ArrowDown" && e.key !== "ArrowUp")
                          return;
                        e.preventDefault();
                        const index = rows.findIndex(
                          (item) => item.symbol === row.symbol,
                        );
                        const next =
                          rows[index + (e.key === "ArrowDown" ? 1 : -1)];
                        if (next) {
                          onSelect(next.symbol);
                          const tr = e.currentTarget.closest("tr");
                          (e.key === "ArrowDown"
                            ? tr?.nextElementSibling
                            : tr?.previousElementSibling
                          )
                            ?.querySelector("button")
                            ?.focus();
                        }
                      }}
                    >
                      {row.symbol}
                    </button>
                  </th>
                  <td
                    className="scanner-company"
                    title={
                      identities[row.symbol]?.name ?? "Company name unavailable"
                    }
                  >
                    {identities[row.symbol]?.name ?? "—"}
                  </td>
                  <td title={age(row.asOf, now)}>{price(row.price)}</td>
                  <td className={tone(row.change)}>{pct(row.change)}</td>
                  <td
                    title={`Volume timestamp: ${row.quote.day_at ?? "not supplied"}`}
                  >
                    {volume(row.volume)}
                  </td>
                  <td className={tone(row.quote.gap_pct)}>
                    {pct(row.quote.gap_pct)}
                  </td>
                  <td className={tone(row.quote.vwap_delta_pct)}>
                    {pct(row.quote.vwap_delta_pct)}
                  </td>
                  <td
                    className="scanner-catalyst"
                    title={
                      explanation?.summary ?? "No assessment for this capture"
                    }
                  >
                    {explanation
                      ? explanation.evidence === "insufficient"
                        ? "Unclear"
                        : explanation.driver.replaceAll("_", " ")
                      : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!rows.length && (
          <p className="pulse-placeholder">
            {query
              ? "No securities match your filter."
              : "No securities available in this view."}
          </p>
        )}
      </div>
      <div className="pulse-scanner-status">
        {view === "active"
          ? "SIP volume ranking"
          : "Top 25 gainers + 25 losers"}{" "}
        · {board?.feed.toUpperCase() ?? "—"} supplemental prices · select a row
        to link chart & news
      </div>
    </section>
  );
}
