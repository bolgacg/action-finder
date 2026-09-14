# Build notes for the Action finder data pipeline

What the pipeline does, what its numbers mean, what it cannot do, and what would
change the design. Every number quoted here is written by a script in `study/`
into a file in `data/`, and nothing in this file was typed in by hand.

`data/derived/honesty.json` is the machine-readable version of everything below.

## Read this first

The OpenAlex lookup is **incomplete**. Of the 7,329 Natural Sciences DOIs, 2,025
have OpenAlex data and 5,304 do not, which is 27.6 percent coverage. Everything
downstream is computed on the covered 2,025.

The cause is not a rate limit that backing off would solve. OpenAlex now meters
its API against a daily spending allowance, and this address had spent its free
allowance. The service replies:

    {"error":"Rate limit exceeded",
     "message":"Insufficient budget. This request costs $0.0001 but you only
                have $0 remaining. Resets at midnight UTC",
     "retryAfter":17659,"dailyRemainingUsd":0}

So the fix is the clock, not the code. The allowance resets at 00:00 UTC. The
remaining 5,304 DOIs are 107 requests at 50 DOIs each, which is under two US
cents. What spent the allowance was an earlier per-DOI version of the lookup,
not the batched code that is in the repository now.

**Do not read a thin year as a thin harvest.** The Pure harvest is complete and
even. Counted straight from the raw cache before any filter or join, AU records
per publication year run 13,724 / 13,106 / 12,959 / 14,365 / 8,898 across 2022
to 2026, and Natural Sciences works run 2,002 / 1,871 / 1,925 / 1,931 / 1,185.
The 2026 figure is lower because the year is not over. All five OAI sets match
the `completeListSize` the endpoint reports for them.

The unevenness is entirely in the OpenAlex lookup, and it is severe because the
batch that succeeded was drawn from a DOI list built when only the 2022 set had
been parsed:

| publication year | Natural Sciences DOIs | covered by OpenAlex |
| --- | --- | --- |
| 2022 | 1,650 | 98.4 percent |
| 2023 | 1,518 | 8.0 percent |
| 2024 | 1,580 | 0.1 percent |
| 2025 | 1,584 | 5.1 percent |
| 2026 | 992 | 19.5 percent |

That is why a candidate can show `works_by_year` of 2022: 82, 2023: 3, 2025: 5,
2026: 13 with 2024 missing. The department did not stop publishing in 2024. The
lookup never reached those papers. Every candidate now carries
`au_evidence.openalex_coverage_for_this_department` giving that department's
DOI-carrying Pure works per year beside the number covered, so the ambiguity
cannot survive a reading of the entry. The same tables are at the top of
`actions.json` under `harvest_and_coverage_by_year`.

Nothing was faked to paper over any of this. To finish the lane once the
allowance resets:

    bash /home/bolgac/projects/action-finder/study/finish_lane.sh

It refuses to run before 00:05 UTC on 15 September 2026, takes a lock, logs to
`logs/finish_lane.log`, and exits non-zero if any step fails or if the lookup is
still short. It publishes nothing.

The numbers below are what the pipeline produced under the incomplete lookup.

## Numbers from the final run

**AU Pure.** 63,114 records harvested across publication years 2022 to 2026,
all five year sets complete against the `completeListSize` the endpoint reports.
8,920 of those are Faculty of Natural Sciences works, spread 2,002 / 1,871 /
1,925 / 1,931 / 1,185 across 2022 to 2026. 7,344 carry a DOI, which is 82.3
percent. Thirteen departments and centres appear, led by Biology at 1,876 works,
then the Interdisciplinary Nanoscience Center, Physics and Astronomy, Chemistry
and Molecular Biology and Genetics. The tail is small units such as iMAT, the
Dean's Office and Aarhus Space Centre, which never clear the thresholds.

The scrub removed, across the harvest: 128,454 employee identifiers, 132,212
staff profile links, 96,472 office addresses, 95,775 email elements, 81,027
ORCIDs, and 325 further email addresses sitting loose in free text. Re-auditing
all 633 cached pages with a different function than the one that cleaned them
returns zero on every category.

**OpenAlex.** 2,025 of 7,329 DOIs covered, for the reason above. Of the covered
works, 184 have a co-author at an organisation OpenAlex types as a company,
which is 9.1 percent.

