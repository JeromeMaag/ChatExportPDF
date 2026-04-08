# Changelog

## [0.3.1] - 2026-04-08
### Added
- Added inline image previews in the normal PDF export for image attachments.
- Added `--no-image-previews` to disable image previews when needed.

## [0.3.0] - 2026-04-07
### Added
- Added WhatsApp ZIP import support.
- Added support for Apple-style and Android-style WhatsApp chat export formats.
- Added explicit `--chat-text-name` handling for WhatsApp ZIPs with multiple plausible chat text files.

### Changed
- Updated the README with current usage examples and multi-source export documentation.

## [0.2.0] - 2026-04-07
### Changed
- Refactored the export flow to support pluggable importers.
- Introduced a normalized conversation model as the internal export format.
- Split generic rendering from Threema-specific import and TECH-report logic.
- Reorganized the package structure to prepare for additional chat sources.

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
