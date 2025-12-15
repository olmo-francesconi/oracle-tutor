# Oracle Tutor

A fast, fuzzy-search engine for Magic: The Gathering cards, powering a REST API.

## Features

-   **Fuzzy Name Matching**: Finds cards even with typos or partial names using TF-IDF and cosine similarity.
-   **Smart Ranking**: Incorporates EDHREC rank to prioritize popular cards in search results.
-   **REST API**: FastAPI-based backend to integrate search into other applications.
-   **Local Data**: Downloads and indexes the latest Scryfall Oracle data for offline speed.

## Installation

1.  Clone the repository.
2.  Navigate to the API directory:
    ```bash
    cd api
    ```
3.  Install `uv` (once):
    ```bash
    # macOS (Homebrew)
    brew install uv

    # Or via the official installer (macOS/Linux)
    # curl -LsSf https://astral.sh/uv/install.sh | sh
    ```
4.  Create a virtual environment and install dependencies:
    ```bash
    uv venv
    uv pip install -r requirements.txt
    uv pip install -e .
    ```

## Quick Start

### 1. Initialize Data
Before searching, you need to download the card database from Scryfall and build the local index.

```bash
# From the api directory
python -m oracle_tutor_api.data_builder
```

This creates `data/cards.json` and `data/card_names.json`. The database can be automatically updated daily (see [Daily Updates](#daily-updates) below).

### 2. Run the API Server
Start the HTTP API using Uvicorn:

```bash
# From the api directory
uvicorn oracle_tutor_api.api:app --reload
```

**Endpoints:**

-   `GET /search?q=lotus&limit=5` - Fuzzy search for cards by name.
-   `GET /suggest-names?q=lotus&limit=5` - Search for card names only.

**Example:**
```bash
curl "http://localhost:8000/search?q=black%20lotus&limit=5"
```

**Note:** The API automatically starts a background scheduler for daily updates when it starts. See [Daily Updates](#daily-updates) for configuration options.

### 3. Run the Web Frontend (Optional)

A modern, interactive web frontend is available for easy searching:

```bash
cd frontend
npm install
npm start
```

Then open your browser to `http://localhost:3000`.

The frontend features:
- Real-time autocomplete suggestions as you type
- Keyboard navigation (arrow keys, Enter, Escape)
- Beautiful, responsive UI
- See [frontend/README.md](frontend/README.md) for more details

## Daily Updates

The card database can be automatically updated daily to stay in sync with Scryfall's latest data. When updates are available, the system will:
1. Download the latest bulk data from Scryfall
2. Rebuild the JSON index files
3. Update the TF-IDF search engine
4. Automatically reload the API data (if running)

### Automatic Updates with API

**The update scheduler runs automatically when you start the API server.** No additional setup required!

The scheduler is enabled by default and runs daily at 2:00 AM local time. You can configure it using environment variables:

    ```bash
    # Set custom update time (24-hour format)
    export ORACLE_TUTOR_API_UPDATE_HOUR=3
    export ORACLE_TUTOR_API_UPDATE_MINUTE=30
    
    # Disable the scheduler if you prefer manual updates
    export ORACLE_TUTOR_API_DISABLE_SCHEDULER=1
    
    # Start the API (scheduler starts automatically)
    # From the api directory
    uvicorn oracle_tutor_api.api:app --reload
    ```
    
    ### Cron Job
    
    Add a cron job to run the update script daily. Edit your crontab:
    
    ```bash
    crontab -e
    ```
    
    Add a line to run the update daily at 2:00 AM:
    
    ```
    0 2 * * * cd /path/to/mtg-search/api && python -m oracle_tutor_api.daily_update >> data/update.log 2>&1
    ```
    
    Replace `/path/to/mtg-search/api` with the actual path to your project's api directory.
    
    ### Manual Update
    
    You can also run the update manually at any time:
    
    ```bash
    # From the api directory
    python -m oracle_tutor_api.daily_update
    ```
    
    ### Reloading API Data
    
    After an update, restart the API server to reload the data:
    
    ```bash
    # Stop the server (Ctrl+C) and restart
    # From the api directory
    uvicorn oracle_tutor_api.api:app --reload
    ```

## How It Works

-   **Data Source**: Consumes Scryfall's `oracle_cards` bulk data.
-   **Search Algorithm**: Uses `scikit-learn` to build a TF-IDF matrix of card name n-grams. Queries are matched using cosine similarity against this matrix, with a boost factor for cards with higher EDHREC ranks.

## License

This project is licensed under the terms of the [GNU General Public License v3.0](LICENSE).
