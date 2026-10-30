# Reviewed source corrections

Verified 2026-09-05. Synthetic software acceptance; no remote broker call, cash movement or order submission.

## Implemented behavior

Conflicting normalized activity versions sharing a source ID remain immutable. New additive correction-review and approval tables select an observed version for later calculations. Reviews pin the full candidate set, current account receipt, existing approvals and loaded calculation build. They show the prior and proposed source payloads, ledger impact, remaining discrepancies and affected historical balance observations. Approval requires the exact displayed hash, account, named actor and reason. A five-minute review expires; a newer account receipt, source version or competing approval requires a new review. Research-room callers cannot preview or approve these account corrections.

The proposal selects the version in the latest account receipt, matched to a retained economic version. It cannot invent a replacement event, select an arbitrary favorable candidate or approve unresolved ledger discrepancies. The account observer expands its activity interval to revisit outstanding corrections older than the normal seven-day overlap, within the adapter's existing retrieval bounds.

Approval is an immutable decision, not a new account observation. The prior report stays unchanged until the account is reconciled again. Reconciliation identity includes accepted correction IDs, so replaying the same source request after approval produces a new receipt; repeating it again is idempotent. Original activities, revision receipts and historical reports remain saved. Retained source and review payloads are checked against their content hashes.

New revisions and reversions to an already known version both require another review. A later batch which omits the conflicted source cannot silently clear that requirement.

## Historical valuations

A retroactive source correction can conflict with a balance previously reported by the broker. The review compares both selected source sets against the actual saved observations. It may exclude an older observation from the new calculation only when that observation reconciles under the prior source selection and develops a cash or position mismatch under the correction. Previously reviewed exclusions remain excluded only while they still conflict; a later correction can restore an observation which reconciles again.

Unrelated prior discrepancies and conflicting snapshots at the same timestamp cannot be waived. The latest balance must reconcile and is never excluded by this process. No opening baseline is replaced. No historical cash balance, position mark or price is fabricated. The current account and deployment performance disclosures identify excluded historical marks; drawdown remains scoped to observed valuations. Missing contemporaneous external-flow valuations remain unknown even after the corrected cash movement reconciles.

## UI and API

Performance includes a Source corrections panel with a typed comparison table, original payload/fingerprint inspection, calculation impact, affected/restored observation references, explicit reason and approval, and saved approval inspection. A newly loaded account receipt clears a stale proposal or success message. Abortable requests stop when the component unmounts or the account observation changes.

Routes under `/api/paper-accounting/accounts/{key}/corrections` provide GET history, POST `/preview`, and POST `/{review_id}/approve`. Read permission and the existing paper-account-review grant are checked separately. Reconciliation remains the existing account-observation action and never gains broker submission authority.

## Verification

- Broad backend regression: **445 passed, 12 explicitly skipped native checks**, one existing pinned-test-model warning. `/tmp/trademaster-corrections-regression.log`. This preceded the final restoration and conflicting-snapshot additions.
- Final focused corrections/accounting/protection/deployment-performance/native-HTTP regression: **50 passed**, `/tmp/trademaster-corrections-finalchecks.log`. The narrower final corrections/accounting/protection run passed **27**, `/tmp/trademaster-corrections-focused-final.log`; these suites overlap.
- Frontend: **160 passed**, `/tmp/trademaster-corrections-webtests.log`, before the browser-driven saved-review presentation refinement. The final production build passed with four existing unrelated warnings, `/tmp/trademaster-corrections-webbuild-final.log`.
- Tests cover approval, exact hashes/account, expiry, repeat approval, restart, immutability, newer revisions, source reversion, omitted-source batches, expanded correction coverage start, competing approvals/new receipts, current and unrelated historical discrepancies, restoration of valid marks, conflicting same-time snapshots, unknown flow valuations and room grants.

The browser used `/tmp/trademaster-corrections-ui/research.db`, seeded once with a USD 1,000 baseline. A synthetic fee changed from USD 1 to USD 2. The displayed comparison was approved with an explicit engineering-test reason; the existing conflicted receipt stayed unchanged until a fresh reconciliation produced USD -2 P&L and -0.2% return. After an API restart and production rebuild, a later USD 3 version required another review and yielded USD -3 / -0.3%. A further observed reversion to USD 1 required a third review, restored the original matching balance observation and yielded USD -1 / -0.1%.

The final database independently verifies one immutable original source (`-1`), two retained revisions, three correction approvals and seven reconciliation receipts. The initial report still contains its original USD -1 P&L, and its balance timestamp appears again in the final curve. Verification output: `/tmp/trademaster-corrections-ui/verification.json`.

Account: `90fe46839df22ccdf2f33a9a62c62a522ed7364464b536f8b4462e5ef3c43afe`. Initial receipt: `par_361a86f257d2427fbe091a74341ab2f1`; initial conflict: `par_324043b4f06d40589a181d4886393397`. Final reviewed comparison and saved history were visually inspected in `/tmp/trademaster-corrections-ui/proposal-final.png` and `history-expanded.png`. Keyboard preview/approval/history interaction, API restart, new-revision blocking, restored-observation disclosure and post-approval refresh were verified. No application exceptions, unexpected alerts or page-width overflow remained. Two browser-script variable redeclaration errors were corrected by scoping the inspection expressions; these were tooling errors, not application exceptions. Browser/API/web test processes were stopped afterward.

## Remaining limits

This resolves retained normalized versions sharing a source ID. Provider-specific trade busts, replacement IDs, deleted records and native correction timing still need verified adapter semantics; unsupported records remain explicit discrepancies. It does not create a manual journal-entry editor or allow a user to waive an unexplained balance. The current UI returns the latest 50 previews/approvals, and review proposals are bounded to 100 conflicted source events; history capacity remains a release requirement.

Genuine research datasets, provider coverage/entitlements, positive eligible promotion, provider-backed prospective scheduling and the full release walkthrough remain unfinished. These correctness fixtures do not establish investment evidence or complete the implementation goal.
