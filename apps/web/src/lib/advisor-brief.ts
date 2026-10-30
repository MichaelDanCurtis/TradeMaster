import type { WatchlistItem } from "@/lib/types";
import type { NewsEvent } from "@/lib/workspace-data";

// NarrativeCard was previously exported from AdvisorNarrativePanel. The
// component was deleted in the v2 IA cleanup, but the brief-building logic
// is still useful (it composes "what to look at next" cards from holdings +
// news). Type inlined here so the brief stays portable.
export type NarrativeCardTone = "good" | "watch" | "blocked";
export type NarrativeCard = {
  label: string;
  title: string;
  body: string;
  tone: NarrativeCardTone;
};

export type PortfolioAdvisorBrief = {
  summary: string;
  cards: NarrativeCard[];
  statusItems: string[];
};

export function buildPortfolioAdvisorBrief({
  newsBySymbol,
  selectedSymbol,
  watchlistItems
}: {
  newsBySymbol: Record<string, NewsEvent[]>;
  selectedSymbol: string;
  watchlistItems: WatchlistItem[];
}): PortfolioAdvisorBrief {
  const normalizedSelected = selectedSymbol.toUpperCase();
  const pricedItems = watchlistItems.filter((item) => typeof item.price === "number" && typeof item.changePercent === "number");
  const gainers = pricedItems.filter((item) => (item.changePercent ?? 0) >= 0);
  const decliners = pricedItems.filter((item) => (item.changePercent ?? 0) < 0);
  const largestMove = pricedItems
    .slice()
    .sort((left, right) => Math.abs(right.changePercent ?? 0) - Math.abs(left.changePercent ?? 0))[0];
  const newsEvents = Object.values(newsBySymbol)
    .flat()
    .sort((left, right) => right.relevance - left.relevance);
  const topNews = newsEvents[0];
  const negativeNews = newsEvents.find((event) => event.sentiment === "negative");
  const focusNews = newsBySymbol[normalizedSelected]?.[0];
  const watchedCount = watchlistItems.length;
  const quoteStatus =
    pricedItems.length > 0
      ? `${pricedItems.length}/${watchedCount} quotes live`
      : "quotes pending";

  const summary =
    pricedItems.length > 0
      ? `${watchedCount} watched names are in the morning review. ${gainers.length} are green and ${decliners.length} are red; ${
          largestMove ? `${largestMove.symbol} is the largest visible mover at ${formatPercent(largestMove.changePercent)}.` : "no major quote move is visible yet."
        } ${topNews ? `Top news signal: ${topNews.title}.` : "No news signal is loaded yet."}`
      : `${watchedCount} watched names are loaded, but the room is still waiting for provider-backed quotes before making a portfolio-level read.`;

  return {
    summary,
    cards: [
      {
        body:
          pricedItems.length > 0
            ? `${gainers.length} green, ${decliners.length} red, ${pricedItems.length} with provider-backed quotes. ${
                largestMove ? `${largestMove.symbol} is the name to look at first.` : "No quote has a meaningful move yet."
              }`
            : "Quotes are not hydrated yet, so this room should avoid claiming portfolio movement.",
        label: "Portfolio read",
        title: `${watchedCount} watched names`,
        tone: decliners.length > gainers.length ? "watch" : "good"
      },
      {
        body: topNews
          ? `${topNews.source} flags ${topNews.sentiment} context with ${topNews.relevance}/100 relevance. ${topNews.summary}`
          : "No news events are loaded for the watchlist yet.",
        label: "News signal",
        title: negativeNews ? `${negativeNews.symbol}: negative news watch` : topNews ? topNews.title : "No news loaded",
        tone: negativeNews ? "watch" : topNews ? "good" : "blocked"
      },
      {
        body: focusNews
          ? `${normalizedSelected} remains the selected research context. ${focusNews.summary}`
          : `${normalizedSelected} is selected, but there is no loaded news context for it yet.`,
        label: "Selected focus",
        title: normalizedSelected,
        tone: focusNews?.sentiment === "negative" ? "watch" : "good"
      }
    ],
    statusItems: [
      `${watchedCount} symbols watched`,
      quoteStatus,
      topNews ? `${newsEvents.length} news items scanned` : "news pending"
    ]
  };
}

function formatPercent(value: number | null): string {
  return typeof value === "number" ? `${value >= 0 ? "+" : ""}${value.toFixed(2)}%` : "unknown";
}
