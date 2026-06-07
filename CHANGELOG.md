# Changelog

All notable changes to the WiseFood client are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
