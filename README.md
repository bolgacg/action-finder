# Which introduction has nobody made yet?

A shortlist of candidate Actions for Science Bridge, the knowledge-exchange secretariat at
Aarhus University's Faculty of Natural Sciences: a department paired with a research topic
where Aarhus publishes, Danish organisations are working, and the two have not yet met.

Live page: https://bolgacg.github.io/action-finder/

Built for the Innovation specialist position, 165085, around the sentence in its own
advertisement about "initiating, structuring and driving Actions" and "facilitating dialogue
and matchmaking between researchers and relevant companies, organisations and public
authorities". Matchmaking across eight departments and tens of thousands of papers is a search
problem before it is a relationship problem, and this is the search half.

## What it does, and what it refuses to do

Every candidate is a department and a topic, never a person. Each carries the evidence that
produced it: the papers behind it, the Danish organisations working on the same topic, whether
a shared European project already exists, and the components of the score. The score is a dull
formula printed next to every row it produced, so a reader can disagree with the weighting and
recompute rather than take it on trust.

The last act is the instrument measuring itself: harvest coverage by year, how many records
carry a DOI and can therefore reach a topic at all, how often a hand-checked topic label looks
wrong, and how often its own top candidates turn out to be collaborating already.

## The joins, and why they are safe

| Link | How | Why it holds |
|---|---|---|
| Paper to faculty and department | AU Pure over OAI-PMH, `ddf-mxd` format | The only source that knows which AU faculty a paper belongs to. OpenAlex cannot say. |
| Paper to topic and company co-authors | OpenAlex, by DOI, institution I204337017 | A company co-author is a typed fact in the record, not an inference. |
| Aarhus to Danish organisations | CORDIS Horizon Europe, participant identifier 999997736 on 439 projects | Both sides of a shared project carry the same identifier, so no organisation name is ever matched to another. |

## Personal data

The Pure feeds carry institutional email addresses, usernames and employee identifiers beside
author names. All three are removed at harvest, before anything reaches the disk, and the code
says why at the point it does it. Nothing person-level is computed, ranked or stored. Author
names appear on the page only behind a labelled control, only for papers already public, and
only as the citation they already are.

The AU Pure portal reserves text and data mining rights in its footer, which is a reservation
under Article 4(3) of the EU copyright directive, so the portal is not scraped. The harvest uses
the OAI-PMH endpoint, which exists to be harvested and feeds the Danish national research
database, with a self-identifying user agent and spaced requests. Before anything built from it
went further than this page, the right next step is a note to the Pure administrators, who sit
in the same administration as Science Bridge.

## Layout

| Path | What it does |
|---|---|
| `study/pure_harvest.py` | Harvests AU Pure by publication-year set, scrubs personal data, caches every response |
| `study/openalex.py` | Topics and co-author institution types for the harvested DOIs |
| `study/partners.py` | Danish organisations per topic from CORDIS, and whether AU already shares a project |
| `study/rank.py` | Writes `data/actions.json` and the honesty panel |
| `study/build_page_data.py` | Writes `docs/data.js` |
| `FACTS.md` | What was verified by hand before any of this was written, with the numbers |
| `NOTES.md` | What could not be verified, and the decisions a reader might make differently |

## What it cannot tell you

- A shared topic label is not a capability match. It means two groups write about similar
  things.
- The Danish company register is behind a signed declaration with no bulk download, and since
  the industry codes changed on 1 January 2025 they can no longer separate a biotechnology
  research firm from any other natural-science research company. So the partner side comes from
  European project participation, which is the part that is open and joinable.
- Absence of a shared project and of a company co-author is absence in two public records, not
  absence in the world.

## Sources

OpenAlex (CC0). CORDIS Horizon Europe bulk export (CC BY 4.0, Commission Decision 2011/833/EU).
Aarhus University Pure, OAI-PMH endpoint. Advertisement for position 165085.

Bolgaç Gülen, September 2026.