**CORDIS.** Aarhus University, participant 999997736, is on 439 Horizon Europe
projects. Self-joining gives 67 Danish for-profit partner rows covering 53
distinct organisations, which reproduces FACTS.md exactly. 726 distinct Danish
organisations appear in Horizon Europe overall; 610 of them share no project
with AU. `project.csv` yielded 23,451 usable rows with 193 malformed by the
quoting fault described above.

**The topic bridge.** 377 of 1,007 euroSciVoc paths map to an OpenAlex subfield,
which places 14,706 of 20,161 CORDIS projects on the shared topic map. That is
lower than it was, deliberately, and the next section says why.

**The ranked list.** 25 department by topic pairs clear the thresholds of at
least 5 department papers and at least 3 Danish organisations on the topic. All
25 are written to `data/actions.json`, covering 8 departments, 13 of them
flagged as white space.

## What the hand check found, and what it changed

Twenty assignments were sampled with a fixed seed and read one at a time. The
sample and the verdicts are frozen in `study/topic_check_sample_checked.json`
and `study/topic_check_verdicts.json`, each verdict with its reasoning.

Ten right, four partly right, six wrong. A 30 percent wrong rate.

The ten paper to subfield rows, which are OpenAlex's work, came out six right,
two partly right, two wrong. Both failures are worth naming. One is an ordinary
misfire: a paper titled only "Computational Chemistry" was given a mass
spectrometry topic and so landed in Spectroscopy. The other is not a fault of
this pipeline at all. A paper on solar variability from radiocarbon records was
given the topic "Geomagnetism and Paleomagnetism Studies", which is fair, and
that topic sits in OpenAlex's own hierarchy under the subfield **Molecular
Biology**, field Biochemistry Genetics and Molecular Biology. Checked against
the cached OpenAlex topic list, so it is upstream. "Diatoms and Algae Research"
is filed under Biomaterials in the same way. Any tool that uses OpenAlex
subfields as its topic unit inherits these.

The ten euroSciVoc term to subfield rows, which are this project's work, split
along one line so cleanly that it changed the code:

| matching route | right | partly | wrong |
| --- | --- | --- | --- |
| term matched an OpenAlex subfield name | 4 | 1 | 0 |
| term matched an OpenAlex topic keyword | 0 | 1 | 4 |

The keyword route matches word forms rather than meanings. "Atmospheric
turbulence" is a keyword on free-space optics topics, so a meteorology term was
filed under Atomic and Molecular Physics and Optics. "Cryptography" was filed
under Artificial Intelligence. "Coal" was filed under Mechanical Engineering.
All three were exact leaf matches, so climbing the euroSciVoc path is not what
made them unreliable. The route is.

So the keyword route is now off by default in `study/partners.py`. The cost is
real and is the reason the bridge numbers above are lower than they could be:
mapped paths fall from 632 to 377, CORDIS projects placed fall from 17,517 to
14,706, which is 86.9 percent down to 72.9 percent, and candidates fall from 53
to 25. Fewer Actions that mean what they say is the better trade for a tool
whose output is meant to start a conversation with a named company.
`--with-keyword-matching` restores the older, wider, less reliable behaviour.

The accuracy figures are measured against the frozen sample, not against a
sample redrawn after the change. Redrawing would score today's rows with
yesterday's verdicts, and the point of the check was precisely to remove the
route those verdicts condemned.

## How many top candidates are already collaborating

Computed exactly, not estimated, because the CORDIS side is a hard identifier
join.

Of the 25 candidates, **18 have at least one Danish organisation that already
shares a Horizon Europe project with AU on that same topic**, which is 72
percent. Widening to a shared project on any topic, it is 22 of 25, or 88
percent. And 12 of the 25 are in a topic where the department already has a
company co-author on one of its own papers.

That is the most uncomfortable number in this project and it should stay
visible. A candidate is a department and a topic, and it lists many
organisations, so "already collaborating" here means some organisation on the
list is already a partner, not that the whole candidate is spent. But it does
mean a reader who takes "AU and Danish industry have not met here" at face value
would be wrong most of the time. The per-organisation flags are the ones to
trust, and each organisation carries its own
`shares_a_project_with_au_on_this_topic` and `shares_any_project_with_au`.

