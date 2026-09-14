# Verified facts for the Action finder (AU Science Bridge)

Checked 14 September 2026. Anything not verified here is not used in the build.

## The join that carries the page

CORDIS Horizon Europe bulk export, `https://cordis.europa.eu/data/cordis-HORIZONprojects-csv.zip`
(36.7 MB, CC BY 4.0 under Decision 2011/833/EU, semicolon separated, UTF-8 BOM, decimal comma
in money fields). Downloaded and joined here, not taken on trust:

- `organization.csv` holds 145,274 rows for Horizon Europe.
- Aarhus University is participant identifier **999997736**, name string `AARHUS UNIVERSITET`,
  on **439 projects**.
- Self-joining that file on those 439 project identifiers gives 6,451 partner rows, of which
  **67 rows are Danish for-profit organisations (`activityType` PRC, `country` DK), covering
  53 distinct organisations**. Among them: Vattenfall Vindkraft, Carlsberg, Topsoe, DLF Seeds,
  NIRAS, Aarhus Vand, Kvantify, HydrogenPro.

The link is a hard join on the same participant identifier appearing on both sides of a shared
project. No name matching anywhere, which is what makes the claim safe to publish.

Do not merge these separate identifiers into Aarhus University: Aarhus Universitetshospital
999643880, Aarhus Kommune 992597994, Arkitektskolen i Aarhus 968659849.

## Research output

- OpenAlex institution for Aarhus University is **I204337017** (224,698 works), ROR
  `https://ror.org/01aj84f44`, Crossref funder 100007605, CVR 31119103. Works without a key;
  a filtered query was run here successfully. Licence CC0.
- OpenAlex cannot give the faculty level. **AU Pure's OAI-PMH endpoint can**:
  `https://pure.au.dk/ws/oai`, no key, and it exposes a four-level hierarchy with the faculty
  at level 2 (`<level2>Natural Sciences</level2>`). The Pure REST API at `/ws/api` needs a key
  and the portal HTML returns 403, so the OAI endpoint is the only usable route.
- The Pure portal footer reserves text and data mining rights, which is an EU DSM Article 4(3)
  reservation. That puts portal scraping out of bounds. The OAI endpoint exists to be harvested
  and feeds the Danish national research database, but a short note to pure@au.dk before
  publishing anything from the harvest is the right move, and Science Bridge sits in the same
  administration.
- The Pure feeds carry institutional email addresses, usernames and employee identifiers.
  Strip all three at harvest and say on the page that they were stripped.

## What is off the critical path, and why

- **CVR is gated.** `distribution.virk.dk/cvr-permanent/_search` returns 401; access needs an
  email to cvrselvbetjening@erst.dk and a signed declaration about advertising-protected
  entities. There is no free bulk download and none is planned.
- **Industry codes cannot carry a topic claim.** DB25 replaced DB07 in CVR on 1 January 2025 and
  merged code 721100, research and development in biotechnology, into the generic 72.10.00
  alongside other natural-science and engineering research. A sector code answers what sector a
  company is in, not what science it needs, and since that merge it cannot even separate a
  protein-engineering firm from a seismology consultancy.
- **European patent citations to papers** have no open, identifier-keyed dataset, so no claim
  about European patent coverage can be made honestly.

## Handling rules for the build

- The Danmarks Frie Forskningsfond grant corpus is reachable with an API key that sits in
  dff.dk's own public page source. Fetch server-side once and cache the result; never ship that
  key to a browser.
- Villum's open data file carries age and gender fields next to named people. Drop both on
  ingest.
- Default every recommendation to department level. Named researchers appear only where they
  already appear publicly, as authors of a cited paper linked to their own profile, and only
  behind the labelled control Bo asked for.
