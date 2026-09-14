"""Danish organisations in Horizon Europe, placed on the same topic map as the AU papers.

Two jobs.

1. Put CORDIS projects onto the OpenAlex subfield vocabulary, so that "what AU
   publishes" and "what Danish organisations work on" can be compared at all.
   CORDIS classifies projects with euroSciVoc, OpenAlex classifies papers with
   its own topic tree. The bridge is built mechanically, never by hand: a
   euroSciVoc term is matched to an OpenAlex subfield name, then to an OpenAlex
   topic name. If the leaf term matches nothing, the walk moves up the
   euroSciVoc path and tries the parent, and the number of levels it had to
   climb is recorded so a coarse match can be told apart from an exact one.
   Nothing is invented: a term that reaches the top of its path without matching
   is left unmapped and counted as unmapped. A third route, matching the term
   against OpenAlex topic KEYWORDS, is available behind --with-keyword-matching
   but is off by default because hand-checking found it unreliable. See
   TRUSTED_METHODS below for the evidence.

2. Decide whether AU has already worked with an organisation. This is a hard
   join on the CORDIS participant identifier: organisation X and Aarhus
   University both appear on the same projectID. Names are never compared.
   That matters because "AARHUS UNIVERSITET", "Aarhus Universitetshospital",
   "Aarhus Kommune" and "Arkitektskolen i Aarhus" are four different
   participants with four different identifiers, and a name match would merge
   them and produce a false collaboration claim.

Usage:
    python3 study/partners.py
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import os
import re
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd  # noqa: E402

from common import (  # noqa: E402
    CONTACT,
    CORDIS,
    DERIVED,
    OPENALEX_RAW,
    load_cordis_projects,
    log,
    polite_get,
    read_gz,
    write_gz,
    write_json,
)

AU_PARTICIPANT_ID = "999997736"

# Verified in FACTS.md and re-checked by this script. These are separate legal
# entities that a name match would wrongly fold into Aarhus University.
NOT_AARHUS_UNIVERSITY = {
    "999643880": "Aarhus Universitetshospital",
    "992597994": "Aarhus Kommune",
    "968659849": "Arkitektskolen i Aarhus",
}

# CORDIS activity types, spelled out because the three letter codes are opaque.
ACTIVITY_TYPES = {
    "PRC": "private for-profit",
    "HES": "higher or secondary education",
    "REC": "research organisation",
    "PUB": "public body",
    "OTH": "other",
}


def norm(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------------------
# The OpenAlex side of the bridge
# ---------------------------------------------------------------------------


def load_openalex_taxonomy(min_interval: float) -> tuple[dict, dict, dict]:
    """Fetch and cache the OpenAlex subfield and topic lists.

    Small and stable, a few hundred kB, so it is cached once and reused.
    """
    sub_path = os.path.join(OPENALEX_RAW, "taxonomy_subfields.json.gz")
    top_path = os.path.join(OPENALEX_RAW, "taxonomy_topics.json.gz")

    def fetch_all(endpoint: str, cache: str) -> list:
        if os.path.exists(cache):
            return json.loads(read_gz(cache))
        out: list = []
        page = 1
        while True:
            url = (
                f"https://api.openalex.org/{endpoint}"
                f"?per-page=200&page={page}&mailto={CONTACT}"
            )
            payload = json.loads(
                polite_get(
                    url, host_key="api.openalex.org",
                    min_interval=min_interval, accept="application/json",
                ).decode("utf-8")
            )
            out.extend(payload["results"])
            if len(out) >= payload["meta"]["count"] or not payload["results"]:
                break
            page += 1
        write_gz(cache, json.dumps(out))
        log(f"  fetched {len(out)} {endpoint}")
        return out

    subfields = fetch_all("subfields", sub_path)
    topics = fetch_all("topics", top_path)

    by_subfield_name = {}
    for s in subfields:
        by_subfield_name[norm(s["display_name"])] = {
            "subfield_id": s["id"].rsplit("/", 1)[-1],
            "subfield": s["display_name"],
            "field": s["field"]["display_name"],
            "domain": s["domain"]["display_name"],
        }

    by_topic_name = {}
    keyword_votes: dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter
    )
    for t in topics:
        rec = {
            "subfield_id": t["subfield"]["id"].rsplit("/", 1)[-1],
            "subfield": t["subfield"]["display_name"],
            "field": t["field"]["display_name"],
            "domain": t["domain"]["display_name"],
        }
        by_topic_name.setdefault(norm(t["display_name"]), rec)
        for kw in t.get("keywords") or []:
            keyword_votes[norm(kw)][json.dumps(rec, sort_keys=True)] += 1

    return by_subfield_name, by_topic_name, keyword_votes


# Which matching routes are trusted, decided by hand-checking twenty sampled
# assignments and recorded in study/topic_check_verdicts.json.
#
# The split was clean enough to act on rather than just note. Of the five
# sampled mappings made by matching a euroSciVoc term to an OpenAlex SUBFIELD
# NAME, four were right and one was merely coarse; none was wrong. Of the five
# made by matching the term to an OpenAlex TOPIC KEYWORD, four were plainly
# wrong and the fifth was only adjacent; none was right. The keyword route fails
# because it matches word forms rather than meanings: "atmospheric turbulence"
# is a keyword on free-space optics topics, so a meteorology term was filed
# under optics; "cryptography" was filed under Artificial Intelligence; "coal"
# under Mechanical Engineering. Those were exact leaf matches, so climbing the
# path is not what made them unreliable, the route is.
#
# So the keyword route is off by default. It roughly halves how many euroSciVoc
# terms can be mapped, and the honest trade is fewer candidate Actions that mean
# what they say over more that do not. Pass --with-keyword-matching to put it
# back and reproduce the earlier, wider, less reliable bridge.
TRUSTED_METHODS = ("subfield_name", "topic_name")


def build_term_bridge(min_interval: float, use_keywords: bool) -> tuple[dict, dict]:
    """Map every euroSciVoc path to an OpenAlex subfield, or leave it unmapped."""
    by_sub, by_top, kw_votes = load_openalex_taxonomy(min_interval)

    def lookup(term: str):
        n = norm(term)
        if n in by_sub:
            return "subfield_name", by_sub[n]
        if n in by_top:
            return "topic_name", by_top[n]
        if use_keywords and n in kw_votes:
            votes = kw_votes[n]
            best, count = votes.most_common(1)[0]
            # A keyword that several subfields share is only accepted when one
            # of them clearly dominates, otherwise the assignment is a coin flip
            # and the term is better left unmapped.
            if len(votes) == 1 or count > sum(votes.values()) / 2:
                return "topic_keyword", json.loads(best)
        return None, None

    voc = pd.read_csv(
        os.path.join(CORDIS, "euroSciVoc.csv"),
        sep=";", encoding="utf-8-sig", dtype=str, low_memory=False,
    )
    paths = sorted(set(voc["euroSciVocPath"].dropna()))
    bridge = {}
    method_counts: collections.Counter = collections.Counter()
    climb_counts: collections.Counter = collections.Counter()

    for path in paths:
        parts = [p for p in path.split("/") if p]
        matched = False
        for i in range(len(parts) - 1, -1, -1):
            method, rec = lookup(parts[i])
            if method:
                climb = len(parts) - 1 - i
                bridge[path] = dict(
                    rec,
                    match_method=method,
                    matched_term=parts[i],
                    levels_above_leaf=climb,
                    leaf_term=parts[-1],
                )
                method_counts[method] += 1
                climb_counts[climb] += 1
                matched = True
                break
        if not matched:
            method_counts["unmapped"] += 1

    stats = {
        "keyword_route_used": use_keywords,
        "euroscivoc_paths_total": len(paths),
        "euroscivoc_paths_mapped": len(bridge),
        "map_rate_pct": round(100.0 * len(bridge) / len(paths), 1) if paths else 0.0,
        "method_counts": dict(method_counts),
        "levels_above_leaf": {str(k): v for k, v in sorted(climb_counts.items())},
        "exact_leaf_match": climb_counts.get(0, 0),
    }
    return bridge, stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-interval", type=float, default=0.3)
    ap.add_argument("--with-keyword-matching", action="store_true",
                    help="also map euroSciVoc terms via OpenAlex topic keywords. "
                         "Hand-checking found this route unreliable, see "
                         "TRUSTED_METHODS above")
    args = ap.parse_args()

    log("building the euroSciVoc to OpenAlex subfield bridge")
    bridge, bridge_stats = build_term_bridge(
        args.min_interval, args.with_keyword_matching
    )
    bridge_stats["trusted_methods"] = list(TRUSTED_METHODS)
    bridge_stats["keyword_matching_enabled"] = args.with_keyword_matching
    write_json(os.path.join(DERIVED, "topic_bridge.json"), bridge)
    log(
        f"  mapped {bridge_stats['euroscivoc_paths_mapped']} of "
        f"{bridge_stats['euroscivoc_paths_total']} euroSciVoc paths"
    )

    log("reading CORDIS")
    org = pd.read_csv(
        os.path.join(CORDIS, "organization.csv"),
        sep=";", encoding="utf-8-sig", dtype=str, low_memory=False,
    )
    proj, proj_stats = load_cordis_projects()
    log(
        f"  project.csv: {proj_stats['rows_usable_for_this_study']} usable rows, "
        f"{proj_stats['rows_running_long_from_unescaped_quotes']} malformed by "
        f"unescaped quotes in the objective text"
    )
    voc = pd.read_csv(
        os.path.join(CORDIS, "euroSciVoc.csv"),
        sep=";", encoding="utf-8-sig", dtype=str, low_memory=False,
    )

    # Money fields use a decimal comma. Parsed explicitly so a silent string
    # sort never gets mistaken for a numeric one.
    def money(series: pd.Series) -> pd.Series:
        return pd.to_numeric(
            series.astype("string").str.replace(",", ".", regex=False),
            errors="coerce",
        ).fillna(0.0)

    org["ecContribution_num"] = money(org["ecContribution"])
    proj["ecMaxContribution_num"] = money(proj["ecMaxContribution"])

    au = org[org["organisationID"] == AU_PARTICIPANT_ID]
    au_projects = set(au["projectID"])
    log(f"  Aarhus University ({AU_PARTICIPANT_ID}) on {len(au_projects)} projects")

    for bad_id, label in NOT_AARHUS_UNIVERSITY.items():
        n = org[org["organisationID"] == bad_id]["projectID"].nunique()
        log(f"  held separate: {label} ({bad_id}) on {n} projects")

    # Project to subfield, through the bridge.
    voc["_key"] = voc["euroSciVocPath"]
    mapped = voc["_key"].map(lambda p: bridge.get(p))
    voc["subfield"] = [m["subfield"] if m else None for m in mapped]
    voc["subfield_id"] = [m["subfield_id"] if m else None for m in mapped]
    voc["field"] = [m["field"] if m else None for m in mapped]
    voc["domain"] = [m["domain"] if m else None for m in mapped]
    voc["levels_above_leaf"] = [
        m["levels_above_leaf"] if m else None for m in mapped
    ]
    voc["match_method"] = [m["match_method"] if m else None for m in mapped]

    proj_sub = (
        voc.dropna(subset=["subfield"])[
            ["projectID", "subfield_id", "subfield", "field", "domain",
             "euroSciVocTitle", "levels_above_leaf", "match_method"]
        ]
        .drop_duplicates(subset=["projectID", "subfield_id"])
    )
    proj_sub.to_csv(
        os.path.join(DERIVED, "cordis_project_subfields.csv"), index=False
    )
    log(
        f"  {proj_sub['projectID'].nunique()} of {voc['projectID'].nunique()} "
        f"CORDIS projects placed on a subfield"
    )

    # Danish organisations, excluding AU itself.
    dk = org[(org["country"] == "DK") & (org["organisationID"] != AU_PARTICIPANT_ID)]
    dk = dk.copy()

    # Which Danish organisations already share a project with AU. Hard join on
    # participant identifier, on both sides of a shared projectID.
    dk["shares_project_with_au"] = dk["projectID"].isin(au_projects)
    au_link = (
        dk[dk["shares_project_with_au"]]
        .groupby("organisationID")["projectID"]
        .apply(lambda s: sorted(set(s)))
        .to_dict()
    )

    # One row per organisation, with its name taken from its most recent row so
    # a renamed entity does not appear twice.
    dk_sorted = dk.sort_values("contentUpdateDate")
    org_info = (
        dk_sorted.groupby("organisationID")
        .agg(
            name=("name", "last"),
            short_name=("shortName", "last"),
            activity_type=("activityType", "last"),
            sme=("SME", "last"),
            city=("city", "last"),
            nuts=("nutsCode", "last"),
            url=("organizationURL", "last"),
            n_projects=("projectID", "nunique"),
            ec_contribution=("ecContribution_num", "sum"),
        )
        .reset_index()
    )
    org_info["activity_label"] = org_info["activity_type"].map(
        lambda a: ACTIVITY_TYPES.get(a, a or "unknown")
    )
    org_info["au_shared_projects"] = org_info["organisationID"].map(
        lambda o: len(au_link.get(o, []))
    )
    org_info["already_worked_with_au"] = org_info["au_shared_projects"] > 0
    org_info["au_shared_project_ids"] = org_info["organisationID"].map(
        lambda o: "|".join(au_link.get(o, []))
    )
    org_info.to_csv(os.path.join(DERIVED, "cordis_dk_organisations.csv"), index=False)
    log(f"  {len(org_info)} distinct Danish organisations in Horizon Europe")

    # Organisation by subfield.
    dk_topics = dk[["organisationID", "projectID"]].drop_duplicates().merge(
        proj_sub[["projectID", "subfield_id", "subfield", "field", "domain"]],
        on="projectID", how="inner",
    )
    titles = proj.set_index("id")["title"].to_dict()
    acronyms = proj.set_index("id")["acronym"].to_dict()
    start = proj.set_index("id")["startDate"].to_dict()

    rows = []
    for (oid, sid), grp in dk_topics.groupby(["organisationID", "subfield_id"]):
        pids = sorted(set(grp["projectID"]))
        # Whether AU and this organisation have met ON THIS TOPIC, which is a
        # different and much more useful question than whether they have ever
        # met at all. Vestas and AU can share a wind project and still never
        # have worked together on microbial ecology, and a global flag would
        # wrongly mark that topic as already covered.
        shared_here = sorted(set(pids) & au_projects)
        rows.append(
            {
                "organisationID": oid,
                "subfield_id": sid,
                "subfield": grp["subfield"].iloc[0],
                "field": grp["field"].iloc[0],
                "domain": grp["domain"].iloc[0],
                "n_projects": len(pids),
                "n_au_shared_projects_on_topic": len(shared_here),
                "au_shared_project_ids_on_topic": "|".join(shared_here),
                "project_ids": "|".join(pids),
                "project_acronyms": "|".join(
                    acronyms.get(p, "") or "" for p in pids[:8]
                ),
                "project_titles": "|".join(
                    (titles.get(p, "") or "")[:160] for p in pids[:4]
                ),
                "earliest_start": min(
                    (start.get(p) or "9999" for p in pids), default=""
                ),
            }
        )
    dk_topic_df = pd.DataFrame(rows)
    dk_topic_df.to_csv(
        os.path.join(DERIVED, "cordis_dk_org_subfields.csv"), index=False
    )
    log(f"  {len(dk_topic_df)} organisation by subfield rows")

    # The AU partner list from FACTS.md, recomputed rather than trusted.
    partner_rows = org[
        org["projectID"].isin(au_projects)
        & (org["organisationID"] != AU_PARTICIPANT_ID)
    ]
    dk_prc_partners = partner_rows[
        (partner_rows["country"] == "DK") & (partner_rows["activityType"] == "PRC")
    ]
    checks = {
        "au_participant_id": AU_PARTICIPANT_ID,
        "au_projects": len(au_projects),
        "partner_rows_on_au_projects": len(partner_rows),
        "partner_rows_including_au_own_rows": len(partner_rows) + len(au),
        "danish_for_profit_partner_rows": len(dk_prc_partners),
        "danish_for_profit_partner_orgs": dk_prc_partners["organisationID"].nunique(),
        "danish_orgs_in_horizon_europe_total": int(dk["organisationID"].nunique()),
        "danish_for_profit_orgs_in_horizon_europe_total": int(
            dk[dk["activityType"] == "PRC"]["organisationID"].nunique()
        ),
        "danish_orgs_with_no_au_project": int((~org_info["already_worked_with_au"]).sum()),
    }
    write_json(
        os.path.join(DERIVED, "cordis_checks.json"),
        {
            "facts_recheck": checks,
            "topic_bridge": bridge_stats,
            "cordis_project_file": proj_stats,
        },
    )
    log(
        f"  recheck: {checks['danish_for_profit_partner_rows']} Danish for-profit "
        f"partner rows covering {checks['danish_for_profit_partner_orgs']} organisations"
    )


if __name__ == "__main__":
    main()
