"""Build data/actions.json, the ranked list of candidate Actions, and the honesty panel.

An Action candidate is one pair: an AU Natural Sciences DEPARTMENT and a TOPIC,
where topic means an OpenAlex subfield. Department is the finest grain this tool
reports. There is no person-level output anywhere and none can be derived from
the files it writes, because the person identifiers were removed at harvest.

A candidate qualifies when three things hold at once:

  1. the department published in that topic through the window, from Pure, which
     is the only source that knows which AU faculty a paper belongs to;
  2. Danish organisations are working on that topic in Horizon Europe, from
     CORDIS;
  3. those two groups have not already met, which is checked two ways that fail
     independently: a hard CORDIS participant-identifier join for shared
     projects, and OpenAlex company co-authorship on the department's own papers.

The score is deliberately dull and fully exposed. Every component that feeds it
is written into the output next to the number it produced, so a reader can
disagree with the weighting and recompute rather than having to trust it.

Usage:
    python3 study/rank.py
"""

from __future__ import annotations

import argparse
import collections
import datetime
import json
import math
import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd  # noqa: E402

from common import (  # noqa: E402
    DATA,
    DERIVED,
    load_cordis_projects,
    log,
    read_json,
    write_json,
)

STUDY = os.path.dirname(os.path.abspath(__file__))

# Science Bridge Actions pair AU researchers with EXTERNAL partners, so the
# Danish side of a candidate has to be an organisation AU could be introduced
# to, not another university. Left in: PRC, private for-profit, the main target.
# REC, research organisations, which in Denmark covers the GTS institutes such
# as Teknologisk Institut, and charities such as Kraeftens Bekaempelse. PUB,
# public bodies such as municipalities and agencies. OTH, everything else.
# Taken out: HES, higher and secondary education. Without this the lists were
# topped by Copenhagen, DTU, SDU and Aalborg on every single topic, because
# universities are the heaviest Horizon Europe participants by far, and
# "Aarhus should talk to Copenhagen" is not an Action this office would run.
PARTNER_ACTIVITY_TYPES = {"PRC", "REC", "PUB", "OTH"}
# Fixed so that the hand-checked sample is the same sample on every run and the
# verdicts recorded against it stay attached to the rows they were made about.
SAMPLE_SEED = 20260914


def slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s or "none"


def pipe_list(value) -> list[str]:
    """Split a pipe-joined cell, treating an empty cell as an empty list.

    The obvious `str(value or "").split("|")` is wrong on a DataFrame cell: an
    empty cell arrives as a float NaN, NaN is truthy, so `value or ""` keeps the
    NaN and str() turns it into the literal string "nan". That produced a
    one-element list for every empty cell, which in turn marked every Danish
    organisation as already sharing a project with AU. The tell was that the
    same-topic collaboration count came out higher than the any-topic count,
    which cannot happen.
    """
    if value is None:
        return []
    if isinstance(value, float) and math.isnan(value):
        return []
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return []
    return [p for p in text.split("|") if p and p.lower() != "nan"]


