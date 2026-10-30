"use client";

/**
 * QuantWorkspace — root container for the Quant tab.
 *
 * "Deterministic trading agents running quant algorithms": the 27 algorithms,
 * trade-intent ladder, execution. No LLM in the hot path.
 *
 * Renders the QuantWorkbench composer which lays out the 4 quadrants:
 *  A · Catalogue rail (left)        — pick from the 27 algorithms
 *  B · Workbench (center)           — configure params, preview plan, submit
 *  C · Active programs table        — what's running on which symbols
 *  D · Pending intents ladder       — approve / reject queue
 *
 * The older `TransactionsWorkspace.tsx` is still in the tree for reference
 * but no longer routed; FundingAllocationPanel and the LLM-flavored trigger
 * wiring it contained will get folded back in selectively.
 */

import { QuantWorkbench, type PendingQuantIntent } from "@/components/QuantWorkbench";
import { StrategyDeploymentPanel } from "@/components/StrategyDeploymentPanel";
import type { StrategyReviewSelection } from "@/lib/deployments";

export function QuantWorkspace({
  symbol,
  pendingIntent,
  strategyReview,
  onConsumePendingIntent
}: {
  symbol: string;
  /**
   * Research→execution handoff: non-null when the user just approved an idea
   * (drawer Buy/Sell, Morning Scan approve). Forwarded to QuantWorkbench,
   * which applies it once and then calls `onConsumePendingIntent`.
   */
  pendingIntent?: PendingQuantIntent | null;
  strategyReview?: StrategyReviewSelection | null;
  onConsumePendingIntent?: () => void;
}) {
  return (
    <section className="quant-workspace-root" aria-label="Quant workspace">
      <StrategyDeploymentPanel selection={strategyReview} />
      <QuantWorkbench
        symbol={symbol}
        pendingIntent={pendingIntent}
        onConsumePendingIntent={onConsumePendingIntent}
      />
    </section>
  );
}
