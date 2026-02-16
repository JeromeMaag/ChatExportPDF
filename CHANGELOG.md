# Changelog

## [0.1.2] - 2026-02-16
### Fixed
- PDF attachment links now work reliably across PDF readers by URL-encoding link targets.

## [0.1.1] - 2026-02-16
### Added
- Exporter version is now included in generated reports (cover/metadata section).

## [0.1.0] - 2026-02-16
### Added
- Initial release.
- Export Threema iOS CoreData SQLite chats (`ThreemaData.sqlite`) to one readable PDF per conversation plus a companion `*_TECH.pdf`.
- Optional media extraction to a structured `media/` folder with links from PDFs.
