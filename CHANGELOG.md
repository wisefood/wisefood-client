# Changelog

All notable changes to the WiseFood client are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.0.37

### Changed

- `recipe_source` no longer requires schema.org JSON-LD. Microdata, RDFa,
  hRecipe, the common WordPress recipe plugins, and plain prose — a heading
  of ingredients followed by a method, in any of several languages — all
  count, and the profile reports which form was found. They are not equally
  useful, so it says so rather than collapsing them into a yes: JSON-LD and
  microdata carry ingredients and steps as data, a plugin renders them in
  known classes, prose has to be read.

- It uses the page it was given as the recipe index before hunting the site
  for sitemaps. Asked about `bestofhungary.co.uk/blogs/recipes` it went to
  the site root, found Shopify's product sitemap and reported that 383 pages
  carried no recipes; the nineteen linked from the page it was handed all
  did.

- The whole profile is bounded at 45 seconds. One site ran for 87 before
  this, with a curator watching a spinner.

### Fixed

- A download the server cuts off part-way is resumed rather than failed.
  Greece's national guides sit behind a host that drops the connection almost
  every time: a 28 MB guide arrived as a different fragment on each attempt
  and failed on all of them. It supports range requests, so the fetch asks
  for the rest and keeps asking while progress is being made. That file now
  arrives whole, all 28,531,618 bytes of it.

- An incomplete download is reported as a failure instead of returned as a
  short file. One attempt had come back "successful" with a third of a PDF,
  which would have extracted into a third of a national guide with nothing
  downstream any the wiser.

- Staged files are deleted once the catalog has them, and abandoned ones are
  swept when the next file is staged. Nothing had ever deleted them, so every
  PDF ever fetched stayed in the pod's temporary directory.

- Country and language go in as ISO codes. A proposal records "Greece" and
  "Greek" because that is what a curator reads; the catalog takes ISO 3166-1
  alpha-2 and ISO 639-1 and refused both with `String should have at most 2
  characters`. `pycountry` does the lookup, so this is not a table somebody
  has to remember to extend.

- A licence a curator overrode now reaches the catalog as `unspecified-oa`.
  The override let the run copy the content but produced no licence value,
  and a guide's schema requires one — so an approved integration got all the
  way to the create call and stopped there.

## 0.0.36

0.0.35 reached PyPI from an earlier build, and PyPI versions are immutable —
so everything below was written for 0.0.35 and ships here instead. 0.0.35 has
the new tools; it does not have any of these fixes.

### Fixed

- **Every HTML page was coming back with no text.** The body is streamed into
  chunks and the response closed, so the later `response.text` was always
  empty. An assistant looking at a ministry page listing twenty-two national
  dietary guides saw nothing, concluded there was nothing there, and went
  back to searching — which is where a great deal of the token budget went.

- Creates could never have worked against the catalog. `urn` is required on
  every creation schema and was never sent; every schema is `extra="forbid"`
  and only articles declare an `extras` field, so provenance sent to a guide
  or a textbook was rejected outright; and the licence went in as the page
  wrote it ("CC BY-NC-SA 4.0") rather than as the enum spells it
  ("CCBYNCSA"). The first real integration failed on all three at once.

- Licences are normalised where they are first recorded and again on the way
  out. Anything unrecognisable becomes undetermined rather than a guess.

- `fetch_url` reports the documents a page links — PDFs, spreadsheets, and
  images, because a national guide is often published as a poster or a
  brochure — each with the link text that names it, since the href is usually
  a meaningless id. A landing page is often an index, not a document.

- `fetch_url(outline_only=True)` returns a page's headings and files without
  its prose, for roughly a third of the payload. Its default text size also
  drops to 8,000 characters, which is what the agent loop clips a result to
  anyway — the rest was built and discarded.

## 0.0.35

### Added

- `recipe_source` — profiles a recipe website, because a recipe collection is
  the one kind of source with no document to read. It finds where the site
  lists its own pages, samples a spread of them, and counts how many carry
  schema.org Recipe markup. That share is the number worth quoting: a site
  with thousands of pages and no markup has nothing importable, and learning
  that here is far cheaper than part-way through an import. What it returns
  is also what the importer needs — `harvest_location` is the sitemap or
  feed, not the homepage.

  It samples several candidate lists rather than trusting the first. BBC Good
  Food publishes `-post.xml` and `-recipe.xml` side by side, and one guess
  gets the blog.

- `import_recipe_source` and `recipe_import_status` — the harvest itself, and
  polling it. Gated like every other write, and gated as content: a harvested
  recipe is the site's own text in our database, so a source whose licence
  does not permit copying is refused before anything is sent. It reaches the
  importer through `ToolContext.recipes_post`/`recipes_get`, which the host
  supplies; there is no built-in transport, so a deployment that has not
  wired one simply reports that no importer is configured.

