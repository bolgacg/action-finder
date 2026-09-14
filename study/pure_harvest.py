"""Harvest AU Pure over OAI-PMH and extract the Faculty of Natural Sciences.

Why this endpoint and not the others, from FACTS.md: the Pure REST API needs a
key, the portal HTML returns 403 and its footer reserves text and data mining
rights under EU DSM Article 4(3), and OpenAlex cannot tell us which AU faculty a
paper belongs to. https://pure.au.dk/ws/oai is open, it exists in order to be
harvested (it is what feeds the Danish national research database), and the
ddf-mxd format on it carries a four-level org hierarchy with the faculty at
level 2. That hierarchy is the whole reason this script exists.

Selection. OAI from/until filter on the record's modification datestamp, not on
when the work was published, so a datestamp window returns whatever Pure last
touched. Probing it returned a batch of 1998 and 1999 records. The
publications:yearYYYY sets select on publication year, which is what a recency
claim actually needs, so the harvest walks those sets.

Personal data is removed before any byte reaches the disk. See the long comment
on scrub_pure_xml in common.py for what goes and why.

Usage:
    python3 study/pure_harvest.py --years 2022 2023 2024 2025 2026
    python3 study/pure_harvest.py --parse-only
"""

from __future__ import annotations

import argparse
import collections
import csv
import html
import os
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import (  # noqa: E402
    DERIVED,
    PURE_RAW,
    audit_scrub,
    log,
    normalise_doi,
    polite_get,
    read_gz,
    scrub_pure_xml,
    write_gz,
    write_json,
)

OAI_BASE = "https://pure.au.dk/ws/oai"
FACULTY = "Natural Sciences"

NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "mxd": "http://mx.forskningsdatabasen.dk/ns/documents/1.4",
}

# ddf-mxd document type codes. Kept as a lookup rather than a filter: the counts
# per type go into the honesty panel so a reader can see how much of the corpus
# is journal articles and how much is conference material or reports.
DOC_TYPES = {
    "dja": "journal article",
    "djr": "journal review",
    "dje": "journal editorial",
    "djl": "journal letter",
    "djc": "journal conference article",
    "dba": "book chapter",
    "db": "book",
    "dr": "report",
    "dra": "report chapter",
    "do": "other contribution",
    "dcp": "conference paper",
    "dpa": "patent",
}


# ---------------------------------------------------------------------------
# Harvest
# ---------------------------------------------------------------------------


def page_path(set_name: str, index: int) -> str:
    safe = set_name.replace(":", "_")
    return os.path.join(PURE_RAW, safe, f"page_{index:04d}.xml.gz")


def resumption_token(xml_text: str) -> tuple[str | None, int | None]:
    m = re.search(
        r"<resumptionToken[^>]*>([^<]*)</resumptionToken>", xml_text
    )
    size = re.search(r'completeListSize="(\d+)"', xml_text)
    total = int(size.group(1)) if size else None
    if not m or not m.group(1).strip():
        return None, total
    return html.unescape(m.group(1).strip()), total


