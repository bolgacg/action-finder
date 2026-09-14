"""How much would the ranking move if the missing papers looked like the ones we have?

The page tells a reader the ranking was computed on a fraction of the papers and
that the order is a draft. That invites a question it then refuses to answer.
This script answers it by measurement rather than by adjective.

METHOD. A nonparametric bootstrap at the level of the individual work. The
covered AU works are resampled with replacement to the same size, the scoring
rank.py uses is rerun on each resample, and the rank each candidate lands at is
recorded. Nothing is modelled and no distribution is assumed: the only claim is
that the papers we have not seen resemble the ones we have. That claim is itself
shaky, because the covered works are a publication-year slice rather than a
random sample, and the output says so.

THREE THINGS THIS DELIBERATELY DOES NOT DO.

Resampling happens upstream of the thresholds, on the works themselves, not on
the finished candidate rows. The uncertainty being measured is "we saw a quarter
of the papers", and that uncertainty lives in which works were drawn. A
candidate that only clears the five-work threshold sometimes has to be allowed
to vanish in the resamples where it does not clear it, and it does.

The CORDIS side is NOT resampled. That half is complete: every Danish
organisation, every shared project and every unconnected share is a census, not
a sample. Treating a complete census as uncertain would widen every band and
make the tool look more careful than it is.

The scoring is imported from rank.py rather than reimplemented, and the script
refuses to report anything until it has reproduced the published ranking exactly
from an unresampled run. A stability estimate produced by a slightly different
scorer would be measuring the wrong thing.

Usage:
    python3 study/stability.py
    python3 study/stability.py --resamples 5000
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from common import DATA, DERIVED, log, read_json, write_json  # noqa: E402

# Imported, not copied. If rank.py's scaling changes, this follows it.
from rank import PARTNER_ACTIVITY_TYPES, minmax, pipe_list  # noqa: E402

SEED = 20260914


def score_once(
    works: np.ndarray,
    company: np.ndarray,
    n_orgs: np.ndarray,
    unconnected_share: np.ndarray,
    min_works: int,
    min_orgs: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Score and rank one draw, exactly as rank.py does it.

    Returns the indices of the candidates that cleared the thresholds, their
    ranks (1 is best), and whether each is flagged white space.
    """
    valid = np.where((works >= min_works) & (n_orgs >= min_orgs))[0]
    if valid.size == 0:
        return valid, np.empty(0, dtype=int), np.empty(0, dtype=bool)

    # rank.py scales with minmax over the candidate set of that run, so the
    # scaling is recomputed inside the loop and not fixed once outside it.
    au = minmax({i: int(works[c]) for i, c in enumerate(valid)})
    dk = minmax({i: int(n_orgs[c]) for i, c in enumerate(valid)})
    au_v = np.array([au[i] for i in range(valid.size)])
    dk_v = np.array([dk[i] for i in range(valid.size)])

    gap = 0.5 + 0.5 * unconnected_share[valid]
    # Rounded before sorting because rank.py rounds before sorting, and the
    # rounding decides ties.
    score = np.round(np.sqrt(au_v * dk_v) * gap, 4)

    # Stable sort on the descending score. rank.py uses Python's stable sort
    # over candidates built in (department, subfield_id) order, so the cells
    # here are held in that same order and ties resolve identically.
    order = np.argsort(-score, kind="stable")
    ranks = np.empty(valid.size, dtype=int)
    ranks[order] = np.arange(1, valid.size + 1)
    return valid, ranks, company[valid] == 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--resamples", type=int, default=2000)
    ap.add_argument("--min-works", type=int, default=5)
    ap.add_argument("--min-orgs", type=int, default=3)
    ap.add_argument("--year-from", type=int, default=2022)
    args = ap.parse_args()

    affil = pd.read_csv(
        os.path.join(DERIVED, "pure_natsci_affiliations.csv"), dtype=str
    )
    oa = pd.read_csv(os.path.join(DERIVED, "openalex_works.csv"), dtype=str)
    dk_orgs = pd.read_csv(
        os.path.join(DERIVED, "cordis_dk_organisations.csv"), dtype=str
    )
    dk_sub = pd.read_csv(
        os.path.join(DERIVED, "cordis_dk_org_subfields.csv"), dtype=str
    )
    published = read_json(os.path.join(DATA, "actions.json"))

    oa["n_companies_i"] = pd.to_numeric(
        oa["n_companies"], errors="coerce"
    ).fillna(0)

    joined = affil.merge(oa, on="doi", how="inner")
    joined = joined[joined["subfield"].notna() & (joined["subfield"] != "")]
    joined["pub_year_i"] = pd.to_numeric(joined["pub_year"], errors="coerce")
    joined = joined[joined["pub_year_i"] >= args.year_from]

    # ------------------------------------------------ the Danish side, fixed
    org_lookup = dk_orgs.set_index("organisationID").to_dict("index")
    per_subfield: dict[str, dict] = {}
    for _, r in dk_sub.iterrows():
        info = org_lookup.get(r["organisationID"])
        if not info:
            continue
        if (info.get("activity_type") or "") not in PARTNER_ACTIVITY_TYPES:
            continue
        connected = bool(pipe_list(r.get("au_shared_project_ids_on_topic")))
        s = per_subfield.setdefault(r["subfield_id"], {"n": 0, "unconnected": 0})
        s["n"] += 1
        if not connected:
            s["unconnected"] += 1

    # -------------------------------------------------------- the AU side
    # Cells in the same order rank.py builds them, so ties break the same way.
    cell_keys = sorted(
        {(d, s) for d, s in zip(joined["department"], joined["subfield_id"])}
    )
    cell_index = {k: i for i, k in enumerate(cell_keys)}
    n_cells = len(cell_keys)

    doi_list = sorted(set(joined["doi"]))
    doi_index = {d: i for i, d in enumerate(doi_list)}
    n_dois = len(doi_list)

    membership = np.zeros((n_dois, n_cells), dtype=np.float64)
    for d, s, doi in zip(
        joined["department"], joined["subfield_id"], joined["doi"]
    ):
        membership[doi_index[doi], cell_index[(d, s)]] = 1.0

    has_company = np.zeros(n_dois, dtype=np.float64)
    for doi, n in zip(joined["doi"], joined["n_companies_i"]):
        if n > 0:
            has_company[doi_index[doi]] = 1.0

    n_orgs = np.array(
        [per_subfield.get(s, {"n": 0})["n"] for _, s in cell_keys], dtype=float
    )
    unconnected_share = np.array(
        [
            (
                per_subfield.get(s, {"unconnected": 0, "n": 0})["unconnected"]
                / per_subfield[s]["n"]
                if per_subfield.get(s, {}).get("n")
                else 0.0
            )
            for _, s in cell_keys
        ]
    )

    log(
        f"{n_dois} covered works across {n_cells} department-by-topic cells, "
        f"{len(per_subfield)} topics carry Danish organisations"
    )

    # ------------------------------------------- the identity check, first
    ones = np.ones(n_dois)
    base_works = ones @ membership
    base_company = (ones * has_company) @ membership
    valid, ranks, _ = score_once(
        base_works, base_company, n_orgs, unconnected_share,
        args.min_works, args.min_orgs,
    )
    reproduced = {
        f"{cell_keys[c][0]}||{cell_keys[c][1]}": int(r)
        for c, r in zip(valid, ranks)
    }
    expected = {
        f"{a['department']}||{a['topic']['subfield_id']}": a["rank"]
        for a in published["actions"]
    }
    mismatch = {
        k: (expected[k], reproduced.get(k))
        for k in expected
        if reproduced.get(k) != expected[k]
    }
    if mismatch:
        raise SystemExit(
            "the unresampled run does not reproduce the published ranking, so "
            "any stability number from it would describe a different scorer. "
            f"First differences: {dict(list(mismatch.items())[:5])}"
        )
    log(f"identity check passed: reproduced all {len(expected)} published ranks")

    # ------------------------------------------------------- the bootstrap
    rng = np.random.default_rng(SEED)
    B = args.resamples
    appears = np.zeros(n_cells, dtype=int)
    first = np.zeros(n_cells, dtype=int)
    white = np.zeros(n_cells, dtype=int)
    rank_samples: list[list[int]] = [[] for _ in range(n_cells)]
    works_samples: list[list[int]] = [[] for _ in range(n_cells)]
    candidate_counts = np.zeros(B, dtype=int)

    for b in range(B):
        draw = rng.integers(0, n_dois, n_dois)
        counts = np.bincount(draw, minlength=n_dois).astype(np.float64)
        works = counts @ membership
        company = (counts * has_company) @ membership
        valid, ranks, is_white = score_once(
            works, company, n_orgs, unconnected_share,
            args.min_works, args.min_orgs,
        )
        candidate_counts[b] = valid.size
        for c, r, w in zip(valid, ranks, is_white):
            appears[c] += 1
            rank_samples[c].append(int(r))
            works_samples[c].append(int(works[c]))
            if r == 1:
                first[c] += 1
            if w:
                white[c] += 1
        if (b + 1) % 500 == 0:
            log(f"  {b + 1} of {B} resamples")

    ref_rank = {
        (a["department"], a["topic"]["subfield_id"]): a for a in published["actions"]
    }

    by_action = {}
    for c, (dept, sub) in enumerate(cell_keys):
        if appears[c] == 0 and (dept, sub) not in ref_rank:
            continue
        a = ref_rank.get((dept, sub))
        rs = np.array(rank_samples[c]) if rank_samples[c] else np.empty(0)
        entry = {
            "department": dept,
            "subfield_id": sub,
            "topic": a["topic"]["subfield"] if a else None,
            "published_rank": a["rank"] if a else None,
            "published_score": a["score"] if a else None,
            "published_white_space": a["white_space"] if a else None,
            "appears_pct": round(100.0 * appears[c] / B, 1),
            "median_rank": int(np.median(rs)) if rs.size else None,
            "rank_p5": int(np.percentile(rs, 5)) if rs.size else None,
            "rank_p95": int(np.percentile(rs, 95)) if rs.size else None,
            "ranked_first_pct": round(100.0 * first[c] / B, 1),
            "white_space_pct": (
                round(100.0 * white[c] / appears[c], 1) if appears[c] else None
            ),
            "median_works": (
                int(np.median(works_samples[c])) if works_samples[c] else 0
            ),
        }
        if a:
            by_action[a["action_id"]] = entry
        else:
            # A cell that never clears the thresholds in the published run but
            # does in some resamples. Reported so the list is not only the
            # candidates that happened to make the cut this time.
            by_action[f"unpublished::{dept}||{sub}"] = entry

    published_entries = [
        v for v in by_action.values() if v["published_rank"] is not None
    ]
    published_entries.sort(key=lambda v: v["published_rank"])

    top = published_entries[0] if published_entries else None
    always = [v for v in published_entries if v["appears_pct"] >= 99.0]
    fragile = [v for v in published_entries if v["appears_pct"] < 80.0]
    ws_now = [v for v in published_entries if v["published_white_space"]]
    ws_holds = [v for v in ws_now if (v["white_space_pct"] or 0) >= 80.0]

    out = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "resamples": B,
        "seed": SEED,
        "what_was_resampled": (
            "the covered AU works only, drawn with replacement at the level of "
            "the individual work and upstream of the thresholds, so a candidate "
            "that only sometimes reaches five works is allowed to disappear. "
            "The CORDIS side was NOT resampled, because every Danish "
            "organisation, shared project and unconnected share in it is a "
            "complete census rather than a sample, and treating a census as "
            "uncertain would widen every band and flatter the ranking."
        ),
        "what_this_assumes": (
            "that the papers not yet looked up resemble the ones that were. "
            "They probably do not: the covered works are heavy with one "
            "publication year rather than being a random sample, so these bands "
            "describe sampling wobble within the covered slice and understate "
            "the movement the missing 72 percent will actually cause."
        ),
        "scoring_source": (
            "imported from study/rank.py and verified against data/actions.json "
            "before any resampling"
        ),
        "reference_ranking_reproduced": True,
        "covered_works_resampled": n_dois,
        "candidates_per_resample": {
            "median": int(np.median(candidate_counts)),
            "p5": int(np.percentile(candidate_counts, 5)),
            "p95": int(np.percentile(candidate_counts, 95)),
            "published": len(published_entries),
        },
        "white_space_caveat": (
            "white_space_pct below is NOT the chance a white space flag "
            "survives the completed lookup, and must not be read as one. The "
            "bootstrap redraws the works already covered, and a topic with no "
            "company co-author among those works will have none in almost any "
            "redraw of them, so this number is close to vacuous by "
            "construction. It says only that the flag is not an accident of "
            "which covered works were drawn. The real risk to a white space "
            "flag is a company appearing among the 5,304 works never looked "
            "up, which no resampling of the covered works can see. The "
            "projection in honesty.json under ranking_stability estimates that "
            "separately, and far less favourably."
        ),
        "headline": {
            "top_candidate": (
                f"{top['department']}, {top['topic']}" if top else None
            ),
            "top_candidate_action_id": (
                next(
                    (k for k, v in by_action.items() if v is top), None
                )
                if top
                else None
            ),
            "top_candidate_ranked_first_pct": top["ranked_first_pct"] if top else None,
            "candidates_appearing_in_at_least_99_pct": len(always),
            "candidates_appearing_in_under_80_pct": len(fragile),
            "white_space_flags_published": len(ws_now),
            "white_space_flags_holding_in_at_least_80_pct": len(ws_holds),
        },
        "by_action": by_action,
    }
    write_json(os.path.join(DERIVED, "stability.json"), out)

    log("")
    log(f"top candidate is ranked first in {top['ranked_first_pct']}% of resamples"
        if top else "no candidates")
    log(
        f"{len(always)} of {len(published_entries)} candidates appear in at least "
        f"99% of resamples, {len(fragile)} in under 80%"
    )
    log(
        f"{len(ws_holds)} of {len(ws_now)} white space flags hold in at least "
        f"80% of resamples"
    )


if __name__ == "__main__":
    main()
