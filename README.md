# mtg-search

A fast, fuzzy-search engine for Magic: The Gathering cards, powering a terminal user interface (TUI) and a REST API.

## Features

-   **Fuzzy Name Matching**: Finds cards even with typos or partial names using TF-IDF and cosine similarity.
-   **Smart Ranking**: Incorporates EDHREC rank to prioritize popular cards in search results.
-   **Terminal UI**: Interactive, live-updating search interface in your terminal.
-   **REST API**: FastAPI-based backend to integrate search into other applications.
-   **Local Data**: Downloads and indexes the latest Scryfall Oracle data for offline speed.

## Installation

1.  Clone the repository.
2.  Install the dependencies:
    ```bash
    pip install -r requirements.txt
    ```
    *(Recommended: use a virtual environment)*

## Quick Start

### 1. Initialize Data
Before searching, you need to download the card database from Scryfall and build the local index.

```bash
python -m mtg_search.data_builder
```

This creates `data/cards.json` and `data/card_names.json`. The database can be automatically updated daily (see [Daily Updates](#daily-updates) below).

### 2. Run the CLI
Launch the interactive terminal search:

```bash
python -m mtg_search
```
*Or explicitly:* `python -m mtg_search.cli`

**Controls:**
-   **Type** to search.
-   **Up/Down Arrows** to select matches.
-   **Enter** to clear input.
-   **Esc** or **Ctrl+C** to quit.

### 3. Run the API Server
Start the HTTP API using Uvicorn:

```bash
uvicorn mtg_search.api:app --reload
```

**Endpoints:**

**Public Endpoints (no authentication required):**
-   `GET /search?q=lotus&limit=5` - Fuzzy search for cards.
-   `GET /cards/{id}` - Get full details for a specific card by ID.

**Admin Endpoints (require API key authentication):**
-   `POST /reload` - Reload card data from disk (useful after running updates).
-   `GET /scheduler/status` - Check the status of the automatic update scheduler.
-   `POST /scheduler/update-now` - Manually trigger an update check.

Visit `http://127.0.0.1:8000/docs` for the interactive API documentation.

**Note:** The API automatically starts a background scheduler for daily updates when it starts. See [Daily Updates](#daily-updates) for configuration options.

### API Security

Admin endpoints are protected by API key authentication. To secure your API:

1. **Set an API key** via environment variable:
   ```bash
   export MTG_SEARCH_API_KEY="your-secret-api-key-here"
   ```

2. **Use the API key** when calling admin endpoints:

   **Via Header (recommended):**
   ```bash
   curl -X POST http://localhost:8000/reload \
     -H "X-API-Key: your-secret-api-key-here"
   ```

   **Via Query Parameter:**
   ```bash
   curl -X POST "http://localhost:8000/reload?api_key=your-secret-api-key-here"
   ```

   **In the API docs:**
   Click the "Authorize" button at the top of the Swagger UI and enter your API key.

**⚠️ Important:** If no API key is set, admin endpoints will be accessible to anyone. Always set `MTG_SEARCH_API_KEY` in production!

## Daily Updates

The card database can be automatically updated daily to stay in sync with Scryfall's latest data. When updates are available, the system will:
1. Download the latest bulk data from Scryfall
2. Rebuild the JSON index files
3. Update the TF-IDF search engine
4. Automatically reload the API data (if running)

### Automatic Updates with API (Recommended)

**The update scheduler runs automatically when you start the API server.** No additional setup required!

The scheduler is enabled by default and runs daily at 2:00 AM local time. You can configure it using environment variables:

```bash
# Set custom update time (24-hour format)
export MTG_SEARCH_UPDATE_HOUR=3
export MTG_SEARCH_UPDATE_MINUTE=30

# Disable the scheduler if you prefer manual updates
export MTG_SEARCH_DISABLE_SCHEDULER=1

# Start the API (scheduler starts automatically)
uvicorn mtg_search.api:app --reload
```

Check scheduler status:
```bash
curl http://localhost:8000/scheduler/status
```

Manually trigger an update:
```bash
curl -X POST http://localhost:8000/scheduler/update-now
```

### Option 1: Standalone Python Scheduler

Run the built-in scheduler that checks for updates daily:

```bash
python -m mtg_search.scheduler
```

By default, updates run at 2:00 AM local time. You can customize the time:

```bash
python -m mtg_search.scheduler --hour 3 --minute 30
```

The scheduler runs in the foreground. For production, consider running it as a systemd service or in a screen/tmux session.

### Option 2: Cron Job

Add a cron job to run the update script daily. Edit your crontab:

```bash
crontab -e
```

Add a line to run the update daily at 2:00 AM:

```
0 2 * * * cd /path/to/mtg-search && python -m mtg_search.daily_update >> data/update.log 2>&1
```

Replace `/path/to/mtg-search` with the actual path to your project directory.

### Manual Update

You can also run the update manually at any time:

```bash
python -m mtg_search.daily_update
```

### Reloading API Data

After an update, if your API server is running, you can reload the data without restarting:

```bash
curl -X POST http://localhost:8000/reload
```

Or visit the `/reload` endpoint in your browser or API documentation.

## How It Works

-   **Data Source**: Consumes Scryfall's `oracle_cards` bulk data.
-   **Search Algorithm**: Uses `scikit-learn` to build a TF-IDF matrix of card name n-grams. Queries are matched using cosine similarity against this matrix, with a boost factor for cards with higher EDHREC ranks.

## License

This project is licensed under the terms of the [GNU General Public License v3.0](LICENSE).
