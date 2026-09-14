#!/usr/bin/env bash
# Finish the lookup once OpenAlex will answer again, then rebuild everything downstream.
#
# Why this exists: OpenAlex moved to a paid interface during this build. The free
# daily allowance for this address ran out with 5,304 of 7,329 DOIs still unlooked,
# and it resets at midnight UTC. Nothing in the code is broken, so the job here is
# to wait for the reset rather than to retry harder. At 50 DOIs a request the whole
# remaining lookup costs about 150 requests, so it finishes in minutes once it can run.
#
# Safe to run more than once. Every step reads from cache and overwrites its own output.

set -o pipefail
cd /home/bolgac/projects/action-finder || exit 1

LOG=data/finish.log
PROBE='https://api.openalex.org/works?filter=doi:https://doi.org/10.1038/s41586-023-06004-9&select=id&mailto=bolgacg1@gmail.com'
UA='action-finder/1.0 (mailto:bolgacg1@gmail.com)'

say() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG"; }

say "waiting for the OpenAlex daily budget to reset"

# Probe every ten minutes for up to eight hours. Eight hours covers the reset with
# room to spare; past that something has changed that a longer wait will not fix.
deadline=$(( $(date +%s) + 8*3600 ))
while :; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -A "$UA" "$PROBE")
  if [ "$code" = "200" ]; then
    say "OpenAlex answering again (HTTP 200), starting the lookup"
    break
  fi
  if [ "$(date +%s)" -ge "$deadline" ]; then
    say "gave up after eight hours, last response was HTTP $code"
    exit 1
  fi
  say "still HTTP $code, sleeping ten minutes"
  sleep 600
done

run() {
  say "running: $*"
  if ! "$@" >>"$LOG" 2>&1; then
    say "FAILED: $*"
    exit 1
  fi
}

run python3 study/openalex.py
run python3 study/partners.py

# rank, spotcheck, rank again. The spot-check reads the finished actions.json, and
# rank.py folds the spot-check back into the honesty panel, so a single pass would
# publish falsification numbers describing the previous ranking.
run python3 study/rank.py
run python3 study/spotcheck.py
run python3 study/rank.py

# stability.py bootstraps the published candidates, so it has to follow rank.py every
# time. Skip it and build_page_data.py finds a stability file describing the previous
# ordering, refuses to inline it, and the page quietly loses that section overnight.
run python3 study/stability.py
run python3 study/build_page_data.py

MATCHED=$(python3 -c "import json;print(json.load(open('data/derived/openalex_coverage.json'))['openalex_match_rate_pct'])")
COMPLETE=$(python3 -c "import json;print('yes' if json.load(open('data/derived/openalex_coverage.json'))['lookup_complete'] else 'no')")
say "match rate now ${MATCHED} percent, lookup complete: ${COMPLETE}"

# Whether to publish an incomplete result. Refusing to push would leave the 27.6
# percent page live, which is worse than whatever this run reached, and the page
# states its own coverage in act three either way. So it publishes regardless and
# the script exits non-zero when the lookup did not finish, so the morning check
# sees a failure rather than a silent partial success.
if git diff --quiet -- docs/data.js data/actions.json data/derived; then
  say "no change to the published data, nothing to push"
else
  git add -A -- docs data
  git commit -q -m "Rerun the lookup once the OpenAlex allowance reset

The first build reached 27.6 percent of the Natural Sciences papers
carrying a DOI, because OpenAlex moved to a paid interface partway through
and the free daily allowance ran out. This is the same pipeline rerun on
the fuller set, now at ${MATCHED} percent, with the spot-check and the
stability bootstrap regenerated against the new ranking rather than left
describing the old one."
  if git push -q origin HEAD 2>>"$LOG"; then
    say "pushed, match rate now ${MATCHED} percent"
  else
    say "rebuild succeeded but the push failed, run git push by hand"
    exit 1
  fi
fi

if [ "$COMPLETE" != "yes" ]; then
  say "LOOKUP STILL INCOMPLETE at ${MATCHED} percent. The page is published and says so, but rerun this script."
  exit 1
fi

say "done"
