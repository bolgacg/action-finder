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
run python3 study/rank.py
# stability.py bootstraps the published candidates, so it has to follow rank.py every
# time. Skip it and build_page_data.py finds a stability file describing the previous
# ordering, refuses to inline it, and the page quietly loses that section overnight.
run python3 study/stability.py
run python3 study/build_page_data.py

# The point of the whole wait. If the lookup still did not complete, say so loudly
# rather than leaving a page that claims more coverage than it has.
python3 - <<'PY' | tee -a "$LOG"
import json
c = json.load(open('data/derived/openalex_coverage.json'))
print(f"match rate now {c['openalex_match_rate_pct']} percent, "
      f"{c['openalex_matched']} of {c['pure_works_with_doi']} DOIs matched, "
      f"{c['dois_never_asked']} never asked")
print("lookup complete" if c['lookup_complete'] else "LOOKUP STILL INCOMPLETE")
PY

# Publish the completed data. The page is already live and says openly that it was
# built on a fraction of the papers, so the honest move is to replace that state as
# soon as there is a better one rather than to leave the caveat standing.
if git diff --quiet -- docs/data.js data/actions.json data/derived; then
  say "no change to the published data, nothing to push"
else
  MATCHED=$(python3 -c "import json;print(json.load(open('data/derived/openalex_coverage.json'))['openalex_match_rate_pct'])")
  git add -A -- docs data
  git commit -q -m "Complete the OpenAlex lookup and rerank

The first build reached ${MATCHED} percent of the Natural Sciences papers
carrying a DOI, because OpenAlex moved to a paid interface partway through
and the free daily allowance ran out. This is the same pipeline rerun once
the allowance reset, with the ranking recomputed on the fuller set."
  if git push -q origin HEAD 2>>"$LOG"; then
    say "pushed the completed data, match rate now ${MATCHED} percent"
  else
    say "rebuild succeeded but the push failed, run git push by hand"
  fi
fi

say "done"