def minmax(values: dict) -> dict:
    """Scale against the largest, on log1p. Log because a department with 200
    papers in a topic is not twenty times more promising than one with 10, and a
    raw linear scale would let one large department own the whole list.

    Against the largest, not between the smallest and the largest. A min-max
    scale gives whichever candidate holds the minimum a value of exactly zero,
    and because the score multiplies two of these together, one zero collapses
    the whole score to zero. That happened to 11 of 25 candidates, every one of
    them with real papers and real Danish organisations behind it: Chemistry and
    Catalysis scored 0.000 on five papers and fourteen organisations. Eleven rows
    tied at zero is not a ranking, and a reader who sees it concludes the page is
    broken rather than that the candidate is weak. Dividing by the maximum keeps
    the meaning, which is strength relative to the strongest candidate here, and
    a real quantity can no longer become nothing."""
    logs = {k: math.log1p(v) for k, v in values.items()}
    if not logs:
        return {}
    hi = max(logs.values())
    if hi <= 0:
        return {k: 1.0 for k in logs}
    return {k: v / hi for k, v in logs.items()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-works", type=int, default=5,
                    help="department papers in a topic before it can be a candidate")
    ap.add_argument("--min-orgs", type=int, default=3,
                    help="Danish organisations on that topic before it can be a candidate")
    ap.add_argument("--top", type=int, default=40, help="candidates written out")
    ap.add_argument("--year-from", type=int, default=2022)
    args = ap.parse_args()

    # ---------------------------------------------------------------- inputs
    affil = pd.read_csv(os.path.join(DERIVED, "pure_natsci_affiliations.csv"),
                        dtype=str)
    works = pd.read_csv(os.path.join(DERIVED, "pure_natsci_works.csv"), dtype=str)
    oa = pd.read_csv(os.path.join(DERIVED, "openalex_works.csv"), dtype=str)
    dk_orgs = pd.read_csv(os.path.join(DERIVED, "cordis_dk_organisations.csv"),
                          dtype=str)
    dk_sub = pd.read_csv(os.path.join(DERIVED, "cordis_dk_org_subfields.csv"),
                         dtype=str)
    pure_cov = read_json(os.path.join(DERIVED, "pure_coverage.json"))
    oa_cov = read_json(os.path.join(DERIVED, "openalex_coverage.json"))
    cordis_checks = read_json(os.path.join(DERIVED, "cordis_checks.json"))

    # Project titles, so a weakly supported link can be named with the project
    # that produced it rather than just a bare identifier. A reader cannot judge
    # "Novo Nordisk under Ecology" without seeing that the project is a clinical
    # trials inclusivity study.
    _proj, _ = load_cordis_projects()
    project_titles = dict(zip(_proj["id"], _proj["title"]))
    project_calls = dict(zip(_proj["id"], _proj["topics"]))

    oa["n_companies"] = pd.to_numeric(oa["n_companies"], errors="coerce").fillna(0)
    oa["cited_by_count"] = pd.to_numeric(oa["cited_by_count"],
                                         errors="coerce").fillna(0)
    work_meta = works.set_index("rec_id").to_dict("index")

    # AU papers carrying both a department (Pure) and a topic (OpenAlex).
    joined = affil.merge(oa, on="doi", how="inner")
    joined = joined[joined["subfield"].notna() & (joined["subfield"] != "")]
    joined["pub_year_i"] = pd.to_numeric(joined["pub_year"], errors="coerce")
    joined = joined[joined["pub_year_i"] >= args.year_from]
    log(f"{len(joined)} department-by-paper rows carry a topic")

    # Per department, how many DOI-carrying Pure works exist per year and how
    # many of them the OpenAlex lookup actually reached. Each candidate carries
    # its department's row so that a zero year in works_by_year can never be
    # read as "this department published nothing that year" when it really
    # means "the lookup never got that far".
    covered_dois = set(oa["doi"])
    dept_year_total: dict = collections.defaultdict(collections.Counter)
    dept_year_covered: dict = collections.defaultdict(collections.Counter)
    for _, r in affil.iterrows():
        if not r["doi"]:
            continue
        y = str(r["pub_year"] or "none")
        dept_year_total[r["department"]][y] += 1
        if r["doi"] in covered_dois:
            dept_year_covered[r["department"]][y] += 1

    def coverage_context(dept: str) -> dict:
        total = dept_year_total.get(dept, collections.Counter())
        cov = dept_year_covered.get(dept, collections.Counter())
        return {
            "note": (
                "works_by_year above counts only the papers this pipeline could "
                "place on a topic, which needs an OpenAlex record. Compare it "
                "with pure_works_with_doi_by_year to see what the department "
                "actually published and how much of it the lookup reached."
            ),
            "pure_works_with_doi_by_year": dict(sorted(total.items())),
            "openalex_covered_by_year": {
                y: cov.get(y, 0) for y in sorted(total)
            },
            "coverage_pct_by_year": {
                y: round(100.0 * cov.get(y, 0) / total[y], 1)
                for y in sorted(total) if total[y]
            },
        }

    # -------------------------------------------------- AU side, per dept/topic
    au_cells: dict[tuple[str, str], dict] = {}
    for (dept, sub_id), grp in joined.groupby(["department", "subfield_id"]):
        recs = grp.drop_duplicates(subset=["doi"])
        n_company = int((recs["n_companies"] > 0).sum())
        companies = sorted(
            {c for names in recs["company_names"] for c in pipe_list(names)}
        )
        # Kept apart from the global list because they answer different
        # questions for a Danish knowledge-exchange secretariat. That a group
        # co-publishes with Intel in the United States says the topic has
        # industrial pull; that it co-publishes with a Danish firm says the
        # local conversation has already happened.
        dk_companies = sorted(
            {c for names in recs["dk_company_names"] for c in pipe_list(names)}
        )
        n_dk_company = int(
            (pd.to_numeric(recs["n_dk_companies"], errors="coerce").fillna(0) > 0).sum()
        )
        examples = (
            recs.sort_values("cited_by_count", ascending=False).head(4)
        )
        au_cells[(dept, sub_id)] = {
            "department": dept,
            "subfield_id": sub_id,
            "subfield": grp["subfield"].iloc[0],
            "field": grp["field"].iloc[0],
            "domain": grp["domain"].iloc[0],
            "works": len(recs),
            "works_by_year": {
                str(int(y)): int(n)
                for y, n in sorted(
                    recs["pub_year_i"].value_counts().to_dict().items()
                )
            },
            "works_with_company_coauthor": n_company,
            "company_coauthors": companies,
            "works_with_danish_company_coauthor": n_dk_company,
            "danish_company_coauthors": dk_companies,
            "examples": [
                {
                    "title": (work_meta.get(r["rec_id"], {}) or {}).get("title") or "",
                    "doi": r["doi"],
                    "year": int(r["pub_year_i"]),
                    "journal": (work_meta.get(r["rec_id"], {}) or {}).get("journal") or "",
                    "openalex_primary_topic": r["primary_topic"],
                    "cited_by_count": int(r["cited_by_count"]),
                }
                for _, r in examples.iterrows()
            ],
        }

    # ------------------------------------------- Danish side, per topic
    org_lookup = dk_orgs.set_index("organisationID").to_dict("index")
    dk_by_sub: dict[str, list] = collections.defaultdict(list)
    for _, r in dk_sub.iterrows():
        info = org_lookup.get(r["organisationID"])
        if not info:
            continue
        if (info.get("activity_type") or "") not in PARTNER_ACTIVITY_TYPES:
            continue
        shared_here = pipe_list(r.get("au_shared_project_ids_on_topic"))
        dk_by_sub[r["subfield_id"]].append(
            {
                "cordis_participant_id": r["organisationID"],
                "name": info.get("name") or "",
                "short_name": info.get("short_name") or "",
                "activity": info.get("activity_label") or "",
                "activity_code": info.get("activity_type") or "",
                "sme": str(info.get("sme")).lower() == "true",
                "city": info.get("city") or "",
                "horizon_projects_on_this_topic": int(r["n_projects"]),
                # Aliases for the page, which reads these two names. They point
                # at the canonical fields above and below rather than holding
                # anything of their own. "projects" is the count the list is
                # ordered by; "shares_project_with_au" is the ANY-topic flag,
                # because for deciding whether a call is warm or cold what
                # matters is that a working relationship exists at all, not that
                # it happens to be on this topic.
                "projects": int(r["n_projects"]),
                "project_ids_on_this_topic": pipe_list(r["project_ids"]),
                "project_acronyms_on_this_topic": pipe_list(r["project_acronyms"]),
                # Two different questions, kept apart on purpose.
                "shares_a_project_with_au_on_this_topic": len(shared_here) > 0,
                "au_shared_project_ids_on_this_topic": shared_here,
                "shares_any_project_with_au": str(
                    info.get("already_worked_with_au")
                ).lower() == "true",
                "shares_project_with_au": str(
                    info.get("already_worked_with_au")
                ).lower() == "true",
                # How solid the CORDIS tag that put this organisation on this
                # topic actually is. See tag_support in partners.py.
                "topic_support": r.get("topic_support") or "unknown",
                "topic_support_detail": {
                    "carrying_terms": pipe_list(r.get("support_carrying_terms")),
                    "terms_on_project": r.get("support_terms_on_project") or "",
                    "terms_in_same_domain": r.get("support_terms_in_same_domain") or "",
                    "other_domains_on_project": pipe_list(
                        r.get("support_other_domains")
                    ),
                    "project_id": r.get("support_project_id") or "",
                },
                "au_shared_project_ids_any_topic": pipe_list(
                    info.get("au_shared_project_ids")
                ),
            }
        )

    # How the Danish side of each topic was built. A subfield reached by an
    # exact euroSciVoc term match is a firmer claim than one reached by climbing
    # two levels up the path, and the reader of a single candidate cannot see
    # which they are looking at unless it travels with the candidate.
    bridge_all = read_json(os.path.join(DERIVED, "topic_bridge.json"))
    bridge_by_subfield: dict[str, list] = collections.defaultdict(list)
    for path, rec in bridge_all.items():
        bridge_by_subfield[rec["subfield_id"]].append(rec)

    def bridge_quality(sub_id: str) -> dict:
        recs = bridge_by_subfield.get(sub_id, [])
        climbs = collections.Counter(r["levels_above_leaf"] for r in recs)
        return {
            "euroscivoc_terms_feeding_this_topic": len(recs),
            "exact_term_matches": climbs.get(0, 0),
            "matched_via_a_parent_term": sum(
                v for k, v in climbs.items() if k > 0
            ),
            "levels_above_leaf": {str(k): v for k, v in sorted(climbs.items())},
            "match_methods": dict(
                collections.Counter(r["match_method"] for r in recs)
            ),
            "example_terms": sorted({r["leaf_term"] for r in recs})[:12],
        }

    # ----------------------------------------------------------- candidates
    raw = []
    for (dept, sub_id), au in au_cells.items():
        orgs = dk_by_sub.get(sub_id, [])
        if au["works"] < args.min_works or len(orgs) < args.min_orgs:
            continue
        connected = [o for o in orgs if o["shares_a_project_with_au_on_this_topic"]]
        unconnected = [
            o for o in orgs if not o["shares_a_project_with_au_on_this_topic"]
        ]
        connected_any = [o for o in orgs if o["shares_any_project_with_au"]]
        raw.append(
            {
                "department": dept,
                "au": au,
                "orgs": orgs,
                "connected": connected,
                "unconnected": unconnected,
                "connected_any": connected_any,
            }
        )
    log(f"{len(raw)} candidate department-by-topic pairs clear the thresholds")

    au_scale = minmax({i: c["au"]["works"] for i, c in enumerate(raw)})
    dk_scale = minmax({i: len(c["orgs"]) for i, c in enumerate(raw)})

    actions = []
    for i, c in enumerate(raw):
        au, orgs = c["au"], c["orgs"]
        unconnected_share = len(c["unconnected"]) / len(orgs) if orgs else 0.0
        # Geometric mean, so a candidate has to be real on BOTH sides. A topic
        # where AU is strong but no Danish organisation works, or the reverse,
        # is not an Action, and an arithmetic mean would let either half carry it.
        base = math.sqrt(au_scale[i] * dk_scale[i])
        # The gap factor never zeroes a candidate out. A topic where AU already
        # has partners is still a legitimate Action, it is just less of a gap,
        # so the factor runs 0.5 to 1.0 rather than 0 to 1.
        gap = 0.5 + 0.5 * unconnected_share
        score = round(base * gap, 4)

        white_space = au["works_with_company_coauthor"] == 0

        actions.append(
            {
                "action_id": f"{slug(c['department'])}__{au['subfield_id']}",
                "department": c["department"],
                "topic": {
                    "subfield": au["subfield"],
                    "subfield_id": au["subfield_id"],
                    "field": au["field"],
                    "domain": au["domain"],
                    "vocabulary": "OpenAlex subfield",
                },
                "score": score,
                "score_components": {
                    "au_strength_scaled": round(au_scale[i], 4),
                    "danish_activity_scaled": round(dk_scale[i], 4),
                    "unconnected_share": round(unconnected_share, 4),
                    "gap_factor": round(gap, 4),
                    "formula": "sqrt(au_strength_scaled * danish_activity_scaled) * (0.5 + 0.5 * unconnected_share)",
                },
                "white_space": white_space,
                "no_danish_company_coauthor": au["works_with_danish_company_coauthor"] == 0,
                "white_space_definition": (
                    "the department published in this topic in the window and "
                    "not one of those papers carries a co-author whose OpenAlex "
                    "institution type is company, anywhere in the world"
                ),
                "au_evidence": {
                    "source": "AU Pure OAI-PMH for the faculty and department, OpenAlex for the topic",
                    "works_in_window": au["works"],
                    "works_by_year": au["works_by_year"],
                    "works_with_company_coauthor": au["works_with_company_coauthor"],
                    "company_coauthors": au["company_coauthors"],
                    "works_with_danish_company_coauthor": au["works_with_danish_company_coauthor"],
                    "danish_company_coauthors": au["danish_company_coauthors"],
                    "example_works": au["examples"],
                    "openalex_coverage_for_this_department": coverage_context(
                        c["department"]
                    ),
                },
                "topic_bridge_quality": bridge_quality(au["subfield_id"]),
                "danish_evidence": {
                    "source": "CORDIS Horizon Europe bulk export",
                    "organisations_on_this_topic": len(orgs),
                    "share_a_project_with_au_on_this_topic": len(c["connected"]),
                    "no_shared_project_with_au_on_this_topic": len(c["unconnected"]),
                    "share_any_project_with_au_on_any_topic": len(c["connected_any"]),
                    "for_profit_organisations": sum(
                        1 for o in orgs if o["activity_code"] == "PRC"
                    ),
                    # Ordered by how much the organisation actually works on
                    # this topic, not by whether it is already an AU partner.
                    # Sorting on the connection flag put a one-project newcomer
                    # above a company with five projects on the topic, which is
                    # the wrong organisation to put in front of a reader.
                    "organisations": sorted(
                        orgs,
                        key=lambda o: (
                            -o["horizon_projects_on_this_topic"],
                            o["activity_code"] != "PRC",
                            o["name"],
                        ),
                    )[:15],
                    "organisations_listed": min(len(orgs), 15),
                    "excluded_from_this_list": (
                        "organisations with CORDIS activity type HES, higher "
                        "and secondary education, which are universities "
                        "rather than external partners"
                    ),
                    "weakly_supported_organisations": sum(
                        1 for o in orgs if o["topic_support"] != "corroborated"
                    ),
                    "weakly_supported_pct": round(
                        100.0
                        * sum(1 for o in orgs if o["topic_support"] != "corroborated")
                        / len(orgs),
                        1,
                    ) if orgs else 0.0,
                    "what_weakly_supported_means": (
                        "the CORDIS project that put this organisation on this "
                        "topic carries no second euroSciVoc term from the same "
                        "domain, so the topic tag stands alone and may be using "
                        "the word loosely. It marks weak support, not a wrong "
                        "link: some of these are correct"
                    ),
                    "organisation_order": (
                        "most Horizon Europe projects on this topic first, "
                        "for-profit before other types at the same count"
                    ),
                },
                "collaboration_check": {
                    "cordis_shared_project_join": "participant identifier, never names",
                    "au_participant_id": "999997736",
                    "openalex_company_coauthor_check": "institution type == company",
                    "connected_on_this_topic": [
                        {
                            "name": o["name"],
                            "cordis_participant_id": o["cordis_participant_id"],
                            "au_shared_project_ids": o["au_shared_project_ids_on_this_topic"],
                        }
                        for o in c["connected"]
                    ],
                    "connected_to_au_on_some_other_topic": [
                        {
                            "name": o["name"],
                            "cordis_participant_id": o["cordis_participant_id"],
                            "au_shared_project_ids": o["au_shared_project_ids_any_topic"],
                        }
                        for o in c["connected_any"]
                        if not o["shares_a_project_with_au_on_this_topic"]
                    ][:15],
                },
            }
        )

    actions.sort(key=lambda a: -a["score"])
    for i, a in enumerate(actions, 1):
        a["rank"] = i
    top = actions[: args.top]

    # ------------------------------------------------------------ the sample
    rng = random.Random(SAMPLE_SEED)
    paper_pool = []
    term_pool = []
    for a in top:
        for ex in a["au_evidence"]["example_works"]:
            paper_pool.append(
                {
                    "check_type": "paper_to_subfield",
                    "action_id": a["action_id"],
                    "department": a["department"],
                    "assigned_subfield": a["topic"]["subfield"],
                    "openalex_primary_topic": ex["openalex_primary_topic"],
                    "paper_title": ex["title"],
                    "doi": ex["doi"],
                }
            )
    bridge = bridge_all
    top_subfields = {a["topic"]["subfield_id"] for a in top}
    for path, rec in bridge.items():
        if rec["subfield_id"] in top_subfields:
            term_pool.append(
                {
                    "check_type": "euroscivoc_term_to_subfield",
                    "euroscivoc_path": path,
                    "leaf_term": rec["leaf_term"],
                    "matched_term": rec["matched_term"],
                    "assigned_subfield": rec["subfield"],
                    "match_method": rec["match_method"],
                    "levels_above_leaf": rec["levels_above_leaf"],
                }
            )
    rng.shuffle(paper_pool)
    rng.shuffle(term_pool)
    sample = paper_pool[:10] + term_pool[:10]
    for i, s in enumerate(sample, 1):
        s["sample_id"] = f"s{i:02d}"
    write_json(os.path.join(DERIVED, "topic_check_sample.json"), sample)

    # Accuracy is measured against the FROZEN sample that was actually read by
    # hand, not against the sample this run happens to draw. The two differ, and
    # they have to: the hand check is what found the topic keyword route
    # unreliable, that finding turned the route off in partners.py, and turning
    # it off changes the candidates and therefore changes what a fresh sample
    # would contain. Scoring today's rows with yesterday's verdicts would attach
    # a judgement to a row it was never made about. So the frozen pair is the
    # evidence, and the fresh sample written below is the next round's work.
    verdict_path = os.path.join(STUDY, "topic_check_verdicts.json")
    frozen_path = os.path.join(STUDY, "topic_check_sample_checked.json")
    verdicts = read_json(verdict_path) if os.path.exists(verdict_path) else {}
    judged_sample = read_json(frozen_path) if os.path.exists(frozen_path) else sample
    checked = [s for s in judged_sample if s["sample_id"] in verdicts]
    wrong = [
        s for s in checked
        if verdicts[s["sample_id"]].get("verdict") == "wrong"
    ]
    partial = [
        s for s in checked
        if verdicts[s["sample_id"]].get("verdict") == "partly right"
    ]

    if checked:
        topic_accuracy = {
            "sample_drawn_from": (
                "a run made before the topic keyword route was switched off, "
                "which is what this check found and removed"
            ),
            "sample_size": len(judged_sample),
            "hand_checked": len(checked),
            "fresh_sample_for_next_round": len(sample),
            "judged_wrong": len(wrong),
            "judged_partly_right": len(partial),
            "judged_right": len(checked) - len(wrong) - len(partial),
            "wrong_rate_pct": round(100.0 * len(wrong) / len(checked), 1),
            "wrong_or_partly_rate_pct": round(
                100.0 * (len(wrong) + len(partial)) / len(checked), 1
            ),
            "by_check_type": {
                t: {
                    "checked": sum(1 for s in checked if s["check_type"] == t),
                    "wrong": sum(1 for s in wrong if s["check_type"] == t),
                    "partly_right": sum(1 for s in partial if s["check_type"] == t),
                }
                for t in ("paper_to_subfield", "euroscivoc_term_to_subfield")
            },
            # The finding that drove the design change, kept as a number rather
            # than a claim in prose.
            "by_bridge_match_method": {
                method: {
                    "checked": sum(
                        1 for s in checked if s.get("match_method") == method
                    ),
                    "right": sum(
                        1 for s in checked
                        if s.get("match_method") == method
                        and verdicts[s["sample_id"]]["verdict"] == "right"
                    ),
                    "partly_right": sum(
                        1 for s in partial if s.get("match_method") == method
                    ),
                    "wrong": sum(
                        1 for s in wrong if s.get("match_method") == method
                    ),
                }
                for method in ("subfield_name", "topic_name", "topic_keyword")
            },
            "verdicts": verdicts,
        }
    else:
        topic_accuracy = {
            "sample_size": len(sample),
            "hand_checked": 0,
            "status": (
                "sample written to data/derived/topic_check_sample.json but no "
                "verdicts recorded yet; no accuracy number is claimed"
            ),
        }

    # ------------------------------- how many top candidates are already joined
    already = []
    for a in top:
        d = a["danish_evidence"]
        already.append(
            {
                "rank": a["rank"],
                "action_id": a["action_id"],
                "organisations": d["organisations_on_this_topic"],
                "share_a_project_with_au_on_this_topic": d["share_a_project_with_au_on_this_topic"],
                "share_any_project_with_au": d["share_any_project_with_au_on_any_topic"],
                "share_pct_on_this_topic": round(
                    100.0 * d["share_a_project_with_au_on_this_topic"]
                    / d["organisations_on_this_topic"], 1
                ),
                "share_pct_any_topic": round(
                    100.0 * d["share_any_project_with_au_on_any_topic"]
                    / d["organisations_on_this_topic"], 1
                ),
                "au_has_company_coauthor_in_topic": (
                    a["au_evidence"]["works_with_company_coauthor"] > 0
                ),
            }
        )
    n_with_existing = sum(
        1 for r in already if r["share_a_project_with_au_on_this_topic"] > 0
    )
    n_with_existing_any = sum(
        1 for r in already if r["share_any_project_with_au"] > 0
    )
    n_with_company = sum(1 for r in already if r["au_has_company_coauthor_in_topic"])

    # How much of this ranking is likely to survive the missing OpenAlex data.
    #
    # This is the one block in the panel that is a PROJECTION rather than a
    # measurement, and it is labelled as such wherever it appears. It exists
    # because the alternative is for a reader to assume the ranking is settled
    # when the AU half of every score rests on roughly a quarter of the papers.
    #
    # Assumptions, both of which are wrong in ways that matter: that a company
    # co-author is equally likely on any paper, when in truth some topics are far
    # more industry-facing than others; and that the covered papers are a random
    # sample of each department's output, when in truth they are a slice heavy
    # with one publication year. Treat the direction as meaningful and the
    # decimals as noise.
    company_rate = (
        oa_cov["matched_with_company_coauthor"] / oa_cov["openalex_matched"]
        if oa_cov["openalex_matched"]
        else 0.0
    )
    dept_coverage = {}
    for dept in {a["department"] for a in top}:
        tot = sum(dept_year_total.get(dept, {}).values())
        cov = sum(dept_year_covered.get(dept, {}).values())
        dept_coverage[dept] = (cov / tot) if tot else 0.0

    fragility = []
    for a in top:
        if not a["white_space"]:
            continue
        cov = dept_coverage.get(a["department"], 0.0) or 1.0
        observed = a["au_evidence"]["works_in_window"]
        expected_more = observed * (1.0 / cov - 1.0)
        survives = (1.0 - company_rate) ** expected_more
        fragility.append(
            {
                "rank": a["rank"],
                "action_id": a["action_id"],
                "observed_works": observed,
                "department_openalex_coverage_pct": round(100 * cov, 1),
                "estimated_unseen_works_in_this_topic": round(expected_more, 1),
                "estimated_chance_it_stays_white_space_pct": round(
                    100 * survives, 1
                ),
            }
        )
    expected_surviving = sum(
        f["estimated_chance_it_stays_white_space_pct"] / 100 for f in fragility
    )

    # ------------------------------------------------- loose CORDIS tag summary
    tag_counts = collections.Counter(dk_sub["topic_support"].fillna("unknown"))
    tag_totals = {
        "all": int(sum(tag_counts.values())),
        "corroborated": int(tag_counts.get("corroborated", 0)),
        "minority_tag": int(tag_counts.get("minority_tag", 0)),
        "single_tag": int(tag_counts.get("single_tag", 0)),
    }
    tag_totals["weak_pct"] = (
        round(
            100.0
            * (tag_totals["minority_tag"] + tag_totals["single_tag"])
            / tag_totals["all"],
            1,
        )
        if tag_totals["all"]
        else 0.0
    )

    listed_orgs = [o for a in top for o in a["danish_evidence"]["organisations"]]
    listed_weak = sum(1 for o in listed_orgs if o["topic_support"] != "corroborated")
    listed_weak_pct = (
        round(100.0 * listed_weak / len(listed_orgs), 1) if listed_orgs else 0.0
    )

    worst_tagged = sorted(
        (
            {
                "rank": a["rank"],
                "action_id": a["action_id"],
                "department": a["department"],
                "topic": a["topic"]["subfield"],
                "weakly_supported_pct": a["danish_evidence"]["weakly_supported_pct"],
                "weakly_supported_organisations": a["danish_evidence"][
                    "weakly_supported_organisations"
                ],
                "organisations_on_this_topic": a["danish_evidence"][
                    "organisations_on_this_topic"
                ],
            }
            for a in top
        ),
        key=lambda r: -r["weakly_supported_pct"],
    )[:8]

    term_weak: collections.Counter = collections.Counter()
    term_all: collections.Counter = collections.Counter()
    named_examples = []
    for a in top:
        for o in a["danish_evidence"]["organisations"]:
            for t in o["topic_support_detail"]["carrying_terms"]:
                term_all[t] += 1
                if o["topic_support"] != "corroborated":
                    term_weak[t] += 1
            if o["topic_support"] == "single_tag":
                named_examples.append(
                    {
                        "organisation": o["name"],
                        "organisation_type": o["activity"],
                        "topic": a["topic"]["subfield"],
                        "department": a["department"],
                        "rank": a["rank"],
                        "carried_by_term": o["topic_support_detail"]["carrying_terms"],
                        "project_id": o["topic_support_detail"]["project_id"],
                        "project_title": project_titles.get(
                            o["topic_support_detail"]["project_id"], ""
                        ),
                        "call_topic": project_calls.get(
                            o["topic_support_detail"]["project_id"], ""
                        ),
                        "terms_on_that_project": o["topic_support_detail"][
                            "terms_on_project"
                        ],
                    }
                )
    # One organisation reaching the same loose tag from several candidates is one
    # finding, not several, so the list is deduplicated on the organisation and
    # the project that carried it, keeping the highest-ranked candidate.
    seen_examples = {}
    for e in sorted(named_examples, key=lambda x: x["rank"]):
        key = (e["organisation"], e["project_id"])
        if key not in seen_examples:
            seen_examples[key] = e
    named_examples = list(seen_examples.values())

    worst_terms = [
        {
            "term": t,
            "uncorroborated_uses": n,
            "total_uses": term_all[t],
            "uncorroborated_pct": round(100.0 * n / term_all[t], 1),
        }
        for t, n in term_weak.most_common(8)
    ]

    honesty = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "what_this_panel_is": (
            "the numbers that say how far the ranked list can be trusted, "
            "computed by the same scripts that produced the list"
        ),
        "headline_limitation": oa_cov.get("coverage_warning"),
        "coverage_pure": {
            "harvest_census": pure_cov["harvest_census"],
            "harvest_window_publication_years": pure_cov["works_by_year"],
            "records_read_from_cache": pure_cov["records_seen_in_cache"],
            "natural_sciences_works": pure_cov["natural_sciences_works"],
            "natural_sciences_works_with_doi": pure_cov[
                "natural_sciences_works_with_doi"
            ],
            "doi_share_pct": pure_cov["doi_share_pct"],
            "works_by_department": pure_cov["works_by_department"],
            "faculty_mentions_across_all_of_au": pure_cov[
                "faculty_mentions_in_cache"
            ],
        },
        "coverage_openalex": {
            "lookup_complete": oa_cov.get("lookup_complete", True),
            "incomplete_because": oa_cov.get("coverage_warning"),
            "dois_never_asked": oa_cov.get("dois_never_asked", 0),
            "dois_looked_up": oa_cov["pure_works_with_doi"],
            "dois_matched": oa_cov["openalex_matched"],
            "match_rate_pct": oa_cov["openalex_match_rate_pct"],
            "matched_share_of_all_natural_sciences_works_pct": oa_cov[
                "matched_share_of_all_pure_works_pct"
            ],
            "matched_works_with_a_primary_subfield": oa_cov[
                "matched_with_primary_subfield"
            ],
            "works_with_a_company_coauthor": oa_cov[
                "matched_with_company_coauthor"
            ],
            "company_coauthor_share_pct": oa_cov["company_coauthor_share_pct"],
            "institution_type_counts": oa_cov["institution_type_counts"],
            "coverage_by_publication_year": oa_cov.get(
                "coverage_by_publication_year", {}
            ),
        },
        "coverage_cordis": cordis_checks["facts_recheck"],
        "topic_bridge": cordis_checks["topic_bridge"],
        "cordis_project_file": cordis_checks.get("cordis_project_file", {}),
        "ranking_stability": {
            "status": "PROJECTION, not a measurement. See the assumptions below",
            "why_it_matters": (
                "the Danish half of every score is final, because CORDIS is "
                "complete. The AU half rests on the covered papers only, so the "
                "ranking will move when the rest of the lookup lands"
            ),
            "department_openalex_coverage_pct": {
                d: round(100 * c, 1)
                for d, c in sorted(dept_coverage.items(), key=lambda x: -x[1])
            },
            "coverage_spread_note": (
                "departments are not currently comparable with each other. "
                "Coverage runs from "
                f"{round(100 * min(dept_coverage.values()), 1)} percent to "
                f"{round(100 * max(dept_coverage.values()), 1)} percent across "
                "the departments in this list, so a department whose papers "
                "happened to fall in the covered slice looks stronger than one "
                "whose papers did not, for no reason connected to its research"
            ),
            "observed_company_coauthor_rate_pct": round(100 * company_rate, 1),
            "white_space_flags_now": len(fragility),
            "estimated_white_space_flags_surviving": round(expected_surviving, 1),
            "per_white_space_candidate": fragility,
            "assumptions": [
                "a company co-author is equally likely on any paper, which is "
                "false: some topics are far more industry-facing than others",
                "the covered papers are a random sample of each department's "
                "output, which is false: they are heavy with one publication year",
            ],
        },
        "loose_cordis_tags": {
            "what_this_measures": (
                "a link can be produced by a correct bridge from a loose tag. "
                "A CORDIS project tagged with one euroSciVoc term uses that word "
                "with nothing to corroborate it, and some of those words are "
                "homonyms. An organisation is counted weakly supported on a "
                "topic when no project connecting it to that topic carries a "
                "second euroSciVoc term from the same domain as the term that "
                "carried the topic"
            ),
            "why_not_the_simpler_test": (
                "asking whether the project's OTHER terms sit in a different "
                "domain misses the worst cases, because the worst projects have "
                "no other terms at all. The project that exposed this, Novo "
                "Nordisk under Ecology, carries exactly one term"
            ),
            "what_this_test_misses": (
                "corroboration is checked at the euroSciVoc DOMAIN level, which "
                "is coarse, so a loose tag sitting beside an unrelated term from "
                "the same broad domain passes. Region Hovedstaden reaches "
                "Ecology partly through project 101137378, a psilocybin trial in "
                "palliative care, whose terms are ecosystems, neurobiology, "
                "multiple sclerosis and anxiety disorders. Ecosystems and "
                "neurobiology are both natural sciences, and both are still "
                "biological sciences one level down, so no level of this test "
                "catches it. Tightening the test to the next level down flags "
                "63 percent of listed organisations instead of 25 and still "
                "misses that case, so the conservative version is kept and this "
                "number is a floor on the problem, not a measure of it."
            ),
            "a_named_case_the_test_correctly_clears": (
                "Region Hovedstaden also reaches Ecology through project "
                "101112723, on remediation and restoration of contaminated "
                "land, which is a genuinely ecological link. A health region "
                "under Ecology looks wrong and is not always wrong"
            ),
            "not_a_wrongness_measure": (
                "weak support is not the same as a wrong link. Blue World "
                "Technologies reaches Organic Chemistry through the term "
                "alcohols on a bio-methanol project, which is uncorroborated and "
                "entirely correct"
            ),
            "organisation_by_topic_links_in_corpus": tag_totals["all"],
            "corroborated": tag_totals["corroborated"],
            "minority_tag": tag_totals["minority_tag"],
            "single_tag": tag_totals["single_tag"],
            "weakly_supported_pct_of_corpus": tag_totals["weak_pct"],
            "weakly_supported_pct_of_listed_organisations": listed_weak_pct,
            "worst_candidates": worst_tagged,
            "worst_carrying_terms": worst_terms,
            "named_examples": named_examples,
        },
        "topic_assignment_accuracy": topic_accuracy,
        "falsification_spotcheck": (
            read_json(os.path.join(DERIVED, "spotcheck.json"))
            if os.path.exists(os.path.join(DERIVED, "spotcheck.json"))
            else {
                "status": (
                    "not run yet. Run study/spotcheck.py after this script to "
                    "test the not-yet-connected claims against OpenAlex "
                    "co-authorship, then run this script again to fold the "
                    "result in"
                )
            }
        ),
        "top_candidates_already_collaborating": {
            "top_n_examined": len(top),
            "candidates_where_a_danish_organisation_already_shares_an_au_project_on_the_same_topic": n_with_existing,
            "share_pct_same_topic": round(100.0 * n_with_existing / len(top), 1) if top else 0.0,
            "candidates_where_a_danish_organisation_already_shares_an_au_project_on_any_topic": n_with_existing_any,
            "share_pct_any_topic": round(100.0 * n_with_existing_any / len(top), 1) if top else 0.0,
            "candidates_where_au_already_has_a_company_coauthor_in_that_topic": n_with_company,
            "per_candidate": already,
            "note": (
                "a shared Horizon Europe project is the only kind of existing "
                "collaboration this can see; two organisations can work together "
                "through contract research, Innovation Fund Denmark, a student "
                "project or a consultancy and leave no trace in CORDIS, so this "
                "is a floor on existing collaboration and never a ceiling"
            ),
        },
    }
    write_json(os.path.join(DERIVED, "honesty.json"), honesty)

    out = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "what_this_is": (
            "candidate Actions: a department at the AU Faculty of Natural "
            "Sciences paired with a topic where Danish organisations are active "
            "in Horizon Europe. Each entry is a proposal for a conversation, "
            "not a partnership, and carries the evidence that produced it."
        ),
        "unit_of_analysis": "AU Natural Sciences department by OpenAlex subfield",
        "danish_partner_scope": {
            "activity_types_included": sorted(PARTNER_ACTIVITY_TYPES),
            "activity_type_excluded": "HES",
            "why": (
                "an Action pairs AU with an external partner, so other "
                "universities are not candidates"
            ),
        },
        "no_person_level_output": (
            "person identifiers, institutional email addresses and office "
            "addresses were removed from the Pure feed at harvest time, so no "
            "person-level ranking can be derived from these files"
        ),
        "window": {"publication_years_from": args.year_from},
        "thresholds": {
            "min_department_works_in_topic": args.min_works,
            "min_danish_organisations_on_topic": args.min_orgs,
        },
        "sources": {
            "faculty_and_department": "AU Pure OAI-PMH, ddf-mxd, https://pure.au.dk/ws/oai",
            "topic_and_coauthors": "OpenAlex, institution I204337017",
            "danish_organisations": "CORDIS Horizon Europe bulk export, CC BY 4.0",
        },
        "coverage_warning": oa_cov.get("coverage_warning"),
        "harvest_and_coverage_by_year": {
            "what_this_is": (
                "what the harvest actually covered, and how much of it reached "
                "a topic. The Pure harvest is even across the window; the "
                "unevenness downstream is the OpenAlex lookup, not the harvest"
            ),
            "all_au_records_harvested_by_publication_year": pure_cov[
                "harvest_census"
            ]["all_au_records_by_publication_year"],
            "records_harvested_per_set": pure_cov["harvest_census"][
                "all_au_records_by_harvested_set"
            ],
            "natural_sciences_works_by_publication_year": pure_cov[
                "harvest_census"
            ]["natural_sciences_works_by_publication_year"],
            "natural_sciences_works_with_doi_by_publication_year": pure_cov[
                "harvest_census"
            ]["natural_sciences_works_with_doi_by_publication_year"],
            "openalex_coverage_by_publication_year": oa_cov.get(
                "coverage_by_publication_year", {}
            ),
        },
        "counts": {
            "candidate_pairs_clearing_thresholds": len(actions),
            "actions_written": len(top),
            "white_space_in_written": sum(1 for a in top if a["white_space"]),
            "departments_represented": len({a["department"] for a in top}),
        },
        "honesty_panel": "data/derived/honesty.json",
        # A global top 40 is led by whichever departments publish most, so a
        # smaller department can be absent from it while still having a good
        # Action available. This index gives every department that clears the
        # thresholds its own best candidates, which is the view an office that
        # has to serve the whole faculty actually needs.
        "best_per_department": {
            dept: [
                {
                    "rank": a["rank"],
                    "action_id": a["action_id"],
                    "topic": a["topic"]["subfield"],
                    "score": a["score"],
                    "white_space": a["white_space"],
                    "au_works": a["au_evidence"]["works_in_window"],
                    "danish_organisations": a["danish_evidence"][
                        "organisations_on_this_topic"
                    ],
                }
                for a in actions
                if a["department"] == dept
            ][:5]
            for dept in sorted({a["department"] for a in actions})
        },
        "actions": top,
    }
    write_json(os.path.join(DATA, "actions.json"), out)

    log(
        f"{len(actions)} candidates, wrote top {len(top)}, "
        f"{out['counts']['white_space_in_written']} flagged white space, "
        f"{out['counts']['departments_represented']} departments"
    )


if __name__ == "__main__":
    main()
