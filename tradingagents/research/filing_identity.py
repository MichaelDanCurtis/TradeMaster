"""Context-bound identity correction for joint SEC filings; no scoring changes."""
from datetime import datetime
import re

from lxml import etree


VERSION = "filing_identity_context_v1"
FIELDS = {"documenttype", "documentperiodenddate", "entitycentralindexkey",
          "documentfiscalyearfocus", "documentfiscalperiodfocus"}


def local(tag):
    return str(tag).split("}")[-1].split(":")[-1].lower()


def normalize_date(value, format_name):
    value = re.sub(r"\s+", " ", value).strip().replace(" ,", ",")
    formats = ["%Y-%m-%d", "%B %d, %Y", "%b %d, %Y"]
    if format_name.split(":")[-1] in {"date-month-day-year", "datemonthdayyear"}:
        formats.append("%m/%d/%Y")
    for pattern in formats:
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            continue
    return value


def scoped_identity(raw, record):
    tree = etree.HTML(raw, parser=etree.HTMLParser(no_network=True))
    if tree is None:
        raise ValueError("No HTML document")
    contexts, rejected = {}, []
    for node in tree.iter():
        if local(node.tag) != "context":
            continue
        descendants = list(node.iter())
        ids = [(n.text or "").strip() for n in descendants if local(n.tag) == "identifier"]
        ends = [(n.text or "").strip() for n in descendants if local(n.tag) in {"enddate", "instant"}]
        dimensional = any(local(n.tag) in {"segment", "scenario", "explicitmember", "typedmember"} for n in descendants)
        matched = (len(ids) == 1 and ids[0].isdigit() and int(ids[0]) == int(record["cik"])
                   and ends == [record["reportDate"]] and not dimensional)
        cid = node.get("id")
        if not matched:
            rejected.append(cid)
        elif cid in contexts:
            raise ValueError("Duplicate eligible context identifier")
        else:
            contexts[cid] = {"cik": ids[0], "period_end": ends[0]}
    values, evidence = {}, []
    for node in tree.iter():
        name = node.get("name", "").lower()
        cid = node.get("contextref")
        if not name.startswith("dei:") or name.split(":", 1)[1] not in FIELDS or cid not in contexts:
            continue
        key = name.split(":", 1)[1]
        text = " ".join(" ".join(node.itertext()).split())
        value = normalize_date(text, node.get("format", "")) if key == "documentperiodenddate" else text
        values.setdefault(key, set()).add(value)
        evidence.append({"field": key, "context_id": cid, "source_value": text,
                         "format": node.get("format"), "normalized_value": value})
    return {"version": VERSION, "dei": {k: sorted(v) for k, v in values.items()},
            "eligible_contexts": contexts, "rejected_context_count": len(rejected), "evidence": evidence,
            "narrative_scope": "Original whole filing, which may include named co-registrants; text and tokens unchanged"}
