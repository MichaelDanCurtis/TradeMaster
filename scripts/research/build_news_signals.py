"""Offline, reproducible news normalization, local FinBERT scoring and snapshots."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

from tradingagents.research.news_signals import normalize_article, snapshot, validate_tone


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path, payload):
    with path.open("x") as handle:
        handle.write(json.dumps(payload, indent=2, allow_nan=False) + "\n")


def normalize(root):
    receipt = json.loads((root / "receipt.json").read_text())
    articles, quarantine, seen = [], [], {}
    for page in receipt["pages"]:
        name = page["file"]
        if Path(name).name != name:
            raise ValueError("Unexpected capture path")
        path = root / name
        if sha(path) != page["sha256"]:
            raise ValueError("Capture hash mismatch")
        for index, raw in enumerate(json.loads(path.read_text())["news"]):
            try:
                row = normalize_article(raw, page["retrieved_at"], page["sha256"])
            except (ValueError, KeyError, TypeError) as error:
                quarantine.append({"file": name, "row": index, "reason": type(error).__name__})
                continue
            if row["version_id"] not in seen:
                seen[row["version_id"]] = row
                articles.append(row)
    result = {"receipt_sha256": sha(root / "receipt.json"), "articles": articles,
              "quarantine": quarantine, "duplicate_versions": receipt["article_count"] - len(articles) - len(quarantine),
              "endpoint_complete": receipt["complete"],
              "qualified_historical_archive": False,
              "note": "Current article versions and provider ticker tags; original revision history and issuer identity are unverified."}
    write_new(root / "articles.json", result)
    print(json.dumps({"normalized_articles": len(articles), "quarantine": len(quarantine), "endpoint_complete": receipt["complete"]}), flush=True)
    return result


def score(root, revision, device, batch_size):
    # No provider text is sent to a hosted model. Model code is never trusted.
    import re
    import torch
    import transformers
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("Supply an immutable Hugging Face commit SHA")
    if (root / "tones.json").exists():
        raise ValueError("Refusing to overwrite classifier evidence")
    source = json.loads((root / "articles.json").read_text())
    # Headline sentiment cannot disambiguate a multi-issuer article.
    articles = [a for a in source["articles"] if len(a["symbols"]) == 1]
    model_id = "ProsusAI/finbert"
    torch.set_num_threads(4)
    tokenizer = AutoTokenizer.from_pretrained(model_id, revision=revision, trust_remote_code=False)
    model = AutoModelForSequenceClassification.from_pretrained(model_id, revision=revision, trust_remote_code=False).to(device).eval()
    labels = {int(k): v.lower() for k, v in model.config.id2label.items()}
    if set(labels.values()) != {"positive", "negative", "neutral"}:
        raise ValueError("Unexpected classifier labels")
    records, cache = {}, {}
    for offset in range(0, len(articles), batch_size):
        batch = articles[offset:offset + batch_size]
        texts = list(dict.fromkeys(a["headline"] for a in batch if a["headline"] not in cache))
        if texts:
            inputs = tokenizer(texts, return_tensors="pt", padding=True, truncation=True, max_length=256).to(device)
            with torch.inference_mode():
                probabilities = torch.softmax(model(**inputs).logits.float(), dim=-1).cpu().tolist()
            cache.update({text: {labels[i]: p for i, p in enumerate(values)} for text, values in zip(texts, probabilities)})
        completed = datetime.now(timezone.utc).isoformat()
        for article in batch:
            row = {"version_id": article["version_id"], "probabilities": cache[article["headline"]],
                   "completed_at": completed, "model": model_id, "revision": revision}
            records[article["version_id"]] = validate_tone(row, article)
        if offset % (batch_size * 20) == 0:
            print(f"Classified {min(offset + batch_size, len(articles))}/{len(articles)} single-ticker headlines", flush=True)
    result = {"articles_sha256": sha(root / "articles.json"), "model": model_id, "revision": revision,
              "device": device, "torch": torch.__version__, "transformers": transformers.__version__,
              "python": sys.version, "max_tokens": 256, "batch_size": batch_size, "records": records,
              "meaning": "Headline text-label probabilities, not issuer-specific direction or return probabilities.",
              "historical_model_training_contamination": "Not excluded; retrospective research only."}
    write_new(root / "tones.json", result)
    print(json.dumps({"classified": len(records), "device": device}), flush=True)


def load_verified(root):
    source = json.loads((root / "articles.json").read_text())
    if sha(root / "receipt.json") != source["receipt_sha256"]:
        raise ValueError("Receipt changed after normalization")
    receipt = json.loads((root / "receipt.json").read_text())
    for page in receipt["pages"]:
        if Path(page["file"]).name != page["file"] or sha(root / page["file"]) != page["sha256"]:
            raise ValueError("Raw capture changed")
    result = json.loads((root / "tones.json").read_text())
    if sha(root / "articles.json") != result["articles_sha256"]:
        raise ValueError("Articles changed after inference")
    by_id = {a["version_id"]: a for a in source["articles"]}
    for identifier, tone in result["records"].items():
        validate_tone(tone, by_id[identifier])
    return source, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["normalize", "score", "snapshot"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--revision")
    parser.add_argument("--device", choices=["cpu", "mps"], default="cpu")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--cutoff")
    parser.add_argument("--evidence-mode", choices=["observed", "retrospective_proxy"], default="observed")
    parser.add_argument("--symbols", default="AAPL,JPM,XOM,UNH,CAT,WMT,NEE,AMT,LIN,DIS,UPS,NVDA")
    args = parser.parse_args()
    if args.mode == "normalize":
        normalize(args.root)
    elif args.mode == "score":
        if not args.revision or not 1 <= args.batch_size <= 128:
            parser.error("score requires --revision and a batch size between 1 and 128")
        score(args.root, args.revision, args.device, args.batch_size)
    else:
        if not args.cutoff:
            parser.error("snapshot requires --cutoff")
        source, tones = load_verified(args.root)
        rows = [snapshot(source["articles"], tones["records"], symbol, args.cutoff,
                         mode=args.evidence_mode, coverage_complete=False)
                for symbol in args.symbols.split(",")]
        # Snapshot coverage must be assessed against capture bounds by the caller;
        # pagination completion alone cannot establish arbitrary time-window coverage.
        write_new(args.root / "snapshots.json", {"rows": rows, "articles_sha256": sha(args.root / "articles.json"),
                                                "tones_sha256": sha(args.root / "tones.json")})
        print(json.dumps([{k: r[k] for k in ["symbol", "headline_cluster_count", "scored_single_ticker_count", "mean_headline_tone"]} for r in rows], indent=2))


if __name__ == "__main__":
    main()