## Trying to disprove the tool's own claims

`study/spotcheck.py` tests the not-yet-connected claims against something CORDIS
cannot see: whether the department already co-authors papers with that company.

Of 214 organisation-level not-yet-connected claims in the ranked list, 17 are
contradicted by co-authorship, which is 7.9 percent. Those 17 reduce to 6
distinct name pairs. Reading them by hand, 5 are genuine and 1 is spurious, so
the name matching runs at about 83 percent precision. The genuine ones are COWI,
Novo Nordisk, Topsoe, Ørsted and Novozymes, all of which co-author with AU
Natural Sciences while sharing no Horizon Europe project on that topic. The
spurious one matched "Knowledge Hub Zealand" to "Knowledge Centre for
Agriculture" on the word "knowledge". Verdicts are in
`study/spotcheck_verdicts.json`.

Name matching is used here and nowhere else in the project, deliberately,
because it is sound in one direction only. A hit disproves "they have never
worked together", which is the claim under test. A miss proves nothing, because
the name may simply not have resolved. Distinctiveness is decided from the data,
by counting how many of the 748 Danish organisation names each word appears in,
rather than from a stopword list written by hand. That rule has a floor:
"knowledge" appears in exactly two names, the same as "cowi" and "unisense", so
no frequency threshold separates the false match from the true ones. Reading
them is what settles it, which is why the readings are recorded.

An OpenAlex API version of the same check exists behind `--with-api`. It was
written first and is the weaker of the two: the institution search endpoint
throttles hard, and three separate problems have to be solved before a Danish
company name resolves at all. CORDIS stores "ORSTED WIND POWER A/S" where
OpenAlex stores "Ørsted (Denmark)"; OpenAlex search does not fold Danish
characters, so "Ørsted" matches and "orsted" returns nothing; and a longer query
is not a better query, since "Nokia" returns seventeen institutions and "Nokia
Bell Labs" returns none. Combining `country_code:DK` with `search` returns zero
for every query tested, so the country filter is applied in Python instead.

## The pipeline

Four steps, each cacheable and each rerunnable on its own.

    study/pure_harvest.py   AU Pure over OAI-PMH, department and faculty, DOIs
    study/openalex.py       those DOIs in OpenAlex, topics and co-author types
    study/partners.py       CORDIS Danish organisations, topic bridge, AU join
    study/rank.py           data/actions.json plus data/derived/honesty.json
    study/spotcheck.py      tries to disprove the not-yet-connected claims

`study/common.py` holds the politeness rules, the cache layout and the scrub.

Run order matters: `pure_harvest` then `openalex` then `partners` then `rank`,
then `spotcheck`, then `rank` again so the spot-check result lands in the
honesty panel.

## Why AU Pure and not something easier

FACTS.md had already established that OpenAlex cannot say which AU faculty a
paper belongs to, and that Pure's OAI-PMH endpoint can. That single fact decides
the architecture. The whole tool is about a specific faculty, so a source that
cannot see faculties is not a substitute no matter how much easier it is to
query. OpenAlex is still here, because Pure cannot say what a paper is about in a
vocabulary shared with the rest of the world, and CORDIS is here because neither
of them knows which Danish companies are working on what.

Three things found while building that were not in FACTS.md:

**The OAI date filter is not a publication date filter.** `from` and `until`
select on the record's modification datestamp. A four day window returned a
batch of 1998 and 1999 records that Pure had just re-indexed. The
`publications:yearYYYY` sets select on publication year, which is what a claim
about recent output actually needs, so the harvest walks those instead.

**The feed ships staff contact data.** Every person element can carry
`<mxd:email>` with the institutional address, `<mxd:address>` with the office
address, an `<mxd:id id_type="loc_per">` employee identifier and an `<mxd:uri>`
staff profile link that embeds that identifier again. All four are removed
before the response is written to disk, so the cache cannot contain them, and a
separate function re-checks the cleaned text with different code than the code
that cleaned it. ORCID goes too, not for privacy but because it is the one
remaining key that would make a person-level ranking easy to build, and the
brief for this tool is that no such ranking should exist. Author names stay in
the raw cache, because a name on a paper is the published byline and dropping it
would make the cache a worse copy of the source. No derived table carries names.

