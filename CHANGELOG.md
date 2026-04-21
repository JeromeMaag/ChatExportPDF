# Changelog

## [0.6.0] - 2026-04-21
### Added
- Added a Windows desktop GUI.
- Added PyInstaller packaging for a standalone `ChatExportPDF.exe`.

### Changed
- Shared CLI and GUI configuration parsing through a common config factory.

## [0.5.1] - 2026-04-08
### Changed
- Restored sender, timestamp, message type, and status in the normal chat bubble header.
- Added synthetic Threema and WhatsApp example data plus a notebook to run local example exports.

## [0.5.0] - 2026-04-08
### Changed
- Added chat-style message bubbles in the normal PDF export.
- Messages from the detected self participant are rendered on the right; other messages are rendered on the left.
- Direct chats fall back to the first sender on the right if no self participant is known.

## [0.4.0] - 2026-04-08
### Changed
- Renamed the project to `ChatExportPDF`.
- Added `chat-export` and `python -m chat_export` as the preferred entry points.
- Kept the previous entry points as compatibility aliases.

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
