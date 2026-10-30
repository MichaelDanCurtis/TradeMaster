"use client";

import { useEffect, useMemo, useState } from "react";

import { createFundingAllocationReview, listFundingAllocationReviews } from "@/lib/api";

import {
  buildFundingAllocationReview,
  getFundingAllocationTrack,
  type FundingAllocationReview
} from "@/lib/funding-allocation";

type DurableFundingAllocationReview = {
  created_at?: string;
  id?: string;
  review_id?: string;
  status?: string;
  summary?: string;
  symbol?: string;
  title?: string;
};

type FundingReviewApiStatus = "loading" | "ready" | "saving" | "saved" | "local-only" | "unavailable";

export function FundingAllocationPanel({
  notional,
  symbol
}: {
  symbol: string;
  notional?: number;
}) {
  const [apiStatus, setApiStatus] = useState<FundingReviewApiStatus>("loading");
  const [savedReviews, setSavedReviews] = useState<DurableFundingAllocationReview[]>([]);
  const review = useMemo(
    () =>
      buildFundingAllocationReview({
        notional,
        symbol
      }),
    [notional, symbol]
  );
  const recentReviews = savedReviews.slice(0, 3);
  const fundingSource = getFundingAllocationTrack(review, "cash-source");
  const liabilityChecks = getFundingAllocationTrack(review, "liabilities");
  const taxQuestions = getFundingAllocationTrack(review, "tax-questions");
  const mandateFit = getFundingAllocationTrack(review, "mandate-fit");
  const complianceGate = getFundingAllocationTrack(review, "compliance-gate");

  useEffect(() => {
    let isCurrent = true;

    async function loadRecentReviews() {
      setApiStatus("loading");
      try {
        const catalog = await listFundingAllocationReviews({ limit: 5, symbol: review.symbol });
        const reviews = Array.isArray(catalog) ? catalog : catalog.reviews ?? [];
        if (isCurrent) {
          setSavedReviews(reviews);
          setApiStatus("ready");
        }
      } catch {
        if (isCurrent) {
          setSavedReviews([]);
          setApiStatus("unavailable");
        }
      }
    }

    void loadRecentReviews();

    return () => {
      isCurrent = false;
    };
  }, [review.symbol]);

  async function saveFundingReview() {
    setApiStatus("saving");
    try {
      const created = await createFundingAllocationReview({
        missingProviderFacts: review.missingProviderFacts,
        notional,
        payload: review,
        status: "provider_facts_missing",
        symbol: review.symbol,
        tracks: review.tracks as unknown as Record<string, unknown>[]
      });
      const reviewId = created.review_id;
      setSavedReviews((currentReviews) => [created, ...currentReviews.filter((item) => (item.review_id ?? item.id) !== reviewId)].slice(0, 5));
      setApiStatus("saved");
    } catch {
      setSavedReviews((currentReviews) => [
        {
          created_at: new Date().toISOString(),
          review_id: `local-${review.symbol}`,
          status: "local-only",
          summary: review.summary,
          symbol: review.symbol,
          title: review.title
        },
        ...currentReviews
      ]);
      setApiStatus("local-only");
    }
  }

  return (
    <article className="dashboard-home-panel funding-allocation-panel" aria-label="Funding Allocation Review">
      <div className="dashboard-panel-title">
        <span className="panel-kicker">Funding Allocation Review</span>
        <span className="panel-control-dot" aria-hidden="true" />
      </div>
      <header className="portfolio-review-header">
        <div>
          <h2>Private-office funding review</h2>
          <p>
            Operations and Private Office must confirm source of funds, liabilities, tax questions, mandate fit, and
            compliance approval before broker execution.
          </p>
        </div>
        <span>{review.symbol}</span>
      </header>
      <div className="dashboard-command-actions">
        <button className="primary-button" type="button" onClick={saveFundingReview} disabled={apiStatus === "saving"}>
          {apiStatus === "saving" ? "Saving review..." : "Save funding review"}
        </button>
        <span className="approval-badge required">Provider facts unavailable</span>
      </div>
      <p className={apiStatus === "local-only" || apiStatus === "unavailable" ? "error" : "run-id"}>
        {apiStatus === "saved"
          ? "Saved funding review to the durable review store."
          : apiStatus === "local-only"
            ? "Durable API unavailable; funding review is local-only and remains visible for this session."
            : apiStatus === "unavailable"
              ? "Durable API unavailable. Local review remains visible; save will keep it local-only."
              : "Provider facts missing. Review remains approval-gated until source-of-funds, tax, broker, and compliance facts are verified."}
      </p>
      <section className="portfolio-thesis-output" aria-label="Funding source">
        <ReviewSection review={review} title={fundingSource.title} body={fundingSource.finding} facts={fundingSource.requiredFacts} />
      </section>
      <section className="portfolio-thesis-output" aria-label="Liability checks">
        <ReviewSection
          review={review}
          title={liabilityChecks.title}
          body={liabilityChecks.finding}
          facts={liabilityChecks.requiredFacts}
        />
      </section>
      <section className="portfolio-thesis-output" aria-label="Tax questions">
        <ReviewSection review={review} title={taxQuestions.title} body={taxQuestions.finding} facts={taxQuestions.requiredFacts} />
      </section>
      <section className="portfolio-thesis-output" aria-label="Mandate fit">
        <ReviewSection review={review} title={mandateFit.title} body={mandateFit.finding} facts={mandateFit.requiredFacts} />
      </section>
      <section className="portfolio-provider-facts" aria-label="Compliance gate">
        <div className="dashboard-panel-title">
          <span className="panel-kicker">{complianceGate.title}</span>
          <span>{review.notionalLabel}</span>
        </div>
        <p>{complianceGate.finding}</p>
        <ul>
          {complianceGate.requiredFacts.map((fact) => (
            <li key={fact}>{fact}</li>
          ))}
        </ul>
      </section>
      <section className="portfolio-provider-facts" aria-label="Missing provider facts">
        <div className="dashboard-panel-title">
          <span className="panel-kicker">Missing provider facts</span>
        </div>
        <p>{review.summary}</p>
        <ul>
          {review.missingProviderFacts.map((fact) => (
            <li key={fact}>{fact}</li>
          ))}
        </ul>
      </section>
      <section className="portfolio-review-decisions" aria-label="Approval next steps">
        <div className="dashboard-panel-title">
          <span className="panel-kicker">Approval next steps</span>
        </div>
        <ol>
          {review.approvalNextSteps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      </section>
      <section className="portfolio-review-decisions" aria-label="Recent funding reviews">
        <div className="dashboard-panel-title">
          <span className="panel-kicker">Recent funding reviews</span>
        </div>
        {recentReviews.length > 0 ? (
          <ol>
            {recentReviews.map((item) => (
              <li key={item.review_id ?? item.id ?? item.title}>
                <strong>{item.title ?? `${item.symbol ?? review.symbol} funding review`}</strong>
                <span>{item.status ?? item.summary ?? "Saved funding review"}</span>
              </li>
            ))}
          </ol>
        ) : (
          <p>No recent funding reviews for {review.symbol} yet.</p>
        )}
      </section>
    </article>
  );
}

function ReviewSection({
  body,
  facts,
  review,
  title
}: {
  body: string;
  facts: string[];
  review: FundingAllocationReview;
  title: string;
}) {
  return (
    <>
      <div className="dashboard-panel-title">
        <span className="panel-kicker">{title}</span>
        <span>{review.notionalLabel}</span>
      </div>
      <p>{body}</p>
      <ul>
        {facts.map((fact) => (
          <li key={fact}>{fact}</li>
        ))}
      </ul>
    </>
  );
}