- `journal_articles` — lists what a journal has published, from Crossref.
  Asked to check ScienceDirect's `Nutrition` and Springer's `Nutrition
  Journal`, the assistant could only report that both refuse automated
  fetches and hand the work back to the curator. Crossref is the registry
  those publishers deposit into and is meant to be read by machines. Takes
  an ISSN, a journal URL as somebody pasted it, or a title; a URL that names
  the journal only by the publisher's internal id has its ISSN read off the
  page.

  An ambiguous name is refused with its candidates rather than resolved to
  the best guess: Crossref's top hit for "nutrition" is a different journal
  than Elsevier's, and a wrong journal's articles would look entirely normal
  all the way into the catalog.

  Each article is marked with whether the catalog already holds it, checked
  in one search rather than a step per DOI.

### Changed

- `fetch_url` retries once with a browser's headers when a site answers 401,
  403, 406, 429 or 503. Those mean "not you" rather than "not here", and the
  pages in question are ones a person could open. Every redirect hop is
  still checked against the destination guard, so this changes how we
  introduce ourselves and never where we may end up. A 404 is not retried.

- robots.txt is consulted only when the deployment sets
  `ToolContext.respect_robots`, and the default is now off. robots.txt
  addresses crawlers; this is one expert pasting one URL and waiting for an
  answer about that one document, under a per-user rate limit. The
  destination guard is untouched — a URL resolving to a private address is
  still refused, because that is a security control and not a preference.

## 0.0.34

### Fixed

- An `Optional[...]` tool argument produced a schema that did not admit null,
  so a model reporting "this source states no licence" the only way it can —
  `licence: null` — had its entire turn rejected by the provider before any
  of our code ran: *parameters for tool propose_source did not match schema:
  `/licence`: expected string, but got null*. Optional arguments are now
  nullable in the generated schema. Being absent from `required` was never
  the same promise: that permits omitting an argument, not sending an empty
  one. Every tool with an optional argument was one explicit null away from
  the same failure, so this is checked across the whole tool surface.

## 0.0.33

### Fixed

- `catalog_coverage` matched a country by *name* against documents that store
  an ISO code, and the field it searched — `country` — does not exist on them
  at all. Asking what Ireland holds returned nothing while `IE` returned
  twenty-four, and "nothing" reads as a gap: the assistant proposed sources
  the catalog already had. Country and language are now resolved to their ISO
  codes (either form works — "Ireland" or "IE", "Greek" or "el") and applied
  as filters on `region` and `language` rather than as words in a query.

- Coverage counted only what a search happened to return and said nothing
  about status, so twelve draft guides were invisible to it. An unpublished
  entry is still a source somebody has already brought in; the result now
  carries `by_status` and `draft_count`, and says that a gap has to be judged
  against both.

### Changed

- `pycountry` joins the `mcp` extra, for the code resolution above.

## 0.0.32

### Added

- `infer_guidelines` — reads dietary rules out of a source that does not
  already list them: advice in prose, a web page, a summary chapter. The
  extraction pipeline handles a guide that ships as numbered recommendations
  in a PDF; this covers everything that does not.

  It is the one tool that *composes* catalog content rather than transcribing
  it, so the safeguard is the feature: every rule carries the verbatim span it
  came from, and that quote is checked against the text that was actually
  sent. A model asked for verbatim quotes will still occasionally paraphrase
  one, and a paraphrased quote is indistinguishable from a real one to whoever
  reads the result — so rules whose quote is not in the source are dropped
  rather than shown, and the count of dropped ones is reported.

  Results are marked `inferred` throughout and say whether the source already
  presented the rules as a list or they were assembled from prose. Nothing
  from it reaches the catalog on its own.

- `ToolContext.inference_model`, defaulting to the research model.

## 0.0.31

### Added

- `wisefood_mcp.passages` — a textbook PDF becomes retrievable passages, with
  each one carrying the heading stack it came from. No model is involved:
  unlike a dietary guide's rules, a passage is a span of the book with enough
  context to be found, so this is text extraction and boundaries. Paragraphs
  are not split unless one exceeds a passage, overlaps cut at sentences, and
  words hyphenated across PDF line breaks are rejoined.
- `wisefood_mcp.fctables` — profiles a food composition table into the
  descriptive fields an `FCTable` carries: entries, nutrient coverage,
  completeness, units, reference portions. It returns the column names it
  judged from, so the profile can be argued with rather than trusted.
- Tools: `extract_textbook_passages`, `profile_fctable`, `create_fctable`.
- `fetch_url` now keeps spreadsheets (XLSX/XLS/ODS/CSV/TSV) as pending
  artifacts as well as PDFs. Running a composition table through an HTML text
  extractor produces confident nonsense.

### Note

A scanned PDF is reported as needing OCR rather than returned as an empty
success, and `FCTable` is a metadata entity — there is no row store behind it,
so a table is profiled rather than ingested.

## 0.0.30

### Added

- `doi_metadata` — an article's bibliographic record from Crossref, shaped like
  a catalog article. Use it before proposing any article: a citation with
  invented authors reads perfectly, cites perfectly and is false, and unlike a
  broken link nothing about it looks wrong later.
