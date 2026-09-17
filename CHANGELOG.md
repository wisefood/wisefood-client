# Changelog

All notable changes to the WiseFood client are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