def harvest_set(set_name: str, min_interval: float) -> dict:
    """Walk one OAI set, scrubbing and caching every page. Resumable."""
    stats = {
        "set": set_name,
        "pages": 0,
        "pages_from_cache": 0,
        "records": 0,
        "complete_list_size": None,
        "scrub": collections.Counter(),
    }
    index = 0
    token = None
    while True:
        path = page_path(set_name, index)
        if os.path.exists(path):
            text = read_gz(path)
            stats["pages_from_cache"] += 1
        else:
            if token is None:
                url = (
                    f"{OAI_BASE}?verb=ListRecords&metadataPrefix=ddf-mxd"
                    f"&set={set_name}"
                )
            else:
                from urllib.parse import quote

                url = (
                    f"{OAI_BASE}?verb=ListRecords"
                    f"&resumptionToken={quote(token, safe='')}"
                )
            raw = polite_get(
                url, host_key="pure.au.dk", min_interval=min_interval,
                accept="text/xml",
            ).decode("utf-8")
            err = re.search(r'<error[^>]*code="([^"]+)"[^>]*>([^<]*)</error>', raw)
            if err:
                code = err.group(1)
                if code == "noRecordsMatch":
                    log(f"  {set_name}: no records")
                    break
                # Anything else, and in particular badResumptionToken when a
                # token from an earlier run has expired, must stop the harvest
                # loudly. Writing the error page to the cache would give it zero
                # records and no resumption token, the loop would end normally,
                # and the year would silently come back short with nothing in
                # the output to say so.
                raise SystemExit(
                    f"OAI error on {set_name} page {index}: {code} "
                    f"{err.group(2).strip()}. Delete "
                    f"{os.path.dirname(path)} and harvest that set again."
                )
            text, counts = scrub_pure_xml(raw)
            for k, v in counts.items():
                stats["scrub"][k] += v
            # Verify with different code than the code that did the removing.
            left = audit_scrub(text)
            if any(left.values()):
                raise SystemExit(
                    f"scrub failed on {set_name} page {index}: {left}"
                )
            write_gz(path, text)

        stats["pages"] += 1
        stats["records"] += text.count("<record>")
        token, total = resumption_token(text)
        if total and stats["complete_list_size"] is None:
            stats["complete_list_size"] = total
        if stats["pages"] % 25 == 0 or token is None:
            log(
                f"  {set_name}: page {stats['pages']}, "
                f"{stats['records']} of {stats['complete_list_size']} records"
            )
        if token is None:
            break
        index += 1
    stats["scrub"] = dict(stats["scrub"])
    # OAI reports the size of the full result set on every page, so the harvest
    # can check its own completeness instead of assuming that reaching the end
    # of the token chain means it got everything.
    expected = stats["complete_list_size"]
    stats["complete"] = expected is None or stats["records"] >= expected
    if not stats["complete"]:
        log(
            f"  WARNING {set_name} harvested {stats['records']} of {expected} "
            f"records. Delete data/pure-raw/{set_name.replace(':', '_')} and "
            f"run this set again."
        )
    return stats


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


def text_of(el, path: str) -> str | None:
    found = el.find(path, NS)
    if found is None or found.text is None:
        return None
    return " ".join(found.text.split()) or None


