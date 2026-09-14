"""Try to disprove the tool's own "not yet working together" claims.

The CORDIS join can only see one kind of collaboration: a shared Horizon Europe
project. Two organisations can have worked together for years through contract
research, an Innovation Fund Denmark grant, a PhD placement or a consultancy and
leave nothing in CORDIS at all. So "no shared Horizon Europe project" is a floor
on existing collaboration, never a ceiling, and a tool that presented it as a
ceiling would be lying by omission.

This script goes looking for the collaboration CORDIS cannot see. It takes
organisations the ranked list calls not yet connected, finds them in OpenAlex,
and asks whether they have co-authored a paper with Aarhus University anyway.

On name matching. Everywhere else in this project the AU link is a hard join on
the CORDIS participant identifier, because a name match can silently merge
Aarhus University with Aarhus University Hospital and manufacture a partnership
that does not exist. Here a name match is used on purpose, and it is safe in
this direction only, because of an asymmetry:

    a hit DISPROVES "they have never worked together", which is the claim under
    test, and a false positive costs us a candidate we should not have proposed;

    a miss PROVES NOTHING, because it can equally mean the name did not resolve.

So hits are reported as findings and misses are reported as unknown, never as
confirmation. Every matched name is written into the output so a reader can see
which organisation was actually looked up and throw out a bad match.

Usage:
    python3 study/spotcheck.py
"""

from __future__ import annotations

import argparse
import json
import os
import collections
import random
import re
import sys
import unicodedata
import urllib.parse

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

STUDY = os.path.dirname(os.path.abspath(__file__))

from common import (  # noqa: E402
    CONTACT,
    DATA,
    DERIVED,
    log,
    polite_get,
    read_json,
    write_json,
)

AU_OPENALEX = "I204337017"
SAMPLE_SEED = 20260914


def api(path: str, min_interval: float) -> dict:
    url = f"https://api.openalex.org/{path}&mailto={CONTACT}"
    return json.loads(
        polite_get(
            url, host_key="api.openalex.org", min_interval=min_interval,
            accept="application/json",
        ).decode("utf-8")
    )


# Danish company names are the awkward part of this check, for three reasons
# found by testing the endpoint rather than by assuming:
#
#   1. CORDIS stores the registered legal name, "ORSTED WIND POWER A/S", while
#      OpenAlex stores a short display name, "Ørsted (Denmark)". The legal form
#      suffix has to come off or nothing matches.
#   2. OpenAlex search does not fold Danish characters. "Ørsted" returns the
#      institution and "orsted" returns nothing at all, and CORDIS writes the
#      ASCII form, so the accented spellings have to be tried explicitly.
#   3. A longer query is not a better query. "Nokia" returns seventeen
#      institutions and "Nokia Bell Labs" returns none, so the cascade has to
#      get shorter, not longer, when a query comes back empty.
#
# Combining country_code:DK with search returns zero for every query tested, so
# the country filter is applied here in Python on the results instead.

LEGAL_FORMS = re.compile(
    r"(?i)(?:^|[\s,])(?:a/s|aps|ap/s|i/s|k/s|p/s|ivs|s/a|a\.m\.b\.a\.?|amba|"
    r"as|holding|group|denmark|danmark)(?=[\s,]|$)"
)


def strip_legal_form(name: str) -> str:
    out = LEGAL_FORMS.sub(" ", " " + name + " ")
    return re.sub(r"\s+", " ", out).strip(" ,.-")


def fold(text: str) -> str:
    """Reduce to lowercase ASCII so Ørsted and ORSTED compare equal."""
    text = text.replace("ø", "o").replace("Ø", "O")
    text = text.replace("æ", "ae").replace("Æ", "AE")
    text = text.replace("å", "aa").replace("Å", "AA")
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]", " ", ascii_only.lower()).strip()


def danish_spellings(word: str) -> list[str]:
    """Candidate accented spellings of an ASCII word, most likely first."""
    out = [word]
    swaps = {"o": "ø", "a": ["å", "æ"], "e": "é"}
    for i, ch in enumerate(word):
        repl = swaps.get(ch.lower())
        if not repl:
            continue
        for r in [repl] if isinstance(repl, str) else repl:
            out.append(word[:i] + r + word[i + 1 :])
    seen = set()
    unique = []
    for w in out:
        if w.lower() not in seen:
            seen.add(w.lower())
            unique.append(w)
    # Capped tightly. Each extra spelling is another request against a rate
    # limited endpoint, and the first few cover the real Danish cases.
    return unique[:4]


