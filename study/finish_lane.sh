#!/usr/bin/env bash
#
# Complete the Action finder lane once the OpenAlex daily budget has reset.
#
# OpenAlex meters its API against a daily spend and this address had used its
# free allowance, so the lookup stopped at 2,025 of 7,329 DOIs. The allowance
# resets at 00:00 UTC. This script finishes the lookup and rebuilds everything
# that depends on it.
#
# Safe to schedule unattended:
#   every step is idempotent, so a repeat run cannot corrupt what is already there
#   a lock stops two runs overlapping
#   all output goes to the log
#   it exits non-zero if any step fails OR if the lookup is still incomplete,
#     so a scheduler can simply try again
#
# It does NOT publish anything. No git commit, no push, no outward-facing action.
#
#   bash /home/bolgac/projects/action-finder/study/finish_lane.sh

set -Eeuo pipefail

ROOT=/home/bolgac/projects/action-finder
LOG="$ROOT/logs/finish_lane.log"
LOCK="$ROOT/logs/finish_lane.lock"

mkdir -p "$ROOT/logs"
exec >>"$LOG" 2>&1

say() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

fail() {
  local line=$1
  say "FAILED at line $line. A step exited non-zero; see above for its output."
  exit 1
}
trap 'fail $LINENO' ERR

# One run at a time. Two concurrent runs would race on the derived CSVs.
exec 9>"$LOCK"
if ! flock -n 9; then
  say "another run holds the lock, exiting"
  exit 4
fi

say "===== finish_lane starting ====="

# The budget resets at 00:00 UTC. Asking before then burns a request and gets the
# same refusal, so this is an absolute instant, not an hour of the day. An
# hour-of-day test was the first attempt and it was wrong in the obvious way:
# 19:12 UTC is numerically past 00:05, so it let the run through nine hours
# early. Change NOT_BEFORE if the lane is ever rescheduled.
NOT_BEFORE="2026-09-15T00:05:00Z"
NOT_BEFORE_EPOCH=$(date -u -d "$NOT_BEFORE" +%s)
NOW_EPOCH=$(date -u +%s)
if [ "$NOW_EPOCH" -lt "$NOT_BEFORE_EPOCH" ]; then
  say "it is $(date -u +%Y-%m-%dT%H:%M:%SZ), before the $NOT_BEFORE guard."
  say "The OpenAlex budget has not reset yet. Not touching it. Exiting 5."
  exit 5
fi

cd "$ROOT"

# The order matters, and two of these steps are easy to leave out.
#
# spotcheck.py reads the finished actions.json and the institutions table, so it
# has to run AFTER rank.py; and rank.py folds its result into the honesty panel,
# so rank.py has to run again AFTER it. Skip that and the panel publishes
# falsification numbers describing a ranking that no longer exists.
#
# stability.py bootstraps the published candidates, so it also runs after the
# final rank.py. build_page_data.py refuses to inline a stability file that does
# not match the current ranking, so skipping it degrades safely rather than
# silently, but skipping it does lose the confidence bands.
say "step 1 of 7: openalex lookup"
python3 -u study/openalex.py

say "step 2 of 7: cordis partners and the topic bridge"
python3 -u study/partners.py

say "step 3 of 7: rank"
python3 -u study/rank.py

say "step 4 of 7: falsification spot-check against co-authorship"
python3 -u study/spotcheck.py

say "step 5 of 7: rank again, folding the spot-check into the honesty panel"
python3 -u study/rank.py

say "step 6 of 7: bootstrap the ranking stability"
python3 -u study/stability.py

say "step 7 of 7: page data"
python3 -u study/build_page_data.py

# The gate. openalex.py exits 0 when it stops early on purpose, because stopping
# cleanly is correct behaviour, not an error. So completeness is checked here
# instead, and a still-incomplete lookup exits non-zero so the schedule retries.
# The verification may exit 3 without tripping the ERR trap, because "the lookup
# is still short" is a retryable outcome and not the same thing as a step
# crashing. Flattening the two into exit 1 hid that distinction.
say "verifying coverage"
set +e
python3 - <<'PY'
import json, sys
c = json.load(open("data/derived/openalex_coverage.json"))
print(
    f"  match rate {c['openalex_match_rate_pct']} percent, "
    f"{c['openalex_matched']} of {c['pure_works_with_doi']} DOIs, "
    f"{c['dois_never_asked']} never asked, "
    f"{c['dois_confirmed_absent_from_openalex']} confirmed absent"
)
for year, v in c.get("coverage_by_publication_year", {}).items():
    print(f"    {year}: {v['covered_by_openalex']}/{v['natural_sciences_dois']} "
          f"({v['coverage_pct']}%)")
if not c["lookup_complete"]:
    print("  LOOKUP STILL INCOMPLETE, run this again after the next reset")
    sys.exit(3)
print("  lookup complete")
PY
VERIFY=$?
set -e

if [ "$VERIFY" -eq 3 ]; then
  say "rebuild succeeded but the lookup is still incomplete. Exiting 3 so the"
  say "schedule retries after the next reset. The data on disk is still valid,"
  say "just partial, and every file says so."
  exit 3
elif [ "$VERIFY" -ne 0 ]; then
  say "verification itself failed with $VERIFY"
  exit 1
fi

say "===== finish_lane done, lookup complete ====="