def parse_record(rec) -> dict | None:
    """Turn one OAI record into a flat row, or None if it is not Natural Sciences.

    A record is kept when at least one author affiliation sits under level2
    "Natural Sciences". Records are routinely co-authored across faculties, so a
    record can also carry departments outside the faculty. Those are recorded
    separately rather than dropped, because "this paper also involves Technical
    Sciences" is useful context for an Action, and silently discarding it would
    overstate how self-contained a department is.
    """
    doc = rec.find("oai:metadata/mxd:ddf_doc", NS)
    if doc is None:
        return None

    natsci_units: list[tuple[str, str | None]] = []
    other_faculties: set[str] = set()
    for org in doc.findall("mxd:organisation", NS):
        # The record carries the same unit twice, once xml:lang="da" and once
        # xml:lang="en". Read the English one so department names are stable.
        en = None
        for name in org.findall("mxd:name", NS):
            if name.get("{http://www.w3.org/XML/1998/namespace}lang") == "en":
                en = name
                break
        if en is None:
            continue
        level2 = text_of(en, "mxd:level2")
        level3 = text_of(en, "mxd:level3")
        level4 = text_of(en, "mxd:level4")
        if level2 == FACULTY:
            if level3:
                natsci_units.append((level3, level4))
        elif level2:
            other_faculties.add(level2)

    if not natsci_units:
        return None

    doi = None
    for el in doc.iter("{%s}doi" % NS["mxd"]):
        doi = normalise_doi(el.text)
        if doi:
            break

    title = text_of(doc, "mxd:title/mxd:original/mxd:main")
    if not title:
        title = text_of(doc, "mxd:title/mxd:translated/mxd:main")

    journal = None
    in_journal = doc.find("mxd:publication/mxd:in_journal", NS)
    if in_journal is not None:
        journal = text_of(in_journal, "mxd:title")

    keywords = []
    for kw in doc.iter("{%s}keyword" % NS["mxd"]):
        for sub in kw.iter():
            if sub.text and sub.text.strip() and sub is not kw:
                keywords.append(" ".join(sub.text.split()))
        if kw.text and kw.text.strip():
            keywords.append(" ".join(kw.text.split()))

    research_area = None
    ra = doc.find("mxd:description/mxd:research_area", NS)
    if ra is not None:
        research_area = (ra.text or "").strip() or None

    doc_type = doc.get("doc_type")
    year = doc.get("doc_year")
    try:
        year_i = int(year) if year else None
    except ValueError:
        year_i = None

    header_id = rec.find("oai:header/oai:identifier", NS)
    rec_id = doc.get("rec_id") or (header_id.text if header_id is not None else None)

    departments = sorted({d for d, _ in natsci_units})
    sections = sorted({s for _, s in natsci_units if s})

    return {
        "rec_id": rec_id,
        "pub_year": year_i,
        "doc_type": doc_type,
        "doc_type_label": DOC_TYPES.get(doc_type or "", doc_type or ""),
        "doi": doi,
        "title": title,
        "journal": journal,
        "n_authors": doc.get("total_authors"),
        "research_area": research_area,
        "n_natsci_units": len(natsci_units),
        "departments": "|".join(departments),
        "sections": "|".join(sections),
        "other_faculties": "|".join(sorted(other_faculties)),
        "keywords": "|".join(sorted(set(keywords))[:25]),
    }


