# ChatExportPDF

This project exports chat data from different messenger sources into PDF reports.

Current sources:
- `threema` (iOS only)
- `whatsapp`

For each conversation, the exporter creates:
- a readable main PDF
- a `*_TECH.pdf` report

The main report is generic. The TECH report can be importer-specific. Threema has its own dedicated TECH report. WhatsApp currently uses the generic fallback TECH report.

## Supported Inputs

### Threema

- `ThreemaData.sqlite`
- optional `_EXTERNAL_DATA` folder for attachment recovery

Typical source:
- iOS app container backup or extracted app data

Typical iOS paths:
- `/private/var/mobile/Containers/Shared/AppGroup/<AppID>/ThreemaData.sqlite`
- `/private/var/mobile/Containers/Shared/AppGroup/<AppID>/.ThreemaData_SUPPORT/_EXTERNAL_DATA`

### WhatsApp

- exported `.zip` file
- the ZIP contains:
  - a chat text file
  - optional attachments with matching file names

Typical source:
- WhatsApp chat export ZIP created from the app itself

Supported WhatsApp export variants:
- Android-style chat text:
  - `31.12.26, 12:00 - User: Message`
- Apple-style chat text:
  - `[31.12.26, 12:00:20] User: Message`

If a WhatsApp ZIP contains multiple plausible `.txt` files, the exporter does not guess. In that case you must provide `--chat-text-name`.

## Output

In `--out-dir` the exporter creates:

- `conversations/`
  - one readable PDF per conversation
  - one `*_TECH.pdf` per conversation
- `media/`
  - extracted attachments per conversation if media export is enabled

## Installation

Requirements:
- Python `3.10` or newer
- `pip`

From the repository root, install the project:

```bash
python -m pip install -e .
```

Optional: use a virtual environment if you do not want to install the dependencies into your global Python environment.

## Usage

### Threema

Recommended with external attachment folder:

```bash
python -m chat_export --source threema --input-path "./ThreemaData.sqlite" --out-dir "./export" --external-folder "./_EXTERNAL_DATA"
```

### WhatsApp

WhatsApp export:

```bash
python -m chat_export --source whatsapp --input-path "./WhatsApp-Chat mit Max Mustermann.zip" --out-dir "./export"
```

WhatsApp ZIP with multiple plausible text files:

```bash
python -m chat_export --source whatsapp --input-path "./WhatsApp Chat - Max Mustermann.zip" --chat-text-name "_chat.txt" --out-dir "./export"
```

The preferred entry points are:
- `chat-export ...`
- `python -m chat_export ...`

### Desktop GUI

A simple Windows GUI is also available.

It supports:
- `threema` and `whatsapp`
- source-specific path fields
- basic and advanced options
- live log output inside the window
- default output folders next to the selected input file

## Command Line Options

### Required

- `--out-dir PATH`
  Output directory. It is created if it does not exist.

### Source Selection

- `--source {threema,whatsapp}`
  Selects the importer. Default: `threema`.

- `--input-path PATH`
  Generic input path for the selected source.
  - for `threema`: path to `ThreemaData.sqlite`
  - for `whatsapp`: path to the exported `.zip`

- `--db-path PATH`
  Legacy alias for the Threema database path.

- `--chat-text-name NAME`
  Only relevant for WhatsApp. Forces a specific chat text file inside the ZIP when multiple plausible `.txt` files exist.

### Optional

- `--external-folder PATH`
  Threema only. Path to `_EXTERNAL_DATA`. Recommended for complete attachment export.

- `--tz TIMEZONE`
  Timezone for rendered timestamps. Default: `Europe/Zurich`.

- `--no-media`
  Disable attachment export. PDFs are still generated.

- `--no-image-previews`
  Disable inline image previews in the normal PDF export. By default, image previews are enabled when image attachments are available.

- `--max-media-bytes N`
  Skip media blobs larger than `N` bytes. `0` disables the limit.

- `--limit-conversations N`
  Process only the first `N` conversations. `0` means all.

- `--limit-messages N`
  Process only the first `N` messages per conversation. `0` means all messages.

- `--log-level LEVEL`
  Logging verbosity. Allowed values: `DEBUG`, `INFO`, `WARNING`, `ERROR`.

- `--log-file PATH`
  Write logs additionally to a file.
