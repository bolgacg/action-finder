"""Shared helpers for the Action finder study scripts.

Everything the page can show has to come out of a script in this folder, so the
politeness rules, the cache layout and the scrubbing rules live in one place and
every script imports them rather than re-inventing them.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
CORDIS = os.path.join(DATA, "cordis-he")
PURE_RAW = os.path.join(DATA, "pure-raw")
OPENALEX_RAW = os.path.join(DATA, "openalex-raw")
DERIVED = os.path.join(DATA, "derived")

for _d in (DATA, PURE_RAW, OPENALEX_RAW, DERIVED):
    os.makedirs(_d, exist_ok=True)


# ---------------------------------------------------------------------------
# Politeness
# ---------------------------------------------------------------------------

# A real contact address in the User-Agent is what lets an operator mail us
# instead of blocking us. OpenAlex also routes a request with a mailto into its
# faster pool, so the same string does double duty.
CONTACT = os.environ.get("ACTION_FINDER_CONTACT", "bolgacg1@gmail.com")
USER_AGENT = (
    "AU-ActionFinder-Study/0.1 "
    "(non-commercial work sample for AU Science Bridge; "
    f"mailto:{CONTACT})"
)

_last_request_at: dict[str, float] = {}


def polite_get(
    url: str,
    *,
    host_key: str,
    min_interval: float = 1.0,
    timeout: int = 120,
    max_tries: int = 5,
    accept: str = "*/*",
    max_wait: float = 120.0,
) -> bytes:
    """GET a URL with per-host spacing, retries and Retry-After handling.

    Spacing is per host_key so that a slow Pure harvest does not also throttle
    OpenAlex. Backoff is exponential and a 429 or 503 Retry-After header wins
    over our own guess, because the server knows better than we do.
    """
    delay = 2.0
    for attempt in range(1, max_tries + 1):
        gap = time.time() - _last_request_at.get(host_key, 0.0)
        if gap < min_interval:
            time.sleep(min_interval - gap)
        req = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": accept}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                _last_request_at[host_key] = time.time()
                return resp.read()
        except urllib.error.HTTPError as exc:
            _last_request_at[host_key] = time.time()
            # 404 and 400 will not get better by asking again.
            if exc.code in (400, 404):
                raise
            wait = delay
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            if retry_after and retry_after.strip().isdigit():
                wait = float(retry_after.strip())
            # Honour Retry-After, but not past the point where waiting is the
            # wrong answer. OpenAlex answers a rate limited address with a
            # Retry-After of about five hours, and a script that obeys that
            # literally looks identical to a hung script and blocks everything
            # behind it. Past the cap the error is raised so the caller can
            # decide, which for a resumable cache means stop now and resume
            # later rather than sleep through the afternoon.
            if wait > max_wait:
                log(
                    f"  HTTP {exc.code} with Retry-After {wait:.0f}s, longer "
                    f"than the {max_wait:.0f}s cap. Not waiting."
                )
                raise
            if attempt == max_tries:
                raise
            log(f"  HTTP {exc.code} on try {attempt}, waiting {wait:.0f}s")
            time.sleep(wait)
            delay = min(delay * 2, 120)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            _last_request_at[host_key] = time.time()
            if attempt == max_tries:
                raise
            log(f"  {type(exc).__name__} on try {attempt}, waiting {delay:.0f}s")
            time.sleep(delay)
            delay = min(delay * 2, 120)
    raise RuntimeError("unreachable")


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Scrubbing personal data, applied before anything touches the disk
# ---------------------------------------------------------------------------

# WHY THIS EXISTS.
#
# AU Pure's OAI feed ships staff contact data inside the bibliographic record:
# an <mxd:email> element with the institutional address, an <mxd:address>
# element with the office address, an <mxd:id id_type="loc_per"> element which
# is the employee's identifier in AU's own systems, and an <mxd:uri> pointing at
# that person's staff profile, which embeds the same identifier again.
#
# None of it is needed here. This tool proposes conversations between a
# DEPARTMENT and an organisation, so the finest grain it ever reports is
# level3 / level4 of the org hierarchy. Harvesting contact details we have no
# use for would mean holding a staff directory on disk for no reason, and it
# would put a re-identifiable personal dataset one careless join away from a
# published page.
#
# So the scrub runs at harvest time, before the response is written to the
# cache, not at analysis time. That way the cached bytes on disk cannot contain
# what we promised not to keep, and no later script can reach for it even by
# accident.
#
# ORCID goes too. It is a public identifier that the researcher publishes
# themselves, so this is not a privacy necessity. It is removed because it is
# the one remaining key that would make a person-level ranking easy to build,
# and the brief for this tool is that no person-level ranking should exist.
#
# Author names are kept in the raw cache. A name on a paper is the published
# byline, it is the bibliographic record itself, and dropping it would make the
# cache a worse copy of the source. No derived table carries names forward.

_RE_PERSON_BLOCK = re.compile(r"<mxd:person\b.*?</mxd:person>", re.DOTALL)
_RE_EMAIL_EL = re.compile(r"<mxd:email\b[^>]*>.*?</mxd:email>", re.DOTALL)
_RE_ADDRESS_EL = re.compile(r"<mxd:address\b[^>]*>.*?</mxd:address>", re.DOTALL)
_RE_LOCPER_EL = re.compile(
    r'<mxd:id\b[^>]*id_type="loc_per"[^>]*>.*?</mxd:id>', re.DOTALL
)
_RE_ORCID_EL = re.compile(
    r'<mxd:id\b[^>]*id_type="orcid"[^>]*>.*?</mxd:id>', re.DOTALL
)
_RE_URI_EL = re.compile(r"<mxd:uri\b[^>]*>.*?</mxd:uri>", re.DOTALL)
# Catch-all for an address that turns up in free text such as an abstract or a
# note field, where there is no element to key on.
_RE_BARE_EMAIL = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"
)
# Pure person profile links carry the staff identifier in the path.
_RE_PERSON_URL = re.compile(
    r"https?://[^\s<>\"]*?/persons/[0-9a-fA-F\-]{8,}", re.IGNORECASE
)

SCRUB_MARK = "[removed-at-harvest]"


def scrub_pure_xml(xml_text: str) -> tuple[str, dict[str, int]]:
    """Remove staff contact data and person identifiers from an OAI response.

    Returns the cleaned text and a count per rule, so the harvest log can state
    how much was actually removed instead of asserting that the scrub ran.
    """
    counts = {
        "email_element": 0,
        "address_element": 0,
        "loc_per_id": 0,
        "orcid_id": 0,
        "person_profile_uri": 0,
        "bare_email_in_text": 0,
        "person_profile_url_in_text": 0,
    }

    def clean_person(match: re.Match) -> str:
        block = match.group(0)
        block, n = _RE_EMAIL_EL.subn("", block)
        counts["email_element"] += n
        block, n = _RE_ADDRESS_EL.subn("", block)
        counts["address_element"] += n
        block, n = _RE_LOCPER_EL.subn("", block)
        counts["loc_per_id"] += n
        block, n = _RE_ORCID_EL.subn("", block)
        counts["orcid_id"] += n
        # <mxd:uri> inside a person is the staff profile. The identically named
        # element inside <mxd:organisation> is a department home page and is
        # kept, which is why this only runs within the person block.
        block, n = _RE_URI_EL.subn("", block)
        counts["person_profile_uri"] += n
        return block

    cleaned = _RE_PERSON_BLOCK.sub(clean_person, xml_text)

    # Anything that escaped the element-level rules, anywhere in the document.
    cleaned, n = _RE_LOCPER_EL.subn("", cleaned)
    counts["loc_per_id"] += n
    cleaned, n = _RE_ORCID_EL.subn("", cleaned)
    counts["orcid_id"] += n
    cleaned, n = _RE_EMAIL_EL.subn("", cleaned)
    counts["email_element"] += n
    cleaned, n = _RE_ADDRESS_EL.subn("", cleaned)
    counts["address_element"] += n
    cleaned, n = _RE_PERSON_URL.subn(SCRUB_MARK, cleaned)
    counts["person_profile_url_in_text"] += n
    cleaned, n = _RE_BARE_EMAIL.subn(SCRUB_MARK, cleaned)
    counts["bare_email_in_text"] += n

    return cleaned, counts


def audit_scrub(xml_text: str) -> dict[str, int]:
    """Count personal data still present. Every value must be zero after a scrub.

    Kept separate from scrub_pure_xml so the harvest can verify its own output
    with a different piece of code than the one that produced it.
    """
    return {
        "email_element": len(_RE_EMAIL_EL.findall(xml_text)),
        "address_element": len(_RE_ADDRESS_EL.findall(xml_text)),
        "loc_per_id": len(_RE_LOCPER_EL.findall(xml_text)),
        "orcid_id": len(_RE_ORCID_EL.findall(xml_text)),
        "bare_email": len(_RE_BARE_EMAIL.findall(xml_text)),
        "person_profile_url": len(_RE_PERSON_URL.findall(xml_text)),
    }


# ---------------------------------------------------------------------------
# Small IO helpers
# ---------------------------------------------------------------------------


def write_gz(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def read_gz(path: str) -> str:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return fh.read()


def write_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2, sort_keys=False)
    os.replace(tmp, path)
    log(f"wrote {path} ({os.path.getsize(path) / 1024:.0f} kB)")


def read_json(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_cordis_projects() -> tuple["object", dict]:
    """Read project.csv tolerantly and report how many rows are malformed.

    CORDIS writes the free-text `objective` field with unescaped quote
    characters. When the text itself begins and ends with a quote, CORDIS emits
    two quote characters on each side where correct CSV needs three, so the
    field never closes and the row runs long. pandas' C parser refuses the file
    outright.

    The damage is confined: `objective` is column index 15, so every column
    before it is still correctly positioned on a long row. This reader takes the
    nine columns that sit ahead of `objective`, which are exactly the ones this
    study uses, and counts the malformed rows rather than dropping them or
    pretending the file is clean.
    """
    import csv as _csv

    import pandas as pd

    _csv.field_size_limit(10 ** 9)
    path = os.path.join(CORDIS, "project.csv")
    keep = [
        "id", "acronym", "status", "title", "startDate", "endDate",
        "totalCost", "ecMaxContribution", "topics",
    ]
    rows = []
    n_total = 0
    n_long = 0
    n_short = 0
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = _csv.reader(fh, delimiter=";", quotechar='"')
        header = next(reader)
        idx = [header.index(c) for c in keep]
        objective_at = header.index("objective")
        for row in reader:
            n_total += 1
            if len(row) > len(header):
                n_long += 1
            elif len(row) < len(header):
                n_short += 1
                # A short row may not even reach the columns we want.
                if len(row) <= max(idx):
                    continue
            rows.append([row[i] for i in idx])
    df = pd.DataFrame(rows, columns=keep)
    stats = {
        "project_rows_read": n_total,
        "rows_well_formed": n_total - n_long - n_short,
        "rows_running_long_from_unescaped_quotes": n_long,
        "rows_running_short": n_short,
        "rows_usable_for_this_study": len(df),
        "why_usable": (
            "the corruption is in the free-text objective column at index "
            f"{objective_at}; every column this study reads sits before it and "
            "is still correctly positioned on a long row"
        ),
    }
    return df, stats


def normalise_doi(raw: str | None) -> str | None:
    """Reduce a DOI to the bare lowercase 10.x form used as a join key."""
    if not raw:
        return None
    doi = raw.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/",
                   "http://dx.doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix):]
    doi = doi.strip().rstrip(".")
    if not doi.startswith("10.") or "/" not in doi:
        return None
    return doi