**CORDIS `project.csv` is malformed.** When the free-text `objective` field
contains text that itself starts and ends with a quote, CORDIS writes two quote
characters on each side where CSV needs three. The field never closes, the row
runs long, and pandas' C parser refuses the whole file. The damage is confined to
columns after `objective` at index 15, and every column this study reads sits
before it, so `common.load_cordis_projects` reads the file with the standard
library, takes the nine columns ahead of the break and counts the malformed rows
rather than dropping them or pretending the file is clean.

## The topic bridge, which is the weakest joint

CORDIS classifies projects with euroSciVoc. OpenAlex classifies papers with its
own topic tree. Nothing links them, so the two halves of this tool cannot be
compared until something does.

The bridge is built mechanically, never by hand. A euroSciVoc term is matched to
an OpenAlex subfield name, then to an OpenAlex topic name, then to an OpenAlex
topic keyword, with a keyword accepted only when one subfield clearly dominates
the topics carrying it. If the leaf term matches nothing, the walk moves up the
euroSciVoc path and tries the parent, and the number of levels it had to climb
travels with the result so a coarse match can be told from an exact one. A term
that reaches the top of its path without matching is left unmapped and counted.

Leaf terms alone matched too little to use. Walking up the path roughly doubles
it. Every candidate Action in `actions.json` carries a `topic_bridge_quality`
block showing how the terms feeding its topic were matched, so a reader can see
which rows rest on exact matches and which rest on a climb.

This is the part of the pipeline most likely to be wrong, which is why the
hand-checked sample draws half its rows from it.

## What could not be done, and why

**No CVR, so no company universe beyond Horizon Europe.** Per FACTS.md,
`distribution.virk.dk/cvr-permanent/_search` returns 401 and access needs a
signed declaration to cvrselvbetjening@erst.dk. So the Danish side of this tool
sees only organisations that have participated in Horizon Europe. A Danish
company that has never applied to an EU programme is invisible here, however
active it is. That is the single largest coverage limit in the tool, and it
biases the output towards organisations that are already comfortable with
collaborative research funding, which is close to the opposite of the population
a knowledge-exchange office most wants to reach.

**No industry codes, so no sector claim.** Also per FACTS.md: DB25 merged
research and development in biotechnology into a generic 72.10.00 on
1 January 2025, so a sector code can no longer separate a protein-engineering
firm from a seismology consultancy. Nothing in this pipeline uses one.

**No patent citation layer.** There is no open, identifier-keyed dataset linking
European patents to the papers they cite, so no claim about patent uptake is
made anywhere.

**No person-level output, by design and by construction.** The brief asked for
department level. The scrub makes it structural rather than a matter of
discipline: the identifiers that would let anyone build a person ranking are not
in the files.

**"Not yet working together" only ever means one thing here.** It means no
shared Horizon Europe project, checked by a hard join on the CORDIS participant
identifier. Two organisations can have collaborated for a decade through
contract research, Innovation Fund Denmark, a PhD placement or a consultancy and
leave nothing at all in CORDIS. So the tool reports a floor on existing
collaboration and never a ceiling, and `study/spotcheck.py` exists to measure how
far off that floor is.

## What would change the design

In rough order of how much it would improve the output.

**Finish the OpenAlex lookup.** Everything else on this list is secondary to
the fact that the topic and co-authorship evidence currently rests on 27.6
percent of the DOIs. Rerunning `study/openalex.py` from a different address, or
after the limit clears, is the single highest-value action. Better still, use
the OpenAlex data snapshot rather than the API: it removes the rate limit as a
category of problem and makes the whole pipeline reproducible offline.

**The topic unit is wrong, and the hand check showed why.** OpenAlex subfield
was chosen because it is coarse enough to join to euroSciVoc and specific enough
to name an Action. But subfields inherit hierarchy errors that are visible to
any reader who looks, as the geomagnetism-under-Molecular-Biology case shows,
and a subfield like "Environmental Engineering" is too broad to propose a
conversation about. OpenAlex topics, of which there are 4,516, are far more
accurate and far more specific. The reason the pipeline does not use them is the
bridge: topic names almost never match euroSciVoc terms. The fix is to stop
trying to make CORDIS speak OpenAlex. Classify the CORDIS project titles and
objectives directly into OpenAlex topics using the same text the classifier was
trained on, rather than mapping one controlled vocabulary onto another. That
replaces the weakest joint in the tool with a much stronger one and would let
the Action unit drop from subfield to topic.

