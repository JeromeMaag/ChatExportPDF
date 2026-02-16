# Threema Chat Export (iOS) — PDF Reports

This project exports Threema chats from an iOS CoreData SQLite database into **one readable PDF per chat** and an additional **`*_TECH.pdf`** companion report per chat with more technical/forensic details (IDs, hashes, media provenance, etc.).  
If configured, it also extracts attachments (images/audio/video/files) into a structured media folder and links to them from the PDFs.

## What you need (input artifacts)

### 1) Threema database
- `ThreemaData.sqlite`

Example location on iOS:
- `/private/var/mobile/Containers/Shared/AppGroup/<AppID>/ThreemaData.sqlite`

### 2) External attachment storage (recommended)
- `_EXTERNAL_DATA` directory

Example location on iOS:
- `/private/var/mobile/Containers/Shared/AppGroup/<AppID>/.ThreemaData_SUPPORT/_EXTERNAL_DATA`



## Output

In `--out-dir` you will get:

- `conversations/`  
  - `conv_<pk>_<title>.pdf` (readable report)  
  - `conv_<pk>_<title>_TECH.pdf` (technical companion report)
- `media/` (if enabled)  
  - one folder per chat with extracted attachments (clickable links from the PDFs)

## Console commands

### Install (Repo Directory)
```bash
python -m pip install -e .
```

### Run (recommended: with external folder)
```bash
python -m threema_export --db-path "./ThreemaData.sqlite" --out-dir "./export" --external-folder "./EXTERNAL"
```

### Run (without external folder — attachments may be incomplete)
```bash
python -m threema_export --db-path "./ThreemaData.sqlite" --out-dir "./export"
```

## Command line options

### Required arguments
- `--db-path PATH`  
  Path to `ThreemaData.sqlite`.

- `--out-dir PATH`  
  Output directory. Will be created if it does not exist.

### Optional arguments
- `--external-folder PATH` (default: not set)  
  Folder containing the `_EXTERNAL_DATA` files.  
  Recommended for complete attachment export.

- `--tz TIMEZONE` (default: `Europe/Zurich`)  
  Timezone used for rendering timestamps in PDFs.

- `--no-media`  
  Disable media export entirely (PDFs only, no `media/` folder).

- `--max-media-bytes N` (default: `0`)  
  Skip media blobs larger than `N` bytes.  
  `0` disables the size limit.

- `--limit-conversations N` (default: `0`)  
  Process only the first `N` conversations.  
  `0` means all conversations.

- `--limit-messages N` (default: `0`)  
  Process only the first `N` messages per conversation.  
  `0` means all messages.

- `--log-level LEVEL` (default: `INFO`)  
  Logging verbosity. Allowed values: `DEBUG`, `INFO`, `WARNING`, `ERROR`.

- `--log-file PATH` (default: not set)  
  Write logs additionally to a file.

