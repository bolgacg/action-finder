"""Look up the Natural Sciences DOIs in OpenAlex and keep topic and co-author affiliations.

Pure tells us which AU faculty and department a paper belongs to, which OpenAlex
cannot. OpenAlex tells us what the paper is about in a vocabulary that is shared
across the whole literature, and who the co-authoring organisations were and what
type each of them is. Neither source can do the other's job, which is why both
are here.

The signal this step exists to produce: OpenAlex marks an affiliation with
type "company". A paper co-authored with a company is direct evidence that the
department and industry already meet on that topic. Its absence, across a topic
where the department publishes steadily, is the white space the Action finder is
looking for.

Usage:
    python3 study/openalex.py
    python3 study/openalex.py --limit 500      # short run while testing
"""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import (  # noqa: E402
    CONTACT,
    DERIVED,
    OPENALEX_RAW,
    log,
    normalise_doi,
    polite_get,
    read_gz,
    read_json,
    write_gz,
    write_json,
)

API = "https://api.openalex.org/works"
# OpenAlex allows up to 50 values in an OR filter. One request per 50 DOIs is
# both the documented limit and far kinder than one request per DOI.
BATCH = 50
SELECT = ",".join(
    [
        "id",
        "doi",
        "publication_year",
        "type",
        "primary_topic",
        "topics",
        "authorships",
        "institutions_distinct_count",
        "cited_by_count",
    ]
)


# The cache is keyed per DOI, not per batch.
#
# Batching is a request-shaping decision: fifty DOIs in one OR filter is far
# kinder to OpenAlex than fifty requests. But it is a terrible cache key. The
# first version of this file keyed the cache on the loop index, which served the
# wrong batch as soon as the DOI list grew. Hashing the batch contents fixed the
# correctness problem and left a waste problem: adding one DOI reshuffles every
# chunk after it, so an eight thousand DOI run threw away a two thousand DOI
# cache that was still perfectly valid.
#
# That waste stopped being theoretical when OpenAlex rate limited this address
# mid-run and answered every request with Retry-After of about five hours. What
# has already been fetched now has to survive across days and across any change
# to the DOI list, so each work is stored under its own DOI and the batching
# exists only to shape the requests that are still needed.
BATCH_DIR = os.path.join(OPENALEX_RAW, "batches")
WORK_DIR = os.path.join(OPENALEX_RAW, "works")
MISS_PATH = os.path.join(OPENALEX_RAW, "known_misses.json")


def work_path(doi: str) -> str:
    key = hashlib.sha1(doi.encode("utf-8")).hexdigest()
    return os.path.join(WORK_DIR, key[:2], f"{key}.json.gz")


def cache_work(doi: str, work: dict) -> None:
    write_gz(work_path(doi), json.dumps(work))


def load_cached_work(doi: str) -> dict | None:
    path = work_path(doi)
    if os.path.exists(path):
        return json.loads(read_gz(path))
    return None


def migrate_batches() -> int:
    """Move anything held in an older batch-shaped cache into the per-DOI cache."""
    moved = 0
    for folder in (OPENALEX_RAW, BATCH_DIR):
        if not os.path.isdir(folder):
            continue
        for fname in sorted(os.listdir(folder)):
            if not fname.startswith("works_") or not fname.endswith(".json.gz"):
                continue
            try:
                payload = json.loads(read_gz(os.path.join(folder, fname)))
            except (OSError, ValueError):
                continue
            for w in payload.get("results", []):
                doi = normalise_doi(w.get("doi"))
                if doi and not os.path.exists(work_path(doi)):
                    cache_work(doi, w)
                    moved += 1
    return moved