**"Not yet working together" needs a second source.** 72 percent of the top
candidates already have a same-topic AU partner somewhere in the list, and the
falsification check found real co-authorship that CORDIS cannot see. Horizon
Europe participation is a narrow window onto collaboration. Adding co-authorship
as a first-class signal rather than a check, and adding Innovation Fund Denmark
project data, would make the gap claim mean something closer to what a reader
assumes it means.

**The Danish partner universe is the wrong universe.** Because CVR is gated, the
only Danish organisations this tool can see are the ones already in Horizon
Europe. Those are precisely the organisations that already know how to
collaborate with universities, which is close to the opposite of the population
a knowledge-exchange office wants to reach. Getting CVR access, which needs an
email to cvrselvbetjening@erst.dk and a signed declaration, would change what
the tool is for rather than merely improving it.

**The score is a placeholder and should be treated as one.** It is a geometric
mean of scaled publication count and scaled organisation count, tilted by the
share of organisations not yet connected. It is transparent and every component
is written next to the result, which is the most that can be said for it.
Nothing in it knows whether a topic is ready for an Action, whether the
department has capacity, or whether the companies are the right size. A real
version would be calibrated against Actions that Science Bridge has already run
and judged worthwhile, and until such a list exists the ranking should be read
as a sorted shortlist and not as a prediction.

**Sections are harvested but unused.** Pure's level 4 gives the section inside a
department, which is a considerably more useful unit for finding the right group
than the department is. It is parsed into the `sections` column of
`pure_natsci_works.csv`, where 4,245 of the 8,920 works carry one, and nothing
downstream reads it. Two reasons: only about half the works have a section at
all, and the per-section paper counts get thin enough that the thresholds stop
meaning much. With the full OpenAlex coverage restored, section level would be
worth revisiting for the larger departments, and `pure_natsci_affiliations.csv`
would need a section column to support it.

## A correct bridge can still produce a wrong row

The hand-checked sample tested whether the bridge maps a euroSciVoc term to the
right OpenAlex subfield. It cannot see a different failure, where the bridge maps
the term correctly and the CORDIS tag itself was loose.

The case that exposed it: Novo Nordisk appears under Ecology because project
101166227, "REpresentative Clinical Research, ADvancing Inclusivity in Europe",
carries exactly one euroSciVoc term, "ecosystems", whose path is natural
sciences, biological sciences, ecology, ecosystems. The bridge did its job. The
project means research ecosystems and the vocabulary means ecological ones.

The obvious test, whether the project's other terms sit in a different domain,
does not catch that project, because it has no other terms. So the test used is
the more general one: a link is **corroborated** when at least one other term on
the same project sits in the same euroSciVoc domain as the term that carried the
topic. A single-term project fails automatically, which is correct, and a lone
ecology term among medical ones fails too.

Across the 1,324 organisation-by-topic links, 845 are corroborated, 353 are a
minority tag and 126 are a single tag, so **36.2 percent are weakly supported**.
Of the organisations actually listed on the page, **24.8 percent** are. "Ecology"
is the worst affected candidate at 61.1 percent, and "ecosystems" is the worst
carrying term, because it is a genuine homonym: ecological, business, innovation
and health ecosystems are all called ecosystems.

Two things this number is not. It is not a wrongness measure: Blue World
Technologies reaches Organic Chemistry through "alcohols" on a bio-methanol
project, which is uncorroborated and entirely correct. And it is a floor rather
than a measure, because corroboration is checked at the coarse domain level.
Region Hovedstaden reaches Ecology partly through a psilocybin palliative-care
trial tagged ecosystems, neurobiology, multiple sclerosis and anxiety disorders;
ecosystems and neurobiology are both natural sciences and both are still
biological sciences a level down, so no level of this test catches it.
Tightening to the next level flags 63 percent of listed organisations instead of
25 and still misses that case, so the conservative version is kept.

Weakly supported links are marked, not dropped. Dropping would hide the problem
and would also discard correct links, and the page's argument is that a
specialist does the judging.

## What I could not verify

