# rss2cubox

GitHub Actions scheduled RSS ingestion to Cubox Open API.

## Environment

- `CUBOX_API_URL` (required): personal Cubox API URL
- `CUBOX_FOLDER` (optional, default `RSS Inbox`)
- `KEYWORDS_INCLUDE` (optional, comma-separated)
- `KEYWORDS_EXCLUDE` (optional, comma-separated)
- `MAX_ITEMS_PER_RUN` (optional, default `30`)

## Test

```bash
python -m pip install -e ".[dev]"
pytest -q
```
