# MTG Search Frontend

A modern, interactive web frontend for the MTG Search API.

## Features

- 🔍 Real-time fuzzy search with autocomplete suggestions
- ⌨️ Keyboard navigation (Arrow keys, Enter, Escape)
- 🎨 Beautiful, modern UI with smooth animations
- ⚡ Debounced API calls for optimal performance
- 📱 Responsive design for mobile and desktop

## Setup

1. Install dependencies:
   ```bash
   cd frontend
   npm install
   ```

2. Make sure your API server is running:
   ```bash
   # In the project root
   uvicorn mtg_search.api:app --reload
   ```

3. Start the frontend server:
   ```bash
   npm start
   ```

4. Open your browser to `http://localhost:3000`

## Configuration

You can customize the API URL by setting the `API_URL` environment variable:

```bash
API_URL=http://localhost:8000 npm start
```

## Usage

- Type in the search bar to see instant suggestions
- Use arrow keys to navigate suggestions
- Press Enter to select a suggestion
- Press Escape to close suggestions
- Click on a suggestion to select it

