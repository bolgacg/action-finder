#!/usr/bin/env python3
"""Write docs/data.js from the ranked Actions and the honesty panel."""
from __future__ import annotations
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DOCS = ROOT / "docs"


def attach_stability(d: dict) -> None:
    """Inline data/derived/stability.json, but only if it describes THIS ranking.

    stability.py has to run after rank.py, because it bootstraps the published
    candidates. That means a rebuild which reruns rank.py without rerunning
    stability.py leaves a stability file describing a ranking that no longer
    exists, and inlining it blind would put confidence bands from one ordering
    next to a different ordering. So the file is checked against the actions it
    claims to describe and dropped, loudly, when it does not match.
    """
    p = DATA / "derived" / "stability.json"
    if not p.exists():
        d["stability"] = {"available": False, "reason": "stability.json not built"}
        return
    s = json.loads(p.read_text())
    by = s.get("by_action", {})
    published = {a["action_id"]: a["rank"] for a in d["actions"]}
    stale = [
        aid for aid, rank in published.items()
        if by.get(aid, {}).get("published_rank") != rank
    ]
    if stale:
        d["stability"] = {
            "available": False,
            "reason": (
                f"stability.json describes a different ranking "
                f"({len(stale)} of {len(published)} candidates disagree). "
                "Rerun study/stability.py after rank.py."
            ),
        }
        print(f"  stability.json is STALE for {len(stale)} candidates, not inlined")
        return
    s["available"] = True
    d["stability"] = s
    print(f"  stability.json inlined, {s.get('resamples')} resamples")


def attach_coverage_by_year(d: dict) -> None:
    """How much of each publication year actually reached a topic.

    The headline coverage figure is a single percentage, and a single percentage
    invites the reader to assume the missing papers are missing at random. They
    are not. The lookup walks the DOI list in order and stopped where the budget
    ran out, so one year can be almost complete while the next is untouched, and
    a ranking built on that is a ranking of whichever year got through. That is a
    far sharper thing to tell a reader than "27.6 percent", so it is computed
    here rather than described.

    A caveat that belongs with the number: OpenAlex carries its own publication
    year, which for a paper published near a year boundary can differ from the
    year Pure records. So a year's covered count can exceed what Pure filed under
    it. The rows are kept as they are and the difference is named on the page.
    """
    pure_p = DATA / "derived" / "pure_natsci_works.csv"
    oa_p = DATA / "derived" / "openalex_works.csv"
    if not (pure_p.exists() and oa_p.exists()):
        return
    pure: dict[str, int] = {}
    with pure_p.open() as f:
        for row in csv.DictReader(f):
            if (row.get("doi") or "").strip():
                pure[row["pub_year"]] = pure.get(row["pub_year"], 0) + 1
    looked: dict[str, int] = {}
    with oa_p.open() as f:
        for row in csv.DictReader(f):
            y = row.get("publication_year") or ""
            looked[y] = looked.get(y, 0) + 1

    rows = []
    for y in sorted(pure):
        if not y.isdigit():
            continue
        have, got = pure[y], looked.get(y, 0)
        rows.append({
            "year": y,
            "with_doi": have,
            "looked_up": got,
            "coverage_pct": round(100.0 * got / have, 1) if have else None,
        })
    if not rows:
        return
    # Years outside the requested window hold a handful of oddly dated records, and
    # the year-boundary effect above can put a covered count against a denominator of
    # four, which reports a coverage of several thousand percent. Those rows stay in
    # the table, because hiding them would be hiding a real quirk of the data, but the
    # best and worst year are taken only from years the harvest actually asked for.
    window_from = int((d.get("window") or {}).get("publication_years_from") or 0)
    comparable = [
        r for r in rows
        if r["coverage_pct"] is not None and int(r["year"]) >= window_from and r["with_doi"] >= 100
    ]
    if not comparable:
        return
    best = max(comparable, key=lambda r: r["coverage_pct"])
    worst = min(comparable, key=lambda r: r["coverage_pct"])
    d.setdefault("honesty_panel", {})["coverage_by_year"] = {
        "what_it_is": ("the share of each publication year's papers that reached a topic. "
                       "The missing papers are not missing at random: the lookup stopped "
                       "where the daily budget ran out, partway down a list in order."),
        "rows": rows,
        "years_compared_from": window_from,
        "best_year": best,
        "worst_year": worst,
        "note_on_years": ("OpenAlex records its own publication year, which can differ from "
                          "the year Pure files a paper under, so a year's covered count can "
                          "exceed the Pure count near a year boundary."),
    }
    print(f"  coverage by year: {best['year']} at {best['coverage_pct']}%, "
          f"{worst['year']} at {worst['coverage_pct']}%")


def main() -> int:
    d = json.loads((DATA / "actions.json").read_text())
    hp = d.get("honesty_panel")
    if isinstance(hp, str):
        p = ROOT / hp
        d["honesty_panel"] = json.loads(p.read_text()) if p.exists() else {}
    attach_stability(d)
    attach_coverage_by_year(d)
    DOCS.mkdir(parents=True, exist_ok=True)
    out = "/* generated by study/build_page_data.py, do not edit */\nconst D = " + \
        json.dumps(d, separators=(",", ":")) + ";\n"
    (DOCS / "data.js").write_text(out)
    print(f"wrote docs/data.js ({len(out)//1024} KB), {len(d['actions'])} candidate Actions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