def fetch_batch(dois: list[str], min_interval: float) -> dict:
    filt = "doi:" + "|".join(dois)
    url = (
        f"{API}?filter={urllib.parse.quote(filt, safe=':|/.')}"
        f"&select={SELECT}&per-page={BATCH}&mailto={CONTACT}"
    )
    raw = polite_get(
        url, host_key="api.openalex.org", min_interval=min_interval,
        accept="application/json",
    ).decode("utf-8")
    return json.loads(raw)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-requests", type=int, default=0,
                    help="stop after this many API requests, 0 for no budget")
    # See the note in spotcheck.py: OpenAlex returns 429 well below the
    # documented ten requests a second on some endpoints. Batching 50 DOIs per
    # request already keeps the total call count low, so spacing them out costs
    # little and avoids the backoff entirely.
    ap.add_argument("--min-interval", type=float, default=0.5)
    args = ap.parse_args()

    works_csv = os.path.join(DERIVED, "pure_natsci_works.csv")
    if not os.path.exists(works_csv):
        raise SystemExit(f"run pure_harvest.py first, {works_csv} is missing")

    with open(works_csv, encoding="utf-8") as fh:
        pure_rows = list(csv.DictReader(fh))

    dois = []
    seen = set()
    for row in pure_rows:
        doi = normalise_doi(row.get("doi"))
        if doi and doi not in seen:
            seen.add(doi)
            dois.append(doi)
    if args.limit:
        dois = dois[: args.limit]
    log(f"{len(pure_rows)} Pure works, {len(dois)} distinct DOIs to look up")

    moved = migrate_batches()
    if moved:
        log(f"migrated {moved} works from the old batch cache into the per-DOI cache")

    # DOIs OpenAlex has already been asked about and had no record for. Without
    # this, every run re-asks for the same permanently absent DOIs and spends
    # its request budget learning nothing.
    known_misses = set(read_json(MISS_PATH)) if os.path.exists(MISS_PATH) else set()

    found: dict[str, dict] = {}
    todo: list[str] = []
    for doi in dois:
        cached = load_cached_work(doi)
        if cached is not None:
            found[doi] = cached
        elif doi not in known_misses:
            todo.append(doi)
    log(f"{len(found)} DOIs already cached, {len(todo)} still to fetch")

    requests_made = 0
    rate_limited = False
    for i in range(0, len(todo), BATCH):
        if args.max_requests and requests_made >= args.max_requests:
            log(f"stopping at the {args.max_requests} request budget")
            break
        chunk = todo[i : i + BATCH]
        try:
            payload = fetch_batch(chunk, args.min_interval)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                # Do not sit on a multi-hour Retry-After. Everything fetched so
                # far is already on disk per DOI, so stopping here costs nothing
                # and the run resumes from exactly this point later.
                retry_after = (exc.headers or {}).get("Retry-After")
                log(
                    f"OpenAlex rate limited this address (429). Retry-After is "
                    f"{retry_after} seconds. Stopping with "
                    f"{len(todo) - i} DOIs still unfetched; rerun this script "
                    f"later and it will resume from the cache."
                )
                rate_limited = True
                break
            raise
        requests_made += 1
        returned = set()
        for w in payload.get("results", []):
            doi = normalise_doi(w.get("doi"))
            if doi:
                found[doi] = w
                cache_work(doi, w)
                returned.add(doi)
        # A DOI asked for and not returned is a real absence, worth remembering.
        for doi in chunk:
            if doi not in returned:
                known_misses.add(doi)
        if requests_made % 20 == 1:
            log(f"  request {requests_made}, {len(found)} works held")

    write_json(MISS_PATH, sorted(known_misses))
    log(
        f"per-DOI cache holds {len(found)} of {len(dois)} DOIs; "
        f"{len(known_misses)} confirmed absent from OpenAlex"
    )

    work_rows = []
    inst_rows = []
    topic_rows = []
    inst_type_counter: collections.Counter = collections.Counter()

    for doi, w in found.items():
        pt = w.get("primary_topic") or {}
        insts = {}
        for a in w.get("authorships") or []:
            for inst in a.get("institutions") or []:
                iid = (inst.get("id") or "").rsplit("/", 1)[-1]
                if not iid:
                    continue
                insts[iid] = {
                    "id": iid,
                    "name": inst.get("display_name") or "",
                    "type": inst.get("type") or "unknown",
                    "country": inst.get("country_code") or "",
                    "ror": inst.get("ror") or "",
                }
        for inst in insts.values():
            inst_type_counter[inst["type"]] += 1
            inst_rows.append(
                {
                    "doi": doi,
                    "inst_id": inst["id"],
                    "inst_name": inst["name"],
                    "inst_type": inst["type"],
                    "inst_country": inst["country"],
                    "inst_ror": inst["ror"],
                }
            )

        companies = [i for i in insts.values() if i["type"] == "company"]
        dk_companies = [i for i in companies if i["country"] == "DK"]

        for t in (w.get("topics") or [])[:3]:
            topic_rows.append(
                {
                    "doi": doi,
                    "topic_id": (t.get("id") or "").rsplit("/", 1)[-1],
                    "topic": t.get("display_name") or "",
                    "subfield_id": str(
                        ((t.get("subfield") or {}).get("id") or "")
                    ).rsplit("/", 1)[-1],
                    "subfield": (t.get("subfield") or {}).get("display_name") or "",
                    "field": (t.get("field") or {}).get("display_name") or "",
                    "domain": (t.get("domain") or {}).get("display_name") or "",
                    "score": t.get("score") or "",
                    "rank": "primary" if t is (w.get("topics") or [None])[0] else "secondary",
                }
            )

        work_rows.append(
            {
                "doi": doi,
                "openalex_id": (w.get("id") or "").rsplit("/", 1)[-1],
                "publication_year": w.get("publication_year") or "",
                "type": w.get("type") or "",
                "cited_by_count": w.get("cited_by_count") or 0,
                "primary_topic": pt.get("display_name") or "",
                "primary_topic_id": (pt.get("id") or "").rsplit("/", 1)[-1],
                "subfield": (pt.get("subfield") or {}).get("display_name") or "",
                "subfield_id": str(
                    ((pt.get("subfield") or {}).get("id") or "")
                ).rsplit("/", 1)[-1],
                "field": (pt.get("field") or {}).get("display_name") or "",
                "domain": (pt.get("domain") or {}).get("display_name") or "",
                "n_institutions": w.get("institutions_distinct_count") or 0,
                "n_companies": len(companies),
                "company_names": "|".join(sorted(i["name"] for i in companies)),
                "company_ids": "|".join(sorted(i["id"] for i in companies)),
                "company_countries": "|".join(
                    sorted({i["country"] for i in companies if i["country"]})
                ),
                "n_dk_companies": len(dk_companies),
                "dk_company_names": "|".join(sorted(i["name"] for i in dk_companies)),
            }
        )

    def dump(name: str, rows: list[dict]) -> None:
        """Write the union of this run's rows and any rows already on disk.

        This script is resumable, so a run that could only fetch part of the
        list must not throw away what an earlier run fetched. The first time the
        rate limit hit, a run that fetched nothing overwrote three good files
        with nothing, and the honest coverage number went to zero for reasons
        that had nothing to do with coverage. Rows are keyed by DOI: this run
        wins where it has data, disk wins everywhere else.
        """
        path = os.path.join(DERIVED, name)
        fresh_dois = {r["doi"] for r in rows}
        kept = 0
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                for old in csv.DictReader(fh):
                    if old.get("doi") and old["doi"] not in fresh_dois:
                        rows.append(old)
                        kept += 1
        if not rows:
            log(f"  no rows for {name}, leaving it alone")
            return
        fields = list(rows[0].keys())
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        log(f"wrote {path} ({len(rows)} rows, {kept} carried over from an earlier run)")

    dump("openalex_works.csv", work_rows)
    dump("openalex_work_institutions.csv", inst_rows)
    dump("openalex_work_topics.csv", topic_rows)

    # work_rows is the merged set after dump(), and rows carried over from an
    # earlier run arrive as strings from the CSV, so coerce before comparing.
    def as_int(v) -> int:
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    represented = {r["doi"] for r in work_rows}
    # Counted after the merge, so a DOI that an earlier run already resolved is
    # not also reported as never asked.
    unfetched = [
        d for d in dois if d not in represented and d not in known_misses
    ]
    with_company = sum(1 for r in work_rows if as_int(r["n_companies"]) > 0)
    with_dk_company = sum(1 for r in work_rows if as_int(r["n_dk_companies"]) > 0)
    with_topic = sum(1 for r in work_rows if r["subfield"])
    in_scope = represented & set(dois)

    coverage = {
        "pure_works_total": len(pure_rows),
        "pure_works_with_doi": len(dois),
        "openalex_matched": len(in_scope),
        "works_held_in_output_total": len(work_rows),
        "dois_fetched_this_run": len(found),
        "dois_confirmed_absent_from_openalex": len(known_misses),
        "dois_never_asked": len(unfetched),
        "lookup_complete": not unfetched,
        "rate_limited_this_run": rate_limited,
        "coverage_warning": (
            None
            if not unfetched
            else (
                f"{len(unfetched)} of {len(dois)} Natural Sciences DOIs have "
                "not been looked up, because OpenAlex rate limited this address "
                "with a Retry-After of about five hours. Everything downstream "
                "is computed on the "
                f"{len(in_scope)} DOIs that are covered, which is "
                f"{round(100.0 * len(in_scope) / len(dois), 1)} percent of them. "
                "Rerun study/openalex.py to finish the lookup; it resumes from "
                "the per-DOI cache."
            )
        ),
        "openalex_match_rate_pct": (
            round(100.0 * len(in_scope) / len(dois), 1) if dois else 0.0
        ),
        "matched_share_of_all_pure_works_pct": (
            round(100.0 * len(in_scope) / len(pure_rows), 1) if pure_rows else 0.0
        ),
        "matched_with_primary_subfield": with_topic,
        "matched_with_company_coauthor": with_company,
        "company_coauthor_share_pct": (
            round(100.0 * with_company / len(work_rows), 1) if work_rows else 0.0
        ),
        "matched_with_danish_company_coauthor": with_dk_company,
        "institution_type_counts": dict(inst_type_counter.most_common()),
        "institution_type_counts_scope": (
            "counted from works fetched in this run only"
            if found
            else "no works fetched in this run; see the institutions CSV"
        ),
        "note": (
            "A DOI that does not match is usually a chapter, report or "
            "conference item that was never registered with Crossref. "
            "Unmatched works are dropped from the topic analysis, not counted "
            "as zero-company."
        ),
    }
    write_json(os.path.join(DERIVED, "openalex_coverage.json"), coverage)
    log(
        f"output covers {len(in_scope)} of {len(dois)} DOIs "
        f"({coverage['openalex_match_rate_pct']}%), "
        f"{with_company} works have a company co-author"
    )
    if unfetched:
        log(f"INCOMPLETE: {coverage['coverage_warning']}")


if __name__ == "__main__":
    main()