**Whether the ranking is stable.** It is not, and the honesty panel now carries
a `ranking_stability` block saying so. Two facts drive it. First, OpenAlex
coverage varies by department from 14.3 percent for Mathematics to 33.0 percent
for the Arctic Research Centre, a 2.3 times spread, and since the AU half of the
score is a scaled paper count, departments are currently being compared on
unequal evidence for reasons that have nothing to do with their research.
Second, 13 of the 25 candidates are flagged white space on between 5 and 12
observed papers each. Projecting the observed 9.1 percent company co-authorship
rate onto the unseen papers, roughly 2 of those 13 flags would survive a
complete lookup. That projection is labelled as a projection everywhere it
appears and rests on two assumptions that are both false in known ways: that a
company co-author is equally likely on any paper, and that the covered papers
are a random sample. Treat the direction as real and the decimals as noise.

**Whether the 2,025 covered works are representative.** They are not a random
sample, they are a publication-year slice, so any statement of the form "AU
Natural Sciences co-publishes with companies at 9.1 percent" is really a
statement about 2022 output. I could not test for a time trend because there is
almost no non-2022 data to test against.

**Whether a "not yet connected" organisation is genuinely unconnected.** Only
falsifiable, never confirmable. The offline check found 17 contradicted claims
out of 214 using co-authorship, and a miss there proves nothing.

**Whether OpenAlex company typing is right.** Taken on trust. One visible oddity
survived into the output: a Physics and Astronomy candidate lists "Kjobenhavns
Telefon Aktieselskab" as a Danish company co-author, which is a defunct telecom
name. Institution typing was not audited and should not be assumed clean.

## Decisions a reader might reasonably make differently

These are judgement calls, not facts. Each is a place where someone sensible
could choose the other way, and each is a single edit.

**Excluding universities from the partner lists.** `PARTNER_ACTIVITY_TYPES` in
`rank.py` drops CORDIS activity type HES. Without it every topic was topped by
Copenhagen, DTU, Aalborg and SDU, because universities are the heaviest Horizon
Europe participants by far. Someone running a secretariat that also brokers
university-to-university work would keep them.

**Turning off the keyword route in the topic bridge.** This costs 14 percentage
points of CORDIS project coverage and halves the candidate count, on the
evidence of five hand-checked mappings. Five is a small sample to change a
default on. The split was clean, four wrong and none right against four right
and none wrong, but someone who wanted more candidates and was willing to
hand-filter them could pass `--with-keyword-matching`.

**Counting a work by its primary topic only.** A paper gets one subfield, its
strongest. OpenAlex offers up to three, and using all three would widen every
candidate and make white space much harder to claim. Primary-only is the
conservative choice for a white space flag and the restrictive one for
everything else.

**The thresholds of 5 papers and 3 organisations.** Arbitrary. They were chosen
to keep the list readable. Both are command line flags.

**The gap factor running 0.5 to 1.0 rather than 0 to 1.** A topic where AU
already has partners is still a legitimate Action, so an existing partner
reduces a candidate's score but never zeroes it. Someone hunting strictly for
untouched ground would want the harsher version.

**Scoring on the geometric mean.** It requires both halves of a candidate to be
real, so a topic strong on one side and empty on the other cannot rank. An
arithmetic mean would let either half carry a candidate, which would surface
more AU strengths that no Danish organisation is working on. That is a different
and also useful question, just not the one the tool was asked.

**Keeping author names in the raw cache.** Emails, office addresses, employee
identifiers and ORCIDs are stripped at harvest. Names are not, because a name on
a paper is the published byline. No derived table carries them. Someone with a
stricter reading of the brief would strip those too.

## Rules followed

- Every number is computed by a script in `study/` and written to `data/`.
  Nothing is typed in by hand except the recorded hand verdicts, which are
  clearly marked as judgements and carry their reasoning.
- Raw downloads are cached under `data/`. The Pure harvest is resumable and the
  OpenAlex batches are keyed by content hash, so a rerun re-fetches only what
  actually changed.
- Requests identify themselves with a contact address and are spaced per host.
- Nothing outward-facing was written, no page was built and nobody was
  contacted. FACTS.md notes that a short note to pure@au.dk is the right move
  before publishing anything from the harvest; that has not been sent and is not
  this task's to send.