def resolve_institution(name: str, min_interval: float) -> tuple[dict | None, list[str]]:
    """Find a Danish OpenAlex institution for a CORDIS legal name.

    Returns the chosen institution and the queries tried, so a reader can see
    how hard the lookup worked before giving up.
    """
    cleaned = strip_legal_form(name)
    words = cleaned.split()
    queries: list[str] = []
    if cleaned:
        queries.append(cleaned)
    if len(words) >= 2:
        queries.append(" ".join(words[:2]))
    if words:
        queries.extend(danish_spellings(words[0]))

    tried: list[str] = []
    target = fold(cleaned)
    target_tokens = set(target.split())
    for q in queries:
        if len(q) < 3 or q in tried:
            continue
        tried.append(q)
        try:
            payload = api(
                "institutions?search=" + urllib.parse.quote(q) + "&per-page=10",
                min_interval,
            )
        except Exception:  # noqa: BLE001
            continue
        for r in payload.get("results") or []:
            if r.get("country_code") != "DK":
                continue
            # Accept only when the names actually share a distinctive word.
            # Without this, a short query pulls back an unrelated Danish
            # institution and the check would report a collaboration that
            # belongs to somebody else.
            hit_tokens = set(fold(r.get("display_name") or "").split())
            if hit_tokens & target_tokens:
                return r, tried
    return None, tried


