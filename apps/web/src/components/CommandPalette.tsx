"use client";

/**
 * CommandPalette — TradingView/Webull-class command bar.
 *
 * Cmd+K (Ctrl+K outside macOS) opens the palette anywhere in the shell. The
 * palette is a centered modal (560px wide, max 480px tall, 20vh from the top).
 * Type to filter Symbols / Tabs / Actions. Arrow keys + Enter to activate.
 *
 * Symbol data source:
 *   - Watchlist items (always available, passed in as a prop).
 *   - Portfolio holdings (lazily fetched once per mount via
 *     `listPortfolioHoldings`, cached for 60s in a module-level cache so the
 *     palette feels instant on subsequent opens).
 *
 * Tab actions, symbol jumps, and the dynamic "Research X / Buy X / Sell X"
 * action rows are wired through caller-provided handlers — the palette never
 * touches global state directly.
 *
 * SymbolDetailDrawer fallback:
 *   The drawer is being built in a parallel agent and may not be wired yet.
 *   If `onOpenSymbolDetail` is not a function, the palette silently falls back
 *   to `onResearchSymbol(symbol)` so symbol clicks always go somewhere useful.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent
} from "react";

import { listPortfolioHoldings } from "@/lib/api";
import type { WatchlistItem } from "@/lib/types";
import type { WorkspaceId } from "@/lib/workspace-data";

// ---------------------------------------------------------------------------
// Public contract — matches the brief in TRADEMASTER_VISION-derived task spec.
// ---------------------------------------------------------------------------

export type CommandPalettePaletteTab = Exclude<WorkspaceId, never>; // alias

export type CommandPaletteProps = {
  isOpen: boolean;
  onClose: () => void;
  onSelectTab: (tab: "portfolio" | "research" | "quant" | "settings") => void;
  /**
   * Open the SymbolDetailDrawer for `symbol`. The drawer is built by a
   * parallel agent — if this prop isn't supplied we fall back to switching to
   * Research with `symbol` selected.
   */
  onOpenSymbolDetail?: (symbol: string) => void;
  onResearchSymbol: (symbol: string) => void;
  onTradeSymbol: (input: { symbol: string; side: "buy" | "sell" }) => void;
  /**
   * Watchlist items passed in from MarketShell. The palette uses these as the
   * always-available symbol source so it can render before holdings load.
   */
  watchlistItems?: WatchlistItem[];
};

// ---------------------------------------------------------------------------
// Module-level holdings cache (60s TTL). Survives re-mounts within a session
// so popping the palette open repeatedly doesn't pound the holdings endpoint.
// ---------------------------------------------------------------------------

type CachedHoldings = {
  fetchedAt: number;
  symbols: PaletteSymbol[];
};

let HOLDINGS_CACHE: CachedHoldings | null = null;
const HOLDINGS_TTL_MS = 60_000;

type PaletteSymbol = {
  symbol: string;
  name: string;
  price: number | null;
  source: "watchlist" | "holding";
};

type PaletteItem =
  | { kind: "symbol"; id: string; symbol: PaletteSymbol }
  | { kind: "tab"; id: string; tab: WorkspaceId; label: string; shortcut: string }
  | {
      kind: "action";
      id: string;
      label: string;
      action: () => void;
    };

type PaletteSection = {
  id: "symbols" | "tabs" | "actions";
  heading: string;
  items: PaletteItem[];
};

const TAB_ROWS: { tab: WorkspaceId; label: string; shortcut: string }[] = [
  { tab: "portfolio", label: "Portfolio", shortcut: "1" },
  { tab: "research", label: "Research", shortcut: "2" },
  { tab: "quant", label: "Quant", shortcut: "3" },
  { tab: "settings", label: "Settings", shortcut: "4" }
];

function isMacPlatform(): boolean {
  if (typeof navigator === "undefined") return false;
  return /Mac|iPod|iPhone|iPad/.test(navigator.platform);
}

function shortcutPrefix(): string {
  return isMacPlatform() ? "Cmd" : "Ctrl";
}

function fuzzyMatch(haystack: string, needle: string): boolean {
  if (needle.length === 0) return true;
  const lowerHaystack = haystack.toLowerCase();
  const lowerNeedle = needle.toLowerCase();
  if (lowerHaystack.includes(lowerNeedle)) return true;

  // Loose subsequence match — keeps "nv" matching "NVDA" etc.
  let searchIndex = 0;
  for (const character of lowerHaystack) {
    if (character === lowerNeedle[searchIndex]) {
      searchIndex += 1;
      if (searchIndex === lowerNeedle.length) return true;
    }
  }
  return false;
}

function formatPrice(price: number | null): string {
  if (price === null || Number.isNaN(price)) return "—";
  if (price >= 1000) return `$${price.toFixed(0)}`;
  return `$${price.toFixed(2)}`;
}

function normalizeQuery(query: string): string {
  return query.trim().toUpperCase();
}

