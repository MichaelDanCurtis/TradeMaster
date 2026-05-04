import { getMarketTickerItems, type MarketTickerItem } from "@/lib/workspace-data";

export function MarketTicker() {
  const tickerItems = getMarketTickerItems();

  return (
    <section className="market-ticker-strip" aria-label="Market ticker">
      <div className="market-ticker-track">
        {tickerItems.map((item) => (
          <TickerItem item={item} key={item.id} />
        ))}
      </div>
    </section>
  );
}

function TickerItem({ item }: { item: MarketTickerItem }) {
  const isPositive = item.change >= 0;

  return (
    <article className="market-ticker-item">
      <div className="ticker-copy">
        <strong>{item.label}</strong>
        <span>{formatTickerValue(item.value)}</span>
        <small className={isPositive ? "positive" : "negative"}>
          {formatSigned(item.change)} ({formatSigned(item.changePercent)}%)
        </small>
      </div>
      <TickerSparkline item={item} />
    </article>
  );
}

function TickerSparkline({ item }: { item: MarketTickerItem }) {
  const width = 86;
  const height = 34;
  const minValue = Math.min(...item.sparkline);
  const maxValue = Math.max(...item.sparkline);
  const valueRange = maxValue - minValue || 1;
  const points = item.sparkline
    .map((value, index) => {
      const x = (index / Math.max(item.sparkline.length - 1, 1)) * width;
      const y = height - ((value - minValue) / valueRange) * (height - 4) - 2;

      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");

  return (
    <svg
      aria-label={`${item.label} sparkline`}
      className={item.change >= 0 ? "ticker-sparkline positive" : "ticker-sparkline negative"}
      role="img"
      viewBox={`0 0 ${width} ${height}`}
    >
      <polyline points={points} />
    </svg>
  );
}

function formatTickerValue(value: number): string {
  return value.toLocaleString("en-US", {
    maximumFractionDigits: 3,
    minimumFractionDigits: 2
  });
}

function formatSigned(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toLocaleString("en-US", {
    maximumFractionDigits: 3,
    minimumFractionDigits: 2
  })}`;
}
