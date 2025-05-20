import os
import datetime as dt
import httpx
from typing import List, Dict, Any
from dotenv import load_dotenv
import random
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

EIA_API_BASE_URL = "https://api.eia.gov/v2/petroleum/pri/spt/data/"
EIA_KEY = os.getenv("EIA_API_KEY")
OXR_API = "https://openexchangerates.org/api/latest.json"
OXR_KEY = os.getenv("OPENEXCHANGERATES_APP_ID")

def generate_mock_oil_data(start: str, end: str) -> List[Dict[str, Any]]:
    start_date = dt.datetime.strptime(start, "%Y-%m-%d").date()
    end_date = dt.datetime.strptime(end, "%Y-%m-%d").date()
    # Ensure correct calculation for the number of days
    delta = end_date - start_date
    days = delta.days + 1 # Add 1 because we want to include the end_date

    data = []
    for i in range(days):
        current_date = start_date + dt.timedelta(days=i)
        # Generate a somewhat realistic oil price
        base_price = 80.0
        price = base_price + (i % 10) * 0.1 + random.uniform(-0.5, 0.5) # More subtle daily changes
        data.append({
            "date": current_date.strftime("%Y-%m-%d"), # Use "date" to match the transform
            "value": str(round(price, 2)) # EIA returns values as strings
        })
    logger.info(f"Generated {len(data)} mock oil data points from {start} to {end}")
    return data

async def fetch_oil_prices(start: str, end: str) -> List[Dict[str, Any]]:
    if not EIA_KEY:
        logger.warning("EIA_API_KEY not found. Using mock data.")
        return generate_mock_oil_data(start, end)
    try:
        # Parameters according to EIA API v2 documentation
        params = {
            "api_key": EIA_KEY,
            "frequency": "daily",
            "data[0]": "value", # Requesting the 'value' column
            "facets[series][]": "RBRTE", # Brent Crude Oil series ID
            "start": start,
            "end": end,
            "sort[0][column]": "period", # Sort by date
            "sort[0][direction]": "asc", # Ascending order
        }
        
        # Construct the URL with httpx.AsyncClient correctly handling params
        async with httpx.AsyncClient(timeout=30.0) as client:
            logger.info(f"Requesting EIA API: {EIA_API_BASE_URL} with params: {params}")
            r = await client.get(EIA_API_BASE_URL, params=params)
            r.raise_for_status() # Will raise an exception for 4XX/5XX responses
        
        response_data = r.json()
        logger.info(f"EIA API response received, status_code={r.status_code}")
        
        # Check for API-specific errors or warnings in the response
        if "response" not in response_data or "data" not in response_data["response"]:
            # Handle cases where the API returns a 200 OK but with an error message in the JSON
            if "error" in response_data:
                logger.error(f"EIA API returned an error: {response_data['error']}")
            elif "warnings" in response_data:
                logger.warning(f"EIA API returned warnings: {response_data['warnings']}")
            else:
                logger.error(f"EIA API response format unexpected: {response_data}")
            return generate_mock_oil_data(start, end) # Fallback to mock

        # EIA API v2 returns data in response_data['response']['data']
        # Each item is a dictionary, e.g., {'period': '2023-05-01', 'value': '75.00', 'series-description': 'Brent Crude Oil Spot Price'}
        # We need to transform it to our desired format: {'date': 'YYYY-MM-DD', 'value': 'price_as_string'}
        
        api_data = response_data["response"]["data"]
        logger.info(f"EIA API returned {len(api_data)} data points")
        
        transformed_data = []
        for item in api_data:
            # Ensure 'period' and 'value' keys exist
            if "period" in item and "value" in item:
                transformed_data.append({
                    "date": item["period"], # 'period' is the date field
                    "value": item["value"]  # 'value' is already a string as per Jan 2024 docs
                })
            else:
                logger.warning(f"Skipping malformed item from EIA API: {item}")
        
        if not transformed_data and api_data:
            # This means all items were malformed, which is unlikely but good to log
            logger.warning("EIA API returned data, but none could be transformed. Check data structure.")
            logger.warning(f"First data item example: {api_data[0] if api_data else 'No data'}")
            return generate_mock_oil_data(start, end)

        return transformed_data
        
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error fetching oil prices: {e.response.status_code} - {e.response.text}")
        return generate_mock_oil_data(start, end)
    except httpx.RequestError as e:
        logger.error(f"Request error fetching oil prices: {e}")
        return generate_mock_oil_data(start, end)
    except httpx.TimeoutException as e:
        logger.error(f"Timeout error fetching oil prices: {e}")
        return generate_mock_oil_data(start, end)
    except Exception as e:
        logger.exception(f"Generic error fetching oil prices: {e}")
        return generate_mock_oil_data(start, end)

def generate_mock_fx_data(symbols: str) -> Dict[str, float]:
    mock_data = {symbol: 1.0 + (i * 0.1) for i, symbol in enumerate(symbols.split(","))}
    logger.info(f"Generated mock FX data: {mock_data}")
    return mock_data

async def fetch_fx_rates(base: str = "USD", symbols: str = "EUR,JPY") -> Dict[str, float]:
    if not OXR_KEY:
        logger.warning("OPENEXCHANGERATES_APP_ID not found. Using mock data.")
        return generate_mock_fx_data(symbols)
    try:
        params = {"app_id": OXR_KEY, "base": base, "symbols": symbols}
        async with httpx.AsyncClient(timeout=30.0) as client:
            logger.info(f"Requesting FX API with params: {params}")
            r = await client.get(OXR_API, params=params)
            r.raise_for_status()
        
        response_json = r.json()
        if "rates" not in response_json:
            logger.error(f"FX API response format unexpected, missing 'rates': {response_json}")
            return generate_mock_fx_data(symbols)
        logger.info(f"FX API returned rates for {len(response_json['rates'])} currencies")
        return response_json["rates"]
            
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error fetching FX rates: {e.response.status_code} - {e.response.text}")
        return generate_mock_fx_data(symbols)
    except httpx.RequestError as e:
        logger.error(f"Request error fetching FX rates: {e}")
        return generate_mock_fx_data(symbols)
    except httpx.TimeoutException as e:
        logger.error(f"Timeout error fetching FX rates: {e}")
        return generate_mock_fx_data(symbols)
    except Exception as e:
        logger.exception(f"Generic error fetching FX rates: {e}")
        return generate_mock_fx_data(symbols)