- Tools: `enqueue_article_enrichment`, `article_enrichment_status`.
- `doi`, `venue`, `publication_year` and `authors` added to catalog search
  summaries, which makes "do we already hold this paper?" an exact question
  rather than a fuzzy title match.

## 0.0.29

### Security

- **`fetch_url` could reach inside the caller's own network.** It validated the
  URL scheme and nothing else, and followed redirects blindly, so private
  addresses — link-local metadata services, internal hostnames, loopback —
  were reachable and their responses were returned. Every hostname is now
  resolved and every address it resolves to must be public; one inward answer
  refuses the fetch; each redirect hop is re-checked; and the size limit
  applies while streaming rather than after the body is in memory.
  `WISEFOOD_MCP_ALLOWED_PRIVATE_HOSTS` allows named internal hosts
  deliberately. DNS rebinding is mitigated, not closed: the connection is still
  made by hostname.

### Added

- `Credentials(access_token=...)` — **delegation**, for a service acting on
  behalf of the person who called it, with that person's rights and no others.
  The property that makes it worth anything is negative: a delegated client
  cannot obtain a token by itself. `authenticate()` raises, an expired token
  raises, and there is no fallback to client credentials. An opaque token is
  used as given and left to the API to judge.

## 0.0.28

### Fixed

- `import_guidelines` posted `guide_urn` where the core route's request model
  requires `guide_id`. The body validated as a *missing* field: a 422, no
  import, and nothing that reads as a bug. `dry_run` is now explicit and
  defaults to true on this side too, so a caller who forgets it spends a round
  trip rather than making an unreviewed write.

### Added

- `guideline_extraction_status`, and `ToolContext.core_get` for it.

## 0.0.27

### Added

- `wisefood_mcp` — the WiseFood catalog and research tools, usable two ways:
  as a library whose OpenAI-style schemas drive a tool-calling model, and as an
  MCP server (`wisefood-mcp`) for any MCP host. Install the SDK with the `mcp`
  extra; the library itself imports without it.
- Three rules the package exists to enforce: the provider executes nothing but
  web search; nothing writes to the catalog without a proposal a person
  approved, and there is no tool that approves; a licence is evidence with
  quotes attached, not a verdict.

## 0.0.26

### Added

- Usage telemetry (`client.analytics`) and feedback (`client.feedback`). The
  client now reports which operations were called so platform usage reports
  cover scripts and notebooks, not only the web app. Never sends arguments or
  results. Off with `WISEFOOD_TELEMETRY=0` or `Client(..., telemetry=False)`.
- Every request carries `X-Request-Id`, `X-Client` and `X-Client-Session`, so a
  call from a notebook can be followed through the platform's logs.

### Fixed

- `__version__` is read from the installed package instead of a literal that had
  drifted three releases behind `pyproject.toml`. It is what the client reports
  as `X-Client`, so the stale value was mislabelling every request.

## [Unreleased]

### Added
- Read the Docs documentation site (Sphinx + MyST), reconstructed changelog, and
  modern-library project files (`README`, `AGENTS.md`, `CONTRIBUTING.md`).

## [0.0.22]

### Added
- `page_count` field on guides.
- Structured textbook bookmark constructors for the textbook structure tree
  (`add_root` / `add_chapter` / `add_section`).
- Read the Docs configuration (`.readthedocs.yaml`).

### Fixed
- Internal consistency fixes around guides and artifact handling.

## [0.0.16]

### Added
- Textbook integration: `Textbook`, `TextbookPassage`, the structure tree, and
  textbook-scoped passage browsing (`textbook.passages`, `passages.page[n]`,
  `bulk_replace`).
- Guide pages accessor (`guide.page[n]`) so guidelines can be fetched per page.

### Changed
- Guides and guidelines updated to match the latest catalog API.

## [0.0.9]

### Added
- Artifact management: upload, parent-bound artifacts, and `download_to` for saving
  files locally without caller boilerplate.
- Support for guides and guidelines.
- Article schema refinements and FCTables support.

### Changed
- Member profile aligns with the API: allergies treated as a top-level field.

## [0.0.3]

### Added
- Two separate clients for the WiseFood platform: the Data API (`DataClient`) and the
  Core API (`Client`).
- Machine-to-machine (client credentials) authentication.
- Household and member management on the Core API.
- Lazy loading of collection entities, search, and AI-enhancement capabilities.
- Base entity/collection proxy classes with IPython autocomplete support.
- Typed API exceptions mapped from the server error envelope.

[Unreleased]: https://github.com/wisefood/wisefood-client/compare/v0.0.22...HEAD
[0.0.22]: https://github.com/wisefood/wisefood-client/releases/tag/v0.0.22
[0.0.16]: https://github.com/wisefood/wisefood-client/releases/tag/v0.0.16
[0.0.9]: https://github.com/wisefood/wisefood-client/releases/tag/v0.0.9
[0.0.3]: https://github.com/wisefood/wisefood-client/releases/tag/v0.0.3