export function CommandPalette({
  isOpen,
  onClose,
  onSelectTab,
  onOpenSymbolDetail,
  onResearchSymbol,
  onTradeSymbol,
  watchlistItems = []
}: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [holdings, setHoldings] = useState<PaletteSymbol[]>(() => HOLDINGS_CACHE?.symbols ?? []);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);

  // Reset query and selection every time the palette opens. Also lazy-fetch
  // holdings on first open (or after cache expiry).
  useEffect(() => {
    if (!isOpen) return;

    setQuery("");
    setSelectedIndex(0);

    const now = Date.now();
    const cacheFresh = HOLDINGS_CACHE && now - HOLDINGS_CACHE.fetchedAt < HOLDINGS_TTL_MS;

    if (cacheFresh && HOLDINGS_CACHE) {
      setHoldings(HOLDINGS_CACHE.symbols);
      return;
    }

    let cancelled = false;
    listPortfolioHoldings()
      .then((catalog) => {
        if (cancelled) return;
        const mapped: PaletteSymbol[] = catalog.holdings
          .filter((holding): holding is typeof holding & { symbol: string } => Boolean(holding.symbol))
          .map((holding) => ({
            symbol: holding.symbol!.toUpperCase(),
            name: holding.name ?? holding.symbol!.toUpperCase(),
            price: holding.price,
            source: "holding"
          }));
        HOLDINGS_CACHE = { fetchedAt: Date.now(), symbols: mapped };
        setHoldings(mapped);
      })
      .catch(() => {
        // Holdings provider may not be configured — that's fine; palette still
        // works with the watchlist subset alone.
      });

    return () => {
      cancelled = true;
    };
  }, [isOpen]);

  // Focus the search input as soon as the palette mounts.
  useEffect(() => {
    if (!isOpen) return;
    const handle = window.requestAnimationFrame(() => {
      inputRef.current?.focus();
    });
    return () => window.cancelAnimationFrame(handle);
  }, [isOpen]);

  // Listen for ESC + "/" while the palette is open. (Cmd+K / number shortcuts
  // are owned by MarketShell so they work whether or not the palette is open.)
  useEffect(() => {
    if (!isOpen) return;

    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key === "/" && document.activeElement !== inputRef.current) {
        event.preventDefault();
        inputRef.current?.focus();
      }
    }

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isOpen, onClose]);

  // Combined symbol set, deduped by symbol code.
  const allSymbols = useMemo<PaletteSymbol[]>(() => {
    const seen = new Map<string, PaletteSymbol>();
    for (const item of watchlistItems) {
      const code = item.symbol.toUpperCase();
      seen.set(code, {
        symbol: code,
        name: item.name,
        price: item.price,
        source: "watchlist"
      });
    }
    for (const holding of holdings) {
      const code = holding.symbol.toUpperCase();
      if (!seen.has(code)) {
        seen.set(code, holding);
      }
    }
    return Array.from(seen.values());
  }, [watchlistItems, holdings]);

  // Open-symbol-detail with graceful fallback to research.
  const openSymbolDetail = useCallback(
    (symbol: string) => {
      const normalizedSymbol = symbol.toUpperCase();
      if (typeof onOpenSymbolDetail === "function") {
        try {
          onOpenSymbolDetail(normalizedSymbol);
          return;
        } catch {
          // Fall through to research if the drawer handler throws.
        }
      }
      onResearchSymbol(normalizedSymbol);
    },
    [onOpenSymbolDetail, onResearchSymbol]
  );

  // Build the filtered sections every render. Sections are cheap and the
  // structure makes keyboard navigation trivial — flatten to one ordered list
  // of activatable items.
  const sections = useMemo<PaletteSection[]>(() => {
    const trimmedQuery = query.trim();
    const upperQuery = normalizeQuery(query);

    const symbolItems: PaletteItem[] = allSymbols
      .filter(
        (entry) =>
          trimmedQuery.length === 0 ||
          fuzzyMatch(entry.symbol, trimmedQuery) ||
          fuzzyMatch(entry.name, trimmedQuery)
      )
      .slice(0, 8)
      .map((symbol) => ({ kind: "symbol", id: `symbol:${symbol.symbol}`, symbol }));

    const tabItems: PaletteItem[] = TAB_ROWS.filter((tab) =>
      trimmedQuery.length === 0 ? true : fuzzyMatch(tab.label, trimmedQuery)
    ).map((tab) => ({
      kind: "tab",
      id: `tab:${tab.tab}`,
      tab: tab.tab,
      label: tab.label,
      shortcut: tab.shortcut
    }));

    const actionItems: PaletteItem[] = [];
    if (upperQuery.length > 0) {
      const symbolForAction = upperQuery.replace(/\s+/g, "");
      if (symbolForAction.length > 0 && symbolForAction.length <= 8) {
        actionItems.push({
          kind: "action",
          id: `action:research:${symbolForAction}`,
          label: `Research ${symbolForAction}`,
          action: () => {
            onResearchSymbol(symbolForAction);
            onClose();
          }
        });
        actionItems.push({
          kind: "action",
          id: `action:buy:${symbolForAction}`,
          label: `Buy ${symbolForAction} in Quant`,
          action: () => {
            onTradeSymbol({ symbol: symbolForAction, side: "buy" });
            onClose();
          }
        });
        actionItems.push({
          kind: "action",
          id: `action:sell:${symbolForAction}`,
          label: `Sell ${symbolForAction} in Quant`,
          action: () => {
            onTradeSymbol({ symbol: symbolForAction, side: "sell" });
            onClose();
          }
        });
      }
    }

    const built: PaletteSection[] = [];
    if (symbolItems.length > 0) {
      built.push({ id: "symbols", heading: "Symbols", items: symbolItems });
    }
    if (tabItems.length > 0) {
      built.push({ id: "tabs", heading: "Tabs", items: tabItems });
    }
    if (actionItems.length > 0) {
      built.push({ id: "actions", heading: "Actions", items: actionItems });
    }
    return built;
  }, [allSymbols, onClose, onResearchSymbol, onTradeSymbol, query]);

  const flatItems = useMemo<PaletteItem[]>(
    () => sections.flatMap((section) => section.items),
    [sections]
  );

  // Clamp the selection whenever the filtered list shrinks.
  useEffect(() => {
    if (flatItems.length === 0) {
      if (selectedIndex !== 0) setSelectedIndex(0);
      return;
    }
    if (selectedIndex >= flatItems.length) {
      setSelectedIndex(0);
    }
  }, [flatItems.length, selectedIndex]);

  // Scroll the selected row into view as the user arrow-navigates.
  useEffect(() => {
    const node = itemRefs.current[selectedIndex];
    if (node && typeof node.scrollIntoView === "function") {
      node.scrollIntoView({ block: "nearest" });
    }
  }, [selectedIndex]);

  const activateItem = useCallback(
    (item: PaletteItem) => {
      if (item.kind === "symbol") {
        openSymbolDetail(item.symbol.symbol);
        onClose();
        return;
      }
      if (item.kind === "tab") {
        onSelectTab(item.tab as "portfolio" | "research" | "quant" | "settings");
        onClose();
        return;
      }
      item.action();
    },
    [onClose, onSelectTab, openSymbolDetail]
  );

  function onInputKeyDown(event: ReactKeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (flatItems.length === 0) return;
      setSelectedIndex((current) => (current + 1) % flatItems.length);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      if (flatItems.length === 0) return;
      setSelectedIndex((current) => (current - 1 + flatItems.length) % flatItems.length);
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      const item = flatItems[selectedIndex];
      if (item) activateItem(item);
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
    }
  }

  if (!isOpen) return null;

  const macPrefix = shortcutPrefix();
  let globalRowIndex = 0;

  return (
    <div
      className="command-palette-backdrop"
      onClick={onClose}
      role="presentation"
    >
      <section
        aria-label="Command palette"
        aria-modal="true"
        className="command-palette"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
      >
        <header className="command-palette-search">
          <span className="command-palette-search-icon" aria-hidden="true">
            ⌕
          </span>
          <input
            aria-label="Command search"
            className="command-palette-input"
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={onInputKeyDown}
            placeholder="Type to search symbols, tabs, actions…"
            ref={inputRef}
            type="text"
            value={query}
          />
          <span className="command-palette-hint" aria-hidden="true">
            ↵ to go
          </span>
        </header>
        <div className="command-palette-list" role="listbox">
          {sections.length === 0 ? (
            <div className="command-palette-empty">No matches</div>
          ) : (
            sections.map((section) => (
              <div className="command-palette-section" key={section.id}>
                <div className="command-palette-section-heading">{section.heading}</div>
                {section.items.map((item) => {
                  const rowIndex = globalRowIndex;
                  globalRowIndex += 1;
                  const selected = rowIndex === selectedIndex;
                  return (
                    <button
                      aria-selected={selected}
                      className={
                        selected ? "command-palette-item selected" : "command-palette-item"
                      }
                      key={item.id}
                      onClick={() => activateItem(item)}
                      onMouseEnter={() => setSelectedIndex(rowIndex)}
                      ref={(node) => {
                        itemRefs.current[rowIndex] = node;
                      }}
                      role="option"
                      type="button"
                    >
                      {renderItem(item, macPrefix)}
                    </button>
                  );
                })}
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}

function renderItem(item: PaletteItem, macPrefix: string) {
  if (item.kind === "symbol") {
    return (
      <>
        <span className="command-palette-symbol-code">{item.symbol.symbol}</span>
        <span className="command-palette-symbol-name">{item.symbol.name}</span>
        <span className="command-palette-symbol-price">{formatPrice(item.symbol.price)}</span>
      </>
    );
  }
  if (item.kind === "tab") {
    return (
      <>
        <span className="command-palette-tab-label">{item.label}</span>
        <span className="command-palette-shortcut">
          {macPrefix === "Cmd" ? "⌘" : "Ctrl+"}
          {item.shortcut}
        </span>
      </>
    );
  }
  return (
    <>
      <span className="command-palette-action-label">{item.label}</span>
      <span className="command-palette-action-arrow" aria-hidden="true">
        →
      </span>
    </>
  );
}
