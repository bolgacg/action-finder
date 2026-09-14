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

    A single coverage percentage invites the reader to assume the missing papers
    are missing at random. They are not: the lookup works down a list and stopped
    where the daily budget ran out, so one year can be nearly complete while the
    next is untouched, and a ranking built on that is closer to a ranking of
    whichever year got through.

    This reads the table rank.py already writes rather than recomputing it. A first
    version here did recompute it, taking the numerator from OpenAlex's own
    publication_year and the denominator from Pure's pub_year. Those are different
    fields counting different papers: OpenAlex dates some papers to the year before
    Pure files them, so the two disagree near every year boundary. It printed 253
    covered works against a denominator of 4 for 2021, a coverage of 6,325 percent,
    and it misstated every real year as well. Both sides must key on the same field,
    and rank.py's table does.
    """
    src = (d.get("harvest_and_coverage_by_year") or {}).get("openalex_coverage_by_publication_year")
    if not src:
        return
    rows = []
    for y in sorted(src):
        if not y.isdigit():
            continue
        r = src[y]
        rows.append({
            "year": y,
            "with_doi": r.get("natural_sciences_dois"),
            "looked_up": r.get("covered_by_openalex"),
            "coverage_pct": r.get("coverage_pct"),
        })
    if not rows:
        return
    # Years outside the requested window hold a handful of oddly dated records, so
    # the best and worst year are taken only from years the harvest asked for and
    # that carry enough papers for a percentage to mean anything.
    window_from = int((d.get("window") or {}).get("publication_years_from") or 0)
    comparable = [
        r for r in rows
        if r["coverage_pct"] is not None and int(r["year"]) >= window_from and (r["with_doi"] or 0) >= 100
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
        "both_sides_keyed_on": "the publication year Pure files the paper under, on numerator and denominator alike",
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