def offline_check(actions: list) -> dict:
    """Test the not-yet-connected claims against data already on disk.

    study/openalex.py already recorded every co-authoring organisation on every
    Natural Sciences paper, including which of them OpenAlex types as a company
    and which are Danish. So the question "does this department already publish
    with this company" can be answered without a single further request, which
    matters because the OpenAlex institution search endpoint throttles hard
    enough to make a per-organisation lookup unreliable.

    This check is narrower than the API one in a useful way: it sees only
    co-authorship with the Faculty of Natural Sciences, not with all of Aarhus
    University, so a hit means the department itself has already published with
    that company rather than some other corner of AU.

    The name comparison carries the same asymmetry as everywhere else in this
    file. A hit disproves the claim. A miss proves nothing.
    """
    inst = pd.read_csv(
        os.path.join(DERIVED, "openalex_work_institutions.csv"), dtype=str
    )
    dk_companies = inst[
        (inst["inst_type"] == "company") & (inst["inst_country"] == "DK")
    ]

    # Which words are distinctive enough to match on is decided from the data,
    # not from a list written by hand. A first attempt matched "INNOVATIONSCENTER
    # FOR OKOLOGISK LANDBRUG" to "Knowledge Centre for Agriculture" on the word
    # "for", and "KNOWLEDGE HUB ZEALAND" to the same organisation on "knowledge".
    # Counting how many Danish organisation names each word appears in kills both
    # without anyone having to anticipate them: a word used across many
    # organisations identifies none of them.
    all_names = pd.read_csv(
        os.path.join(DERIVED, "cordis_dk_organisations.csv"), dtype=str
    )["name"].dropna().tolist()
    all_names += [
        re.sub(r"\s*\([^)]*\)\s*$", "", n)
        for n in set(dk_companies["inst_name"].dropna())
    ]
    doc_freq: dict[str, int] = collections.Counter()
    for n in all_names:
        for tok in set(fold(strip_legal_form(n)).split()):
            doc_freq[tok] += 1
    common = {t for t, c in doc_freq.items() if c >= 5}

    def distinctive(tokens: set) -> set:
        # Length four is the shortest that carries a real name in this data:
        # cowi, novo, topsoe. Anything shorter is a preposition or an initial.
        return {t for t in tokens if len(t) >= 4 and t not in common}
    # OpenAlex display names carry a country suffix, "Vestas (Denmark)", which
    # has to come off before the names can be compared with CORDIS legal names.
    observed: dict[str, set] = {}
    for name in sorted(set(dk_companies["inst_name"].dropna())):
        bare = re.sub(r"\s*\([^)]*\)\s*$", "", name)
        tokens = distinctive(set(fold(strip_legal_form(bare)).split()))
        if tokens:
            observed[name] = tokens

    findings = []
    checked = 0
    for a in actions:
        for o in a["danish_evidence"]["organisations"]:
            if o["shares_a_project_with_au_on_this_topic"]:
                continue
            checked += 1
            tokens = distinctive(set(fold(strip_legal_form(o["name"])).split()))
            if not tokens:
                continue
            for oa_name, oa_tokens in observed.items():
                if tokens & oa_tokens:
                    findings.append(
                        {
                            "rank": a["rank"],
                            "department": a["department"],
                            "topic": a["topic"]["subfield"],
                            "cordis_name": o["name"],
                            "cordis_participant_id": o["cordis_participant_id"],
                            "openalex_company_name": oa_name,
                            "shared_name_tokens": sorted(tokens & oa_tokens),
                        }
                    )
                    break

    # The name rule is deliberately over-sensitive. It exists to flag rows for a
    # human to read, not to decide anything, and it errs towards accusing the
    # tool of over-claiming rather than towards letting an over-claim through.
    # Document frequency cannot finish the job: "knowledge" appears in exactly
    # two organisation names in this corpus, the same as "cowi" and "unisense",
    # so no frequency threshold separates the false match from the true ones.
    # What settles it is reading them, and those readings are recorded in
    # study/spotcheck_verdicts.json and folded in here.
    verdict_path = os.path.join(STUDY, "spotcheck_verdicts.json")
    verdicts = read_json(verdict_path) if os.path.exists(verdict_path) else {}
    pairs = {}
    for f in findings:
        key = f"{f['cordis_name']}::{f['openalex_company_name']}"
        f["hand_verdict"] = verdicts.get(key, {}).get("verdict", "not checked")
        f["hand_note"] = verdicts.get(key, {}).get("note", "")
        pairs[key] = f["hand_verdict"]
    genuine = sum(1 for v in pairs.values() if v == "genuine")
    spurious = sum(1 for v in pairs.values() if v == "spurious")

    return {
        "what_it_tests": (
            "organisations the ranked list calls not yet connected on a topic, "
            "checked against the Danish companies that actually co-author "
            "papers with the Faculty of Natural Sciences"
        ),
        "distinct_name_pairs_matched": len(pairs),
        "hand_checked_genuine": genuine,
        "hand_checked_spurious": spurious,
        "hand_checked_pending": len(pairs) - genuine - spurious,
        "name_match_precision_pct": (
            round(100.0 * genuine / (genuine + spurious), 1)
            if (genuine + spurious)
            else None
        ),
        "organisation_claims_checked": checked,
        "claims_contradicted": len(findings),
        "contradicted_pct": (
            round(100.0 * len(findings) / checked, 1) if checked else 0.0
        ),
        "findings": findings,
        "match_rule": (
            "a shared word of at least four characters that appears in fewer "
            "than five Danish organisation names in the corpus"
        ),
        "distinctive_word_threshold": "appears in fewer than 5 of "
        f"{len(all_names)} organisation names",
        "caveat": (
            "matched on name tokens, so each finding should be read before it "
            "is believed. A miss is not evidence of no contact."
        ),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-api", action="store_true",
                    help="also run the slower OpenAlex institution lookup")
    ap.add_argument("--sample", type=int, default=8)
    ap.add_argument("--top", type=int, default=20,
                    help="how many ranked candidates to draw the sample from")
    # OpenAlex answered 429 Too Many Requests during testing at roughly three
    # requests a second on the search endpoint, even inside the polite pool, and
    # the backoff that follows costs far more time than the spacing does. One
    # request a second finishes sooner than a burst that gets throttled.
    ap.add_argument("--min-interval", type=float, default=1.0)
    args = ap.parse_args()

    actions = read_json(os.path.join(DATA, "actions.json"))["actions"][: args.top]

    pool = {}
    for a in actions:
        for o in a["danish_evidence"]["organisations"]:
            if o["shares_a_project_with_au_on_this_topic"]:
                continue
            # For-profit only. These are the organisations an Action would
            # actually be proposed with, and the ones where a wrong "never
            # worked together" would be most embarrassing in a meeting.
            if o["activity_code"] != "PRC":
                continue
            pool.setdefault(
                o["cordis_participant_id"],
                {
                    "name": o["name"],
                    "cordis_participant_id": o["cordis_participant_id"],
                    "claimed_for_actions": [],
                },
            )["claimed_for_actions"].append(
                {
                    "rank": a["rank"],
                    "department": a["department"],
                    "topic": a["topic"]["subfield"],
                }
            )

    candidates = sorted(pool.values(), key=lambda r: r["cordis_participant_id"])
    rng = random.Random(SAMPLE_SEED)
    rng.shuffle(candidates)
    sample = candidates[: args.sample]
    log(f"{len(candidates)} not-yet-connected for-profit organisations, checking {len(sample)}")

    results = []
    for row in (sample if args.with_api else []):
        name = row["name"]
        entry = dict(row)
        best, tried = resolve_institution(name, args.min_interval)
        entry["queries_tried"] = tried
        if best is None:
            entry["openalex_institution"] = None
            entry["verdict"] = (
                "unknown, no Danish OpenAlex institution matched the name. "
                "Most small Danish companies publish nothing and so have no "
                "OpenAlex institution record at all, which means this check "
                "cannot be run for them either way"
            )
            results.append(entry)
            continue

        inst_id = best["id"].rsplit("/", 1)[-1]
        entry["openalex_institution"] = {
            "id": inst_id,
            "matched_name": best.get("display_name"),
            "type": best.get("type"),
            "works_count": best.get("works_count"),
            "name_searched": name,
        }

        co = api(
            f"works?filter=institutions.lineage:{AU_OPENALEX},"
            f"institutions.lineage:{inst_id}"
            "&select=id,doi,title,publication_year&per-page=5",
            args.min_interval,
        )
        n = co.get("meta", {}).get("count", 0)
        entry["coauthored_works_with_au"] = n
        entry["examples"] = [
            {
                "title": w.get("title"),
                "doi": w.get("doi"),
                "year": w.get("publication_year"),
            }
            for w in (co.get("results") or [])[:3]
        ]
        entry["verdict"] = (
            "already collaborating, CORDIS could not see it"
            if n > 0
            else "no co-authored paper found, which is not proof of no contact"
        )
        results.append(entry)
        log(f"  {name[:44]:44s} co-authored works with AU: {n}")

    disproved = [r for r in results if r.get("coauthored_works_with_au", 0) > 0]
    unknown = [r for r in results if "unknown" in str(r.get("verdict", ""))]

    out = {
        "offline_check_against_natural_sciences_coauthorship": offline_check(actions),
        "api_check_run": bool(args.with_api),
        "what_this_is": (
            "an attempt to disprove the not-yet-connected claims in "
            "data/actions.json using a source CORDIS cannot see"
        ),
        "method": (
            "sample for-profit Danish organisations that the ranked list says "
            "share no Horizon Europe project with AU on that topic, resolve each "
            "to an OpenAlex institution by name, and count works co-authored by "
            "that institution and Aarhus University I204337017"
        ),
        "name_matching_caveat": (
            "a name match is used here and nowhere else. It is sound in one "
            "direction only: a hit disproves the claim under test, a miss proves "
            "nothing because the name may simply not have resolved. Matched "
            "names are listed so a bad match can be spotted and discarded."
        ),
        "sampled": len(results),
        "disproved_already_co_author_with_au": len(disproved),
        "disproved_pct": (
            round(100.0 * len(disproved) / len(results), 1) if results else 0.0
        ),
        "unresolved_names": len(unknown),
        "results": results,
    }
    write_json(os.path.join(DERIVED, "spotcheck.json"), out)
    off = out["offline_check_against_natural_sciences_coauthorship"]
    log(
        f"offline check: {off['claims_contradicted']} of "
        f"{off['organisation_claims_checked']} not-yet-connected claims are "
        f"contradicted by co-authorship ({off['contradicted_pct']}%), across "
        f"{off['distinct_name_pairs_matched']} distinct organisations, of which "
        f"{off['hand_checked_genuine']} were read and confirmed genuine and "
        f"{off['hand_checked_spurious']} spurious"
    )
    if args.with_api:
        log(
            f"api check: {len(disproved)} of {len(results)} sampled "
            f"organisations co-author with AU despite no shared project"
        )
    else:
        log("api check: not run, pass --with-api to enable it")


if __name__ == "__main__":
    main()
