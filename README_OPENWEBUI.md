# MiView Dashboard - OpenWebUI Implementation

This is an implementation of the MiView Dashboard using FastAPI and a modern web interface with OpenWebUI design principles, replacing the Chainlit frontend.

## Features

- **Interactive Dashboard**: Displays oil prices and FX rates as interactive charts
- **LLM-powered Q&A**: Ask questions about market data and trends
- **Responsive Design**: Works on desktop and mobile devices
- **Real-time Charts**: Interactive Plotly-based visualizations
- **API Integration**: Connects to EIA and OpenExchangeRates APIs with fallback to mock data

## Prerequisites

- Python 3.9+
- Required packages (install with `pip install -r requirements.txt`):
  - fastapi
  - uvicorn[standard]
  - jinja2
  - httpx
  - python-dotenv
  - plotly

## Running the Dashboard

### Method 1: Using the batch script

Simply run the included batch script:

```
run_openwebui.bat
```

This will start both the backend and frontend services.

### Method 2: Manual startup

1. Start the backend API (in one terminal):

   ```
   cd backend
   uvicorn main:app --host 0.0.0.0 --port 8080
   ```

2. Start the OpenWebUI frontend (in another terminal):

   ```
   uvicorn miview_openwebui:app --host 0.0.0.0 --port 8000
   ```

3. Open your browser and navigate to http://localhost:8000

## Environment Variables

Create a `.env` file in the project root with these variables:

```
EIA_API_KEY=your_eia_api_key
OPENEXCHANGERATES_APP_ID=your_oxr_api_key
OPENROUTER_API_KEY=your_openrouter_api_key
```

If these are not provided, the application will use mock data.

## Architecture

This implementation uses:

- **FastAPI**: For the API endpoints and serving the web interface
- **Jinja2**: For HTML templating
- **Alpine.js**: For reactive UI components
- **Plotly.js**: For interactive charts
- **Tailwind CSS**: For styling

The frontend makes API calls to the backend endpoints, which in turn:

1. Fetch data from external APIs (or generate mock data)
2. Process the data for display
3. Return formatted responses for charts and Q&A

## Differences from Chainlit Implementation

- Uses a standard web interface instead of Chainlit's specialized UI
- More customizable charts and styling
- Standard frontend technologies (HTML, CSS, JavaScript)
- Direct API endpoints for data access