def parse_all() -> dict:
    works: dict[str, dict] = {}
    affil_rows: list[dict] = []
    seen_records = 0
    faculty_counter: collections.Counter = collections.Counter()
    # Census of every record in the cache by its publication year, counted
    # before any faculty filter, any DOI requirement and any join. This is the
    # number to look at first when a year looks thin downstream: if the year is
    # present here, the harvest is fine and the thinness was introduced later.
    raw_year_counter: collections.Counter = collections.Counter()
    raw_records_per_set: collections.Counter = collections.Counter()
    natsci_year_counter: collections.Counter = collections.Counter()
    natsci_with_doi_year: collections.Counter = collections.Counter()

    for set_dir in sorted(os.listdir(PURE_RAW)):
        full = os.path.join(PURE_RAW, set_dir)
        if not os.path.isdir(full):
            continue
        for fname in sorted(os.listdir(full)):
            if not fname.endswith(".xml.gz"):
                continue
            text = read_gz(os.path.join(full, fname))
            try:
                root = ET.fromstring(text)
            except ET.ParseError as exc:
                log(f"  parse error in {set_dir}/{fname}: {exc}")
                continue
            for rec in root.iter("{%s}record" % NS["oai"]):
                seen_records += 1
                raw_records_per_set[set_dir] += 1
                doc = rec.find("oai:metadata/mxd:ddf_doc", NS)
                if doc is not None:
                    raw_year_counter[doc.get("doc_year") or "none"] += 1
                    for org in doc.findall("mxd:organisation", NS):
                        for name in org.findall("mxd:name", NS):
                            lang = name.get(
                                "{http://www.w3.org/XML/1998/namespace}lang"
                            )
                            if lang == "en":
                                lv2 = text_of(name, "mxd:level2")
                                if lv2:
                                    faculty_counter[lv2] += 1
                row = parse_record(rec)
                if row is None:
                    continue
                # The same work appears in more than one year set when Pure
                # reassigns a submission year, so key on rec_id.
                if row["rec_id"] in works:
                    continue
                works[row["rec_id"]] = row
                y = str(row["pub_year"]) if row["pub_year"] else "none"
                natsci_year_counter[y] += 1
                if row["doi"]:
                    natsci_with_doi_year[y] += 1
                for dept in row["departments"].split("|"):
                    if dept:
                        affil_rows.append(
                            {
                                "rec_id": row["rec_id"],
                                "pub_year": row["pub_year"],
                                "department": dept,
                                "doi": row["doi"] or "",
                            }
                        )

    works_path = os.path.join(DERIVED, "pure_natsci_works.csv")
    fields = list(next(iter(works.values())).keys())
    with open(works_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for row in works.values():
            w.writerow(row)
    log(f"wrote {works_path} ({len(works)} works)")

    affil_path = os.path.join(DERIVED, "pure_natsci_affiliations.csv")
    with open(affil_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(
            fh, fieldnames=["rec_id", "pub_year", "department", "doi"]
        )
        w.writeheader()
        w.writerows(affil_rows)
    log(f"wrote {affil_path} ({len(affil_rows)} rows)")

    with_doi = sum(1 for r in works.values() if r["doi"])
    by_year = collections.Counter(
        r["pub_year"] for r in works.values() if r["pub_year"]
    )
    by_dept = collections.Counter(r["department"] for r in affil_rows)
    by_type = collections.Counter(
        r["doc_type_label"] or "unlabelled" for r in works.values()
    )

    coverage = {
        "records_seen_in_cache": seen_records,
        "harvest_census": {
            "what_this_is": (
                "every record in the raw cache counted by its publication year, "
                "before any faculty filter, DOI requirement or join. Read this "
                "first when a year looks thin further down the pipeline"
            ),
            "all_au_records_by_publication_year": dict(
                sorted(raw_year_counter.items())
            ),
            "all_au_records_by_harvested_set": dict(
                sorted(raw_records_per_set.items())
            ),
            "natural_sciences_works_by_publication_year": dict(
                sorted(natsci_year_counter.items())
            ),
            "natural_sciences_works_with_doi_by_publication_year": dict(
                sorted(natsci_with_doi_year.items())
            ),
        },
        "natural_sciences_works": len(works),
        "natural_sciences_works_with_doi": with_doi,
        "doi_share_pct": round(100.0 * with_doi / len(works), 1) if works else 0.0,
        "works_by_year": dict(sorted(by_year.items())),
        "works_by_department": dict(by_dept.most_common()),
        "works_by_doc_type": dict(by_type.most_common()),
        "faculty_mentions_in_cache": dict(faculty_counter.most_common()),
        "department_affiliation_rows": len(affil_rows),
    }
    write_json(os.path.join(DERIVED, "pure_coverage.json"), coverage)
    return coverage


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", nargs="*", type=int,
                    default=[2022, 2023, 2024, 2025, 2026])
    ap.add_argument("--min-interval", type=float, default=1.2,
                    help="seconds between requests to pure.au.dk")
    ap.add_argument("--parse-only", action="store_true")
    args = ap.parse_args()

    if not args.parse_only:
        all_stats = []
        for year in args.years:
            set_name = f"publications:year{year}"
            log(f"harvesting {set_name}")
            all_stats.append(harvest_set(set_name, args.min_interval))
        write_json(
            os.path.join(DERIVED, "pure_harvest_stats.json"),
            {
                "endpoint": OAI_BASE,
                "metadata_prefix": "ddf-mxd",
                "sets": all_stats,
                "scrub_totals": dict(
                    sum(
                        (collections.Counter(s["scrub"]) for s in all_stats),
                        collections.Counter(),
                    )
                ),
            },
        )

    log("parsing cache")
    cov = parse_all()
    log(
        f"Natural Sciences works {cov['natural_sciences_works']}, "
        f"with DOI {cov['natural_sciences_works_with_doi']} "
        f"({cov['doi_share_pct']}%)"
    )


if __name__ == "__main__":
    main()
