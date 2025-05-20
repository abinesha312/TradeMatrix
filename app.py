# Import the fix_imports module first to fix Python path
import fix_imports

# Then import other modules
import chainlit as cl
import plotly.graph_objs as go
import datetime
import os
import sys
import random
import logging
import json
import re
import asyncio
import statistics
from typing import Dict, List, Any, Optional, Tuple
import httpx

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Add the current directory to the Python path so imports work correctly
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Now we can import from the backend directory
from backend.services.data import fetch_oil_prices, fetch_fx_rates
from backend.services.mcp_tools import ask_llm

# API configuration - would normally be in environment variables or config file
API_KEYS = {
    "eia": os.getenv("EIA_API_KEY", ""),  # Energy Information Administration
    "openexchange": os.getenv("OPENEXCHANGERATES_APP_ID", ""),  # Currency exchange rates
    "weather": os.getenv("OPENWEATHER_API_KEY", "")  # Weather data
}

API_ENDPOINTS = {
    "oil_price": "https://api.eia.gov/v2/petroleum/pri/spt/data/",
    "fx_rates": "https://openexchangerates.org/api/latest.json",
    "weather": "https://api.openweathermap.org/data/2.5/weather",
    "fuel_prices": "https://api.example.com/fuel-prices"  # Placeholder for country-specific fuel prices
}

# Country-specific fuel tax and price information (for more accurate location-based responses)
COUNTRY_FUEL_DATA = {
    "germany": {
        "tax_rate": 65.45,  # Percentage of retail price that is tax
        "vat": 19.0,        # VAT percentage
        "currency": "EUR",
        "local_name": "Germany",
        "common_fuels": ["Diesel", "Super E10", "Super E5", "Super Plus"],
        "price_factor": 1.15,  # Multiplier on crude oil price to estimate local retail price before tax
        "price_unit": "€/liter",
        "crude_conversion": 159,  # Liters per barrel
        "notes": "Germany has among the highest fuel taxes in Europe, with prices varying significantly across regions."
    },
    "usa": {
        "tax_rate": 18.4,
        "vat": 0.0,          # Federal level (states have their own sales tax)
        "currency": "USD",
        "local_name": "United States",
        "common_fuels": ["Regular Gasoline", "Premium Gasoline", "Diesel"],
        "price_factor": 1.05,
        "price_unit": "$/gallon",
        "crude_conversion": 42,  # Gallons per barrel
        "notes": "US fuel prices vary significantly by state due to different state taxes."
    },
    "uk": {
        "tax_rate": 57.95,
        "vat": 20.0,
        "currency": "GBP",
        "local_name": "United Kingdom",
        "common_fuels": ["Unleaded", "Premium Unleaded", "Diesel"],
        "price_factor": 1.1,
        "price_unit": "£/liter",
        "crude_conversion": 159,  # Liters per barrel
        "notes": "UK fuel prices include fuel duty and VAT."
    },
    # Add more countries as needed
}

# Intent recognition patterns
INTENT_PATTERNS = {
    "oil_price": [
        r"oil\s+pric(?:e|es|ing)",
        r"crude\s+oil",
        r"brent",
        r"petroleum\s+pric(?:e|es|ing)",
        r"fuel\s+pric(?:e|es|ing)",
        r"gas\s+pric(?:e|es|ing)",
        r"petrol\s+pric(?:e|es|ing)"
    ],
    "fx_rates": [
        r"(?:fx|foreign exchange|currency)\s+rat(?:e|es)",
        r"exchange\s+rat(?:e|es)",
        r"currency\s+conversion"
    ],
    "weather": [
        r"weather(?:\s+forecast)?",
        r"temperature",
        r"(?:rain|snow|precipitation)",
        r"forecast"
    ]
}

# Parameter extraction patterns
PARAMETER_PATTERNS = {
    "date_range": r"(?:from|between)\s+(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4})\s+(?:to|and|until|-)\s+(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4})",
    "single_date": r"(?:on|at|for)\s+(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})",
    "days_ago": r"(\d+)\s+days?\s+ago",
    "timeframe": r"(?:last|past)\s+(\d+)\s+(days?|weeks?|months?|years?)",
    "location": r"(?:in|at|for|of)\s+([A-Za-z][a-z]+(?:\s+[A-Za-z][a-z]+)*)"  # Improved to capture country names better
}

class QueryProcessor:
    """Process user queries to extract intent and parameters."""
    
    def analyze_query(self, query: str) -> Dict[str, Any]:
        """
        Extract intent and parameters from a user query
        
        Args:
            query: The user's query text
            
        Returns:
            A dictionary with the identified intent and parameters
        """
        intent = self._identify_intent(query)
        parameters = self._extract_parameters(query)
        
        # Process date parameters to standard format
        if "date_range" in parameters:
            start_date, end_date = parameters["date_range"]
            parameters["start_date"] = self._normalize_date(start_date)
            
            # For month-year end dates, use the last day of the month
            end_date_normalized = self._normalize_date(end_date)
            if end_date_normalized.endswith("-01") and re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}', end_date, re.IGNORECASE):
                # Extract year and month
                year, month = end_date_normalized.split("-")[:2]
                
                # Import calendar to find the last day of the month
                import calendar
                last_day = calendar.monthrange(int(year), int(month))[1]
                end_date_normalized = f"{year}-{month}-{last_day:02d}"
                
            parameters["end_date"] = end_date_normalized
            del parameters["date_range"]
        elif "single_date" in parameters:
            date = parameters["single_date"]
            parameters["date"] = self._normalize_date(date)
            del parameters["single_date"]
        elif "days_ago" in parameters:
            days = int(parameters["days_ago"])
            end_date = datetime.date.today()
            start_date = end_date - datetime.timedelta(days=days)
            parameters["start_date"] = start_date.isoformat()
            parameters["end_date"] = end_date.isoformat()
            del parameters["days_ago"]
        elif "timeframe" in parameters:
            count, unit = parameters["timeframe"]
            count = int(count)
            end_date = datetime.date.today()
            
            if "day" in unit:
                delta = datetime.timedelta(days=count)
            elif "week" in unit:
                delta = datetime.timedelta(weeks=count)
            elif "month" in unit:
                # Approximate months as 30 days
                delta = datetime.timedelta(days=count*30)
            elif "year" in unit:
                # Approximate years as 365 days
                delta = datetime.timedelta(days=count*365)
                
            start_date = end_date - delta
            parameters["start_date"] = start_date.isoformat()
            parameters["end_date"] = end_date.isoformat()
            del parameters["timeframe"]
        
        # Process location parameter to standardized format
        if "location" in parameters:
            location = parameters["location"].lower()
            # Normalize country names
            if location in ["usa", "united states", "america", "us"]:
                parameters["location"] = "usa"
            elif location in ["uk", "united kingdom", "britain", "england"]:
                parameters["location"] = "uk"
            elif location in ["germany", "deutschland"]:
                parameters["location"] = "germany"
            # Add more country normalizations as needed
        
        # If no date parameters provided, default to last 30 days
        if not any(k in parameters for k in ["start_date", "date"]):
            end_date = datetime.date.today()
            start_date = end_date - datetime.timedelta(days=30)
            parameters["start_date"] = start_date.isoformat()
            parameters["end_date"] = end_date.isoformat()
        
        return {
            "intent": intent,
            "parameters": parameters,
            "original_query": query
        }
    
    def _identify_intent(self, query: str) -> str:
        """Identify the intent of the user query"""
        query_lower = query.lower()
        
        for intent, patterns in INTENT_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, query_lower):
                    return intent
        
        # If location is mentioned but no specific intent, try to guess from context
        location_match = re.search(PARAMETER_PATTERNS["location"], query)
        if location_match:
            # If query mentions fuel, gas, or price, assume oil price intent
            if re.search(r"fuel|gas|petrol|price", query_lower):
                return "oil_price"
        
        return "unknown"
    
    def _extract_parameters(self, query: str) -> Dict[str, Any]:
        """Extract parameters from the user query"""
        parameters = {}
        
        # Extract date range
        date_range_match = re.search(PARAMETER_PATTERNS["date_range"], query)
        if date_range_match:
            parameters["date_range"] = (date_range_match.group(1), date_range_match.group(2))
        
        # Extract single date
        elif single_date_match := re.search(PARAMETER_PATTERNS["single_date"], query):
            parameters["single_date"] = single_date_match.group(1)
        
        # Extract days ago
        elif days_ago_match := re.search(PARAMETER_PATTERNS["days_ago"], query):
            parameters["days_ago"] = days_ago_match.group(1)
        
        # Extract timeframe (last X days/weeks/months)
        elif timeframe_match := re.search(PARAMETER_PATTERNS["timeframe"], query):
            parameters["timeframe"] = (timeframe_match.group(1), timeframe_match.group(2))
        
        # Extract location - search in full text to catch implicit locations too
        location_match = re.search(PARAMETER_PATTERNS["location"], query)
        if location_match:
            parameters["location"] = location_match.group(1)
        else:
            # Try to extract location even if it's not preceded by "in", "at", etc.
            for country in COUNTRY_FUEL_DATA.keys():
                # Look for country name as a standalone word
                country_pattern = r'\b' + country + r'\b'
                if re.search(country_pattern, query.lower()):
                    parameters["location"] = country
                    break
        
        return parameters
    
    def _normalize_date(self, date_str: str) -> str:
        """Convert various date formats to ISO format (YYYY-MM-DD)"""
        # Handle MM/DD/YYYY format
        if '/' in date_str:
            parts = date_str.split('/')
            if len(parts) == 3:
                month, day, year = parts
                # Handle 2-digit years
                if len(year) == 2:
                    year = f"20{year}"
                return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
                
        # Handle month name formats like "May 2024"
        month_names = {
            "jan": "01", "january": "01",
            "feb": "02", "february": "02",
            "mar": "03", "march": "03",
            "apr": "04", "april": "04",
            "may": "05",
            "jun": "06", "june": "06",
            "jul": "07", "july": "07",
            "aug": "08", "august": "08",
            "sep": "09", "september": "09",
            "oct": "10", "october": "10",
            "nov": "11", "november": "11",
            "dec": "12", "december": "12"
        }
        
        # Check for month name pattern
        month_match = re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{4})', date_str, re.IGNORECASE)
        if month_match:
            month_name = month_match.group(1).lower()
            year = month_match.group(2)
            if month_name in month_names:
                # For a month-year format, use the first day of the month for start dates
                # and last day of the month for end dates (determined by caller)
                return f"{year}-{month_names[month_name]}-01"
        
        # Already in YYYY-MM-DD format
        return date_str


class DataFetcher:
    """Fetch data from external APIs based on intent and parameters."""
    
    async def fetch_data(self, intent: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fetch data from the appropriate API based on intent and parameters
        
        Args:
            intent: The identified intent (e.g., "oil_price", "fx_rates")
            parameters: Parameters extracted from the query
            
        Returns:
            The fetched data in a structured format
        """
        try:
            if intent == "oil_price":
                return await self._fetch_oil_prices(parameters)
            elif intent == "fx_rates":
                return await self._fetch_fx_rates(parameters)
            elif intent == "weather":
                return await self._fetch_weather(parameters)
            else:
                return {"error": "Unsupported intent", "intent": intent}
        except Exception as e:
            logger.exception(f"Error fetching data for intent {intent}: {e}")
            return {"error": str(e), "intent": intent}
    
    def _compute_retail_price(self, brent_price_usd: float, country: str) -> Dict[str, float]:
        """
        Convert Brent crude price to a country-specific retail fuel price
        
        Args:
            brent_price_usd: The current Brent crude oil price in USD per barrel
            country: The country code to compute retail price for
            
        Returns:
            Dictionary with retail price information
        """
        if country not in COUNTRY_FUEL_DATA:
            return None
            
        cfg = COUNTRY_FUEL_DATA[country]
        # Convert barrel → liter or gallon
        price_local = (brent_price_usd * cfg["price_factor"]) / cfg["crude_conversion"]
        # Apply fuel duty
        price_local *= 1 + cfg["tax_rate"] / 100
        # Apply VAT
        price_local *= 1 + cfg["vat"] / 100
        return {
            "price": round(price_local, 2),
            "unit": cfg["price_unit"],
            "country": cfg["local_name"],
            "common_fuel": cfg["common_fuels"][0] if cfg["common_fuels"] else "Fuel",
            "currency": cfg["currency"]
        }
    
    async def _fetch_oil_prices(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch oil price data from EIA API"""
        api_key = API_KEYS.get("eia")
        if not api_key:
            return self._generate_mock_oil_data(parameters)
        
        start_date = parameters.get("start_date", datetime.date.today().isoformat())
        end_date = parameters.get("end_date", datetime.date.today().isoformat())
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # EIA API parameters
                params = {
                    "api_key": api_key,
                    "frequency": "daily",
                    "data[0]": "value",
                    "facets[series][]": "RBRTE",  # Brent Crude Oil series ID
                    "start": start_date,
                    "end": end_date,
                    "sort[0][column]": "period",
                    "sort[0][direction]": "asc",
                }
                
                response = await client.get(API_ENDPOINTS["oil_price"], params=params)
                response.raise_for_status()
                
                data = response.json()
                
                # Process the API response
                if "response" in data and "data" in data["response"]:
                    api_data = data["response"]["data"]
                    transformed_data = []
                    
                    for item in api_data:
                        if "period" in item and "value" in item:
                            transformed_data.append({
                                "date": item["period"],
                                "value": float(item["value"])
                            })
                    
                    # Calculate statistics
                    stats = self._calculate_statistics(transformed_data)
                    
                    # If location parameter exists, calculate local retail price
                    if "location" in parameters and parameters["location"] in COUNTRY_FUEL_DATA:
                        country = parameters["location"]
                        
                        # Get latest oil price in USD
                        latest_usd = transformed_data[-1]["value"]
                        
                        # Get currency conversion if needed
                        target_currency = COUNTRY_FUEL_DATA[country]["currency"]
                        usd_to_local = 1.0  # Default to 1.0 if USD or no FX data
                        
                        if target_currency != "USD":
                            # Try to get current exchange rate
                            try:
                                fx_data = await self._fetch_fx_rates({"currencies": target_currency})
                                if "rates" in fx_data and target_currency in fx_data["rates"]:
                                    usd_to_local = fx_data["rates"][target_currency]
                            except Exception as e:
                                logger.error(f"Failed to get exchange rates for {target_currency}: {e}")
                        
                        # Calculate retail price
                        retail = self._compute_retail_price(latest_usd, country)
                        if retail:
                            stats["retail_price"] = retail
                            stats["fx_rate"] = usd_to_local
                    
                    return {
                        "data": transformed_data,
                        "stats": stats,
                        "source": "EIA API",
                        "parameters": parameters
                    }
                else:
                    return self._generate_mock_oil_data(parameters)
                    
        except Exception as e:
            logger.error(f"Error fetching oil prices: {e}")
            return self._generate_mock_oil_data(parameters)
    
    def _generate_mock_oil_data(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Generate mock oil price data"""
        import random
        
        start_date = datetime.date.fromisoformat(parameters.get("start_date", (datetime.date.today() - datetime.timedelta(days=30)).isoformat()))
        end_date = datetime.date.fromisoformat(parameters.get("end_date", datetime.date.today().isoformat()))
        
        delta = end_date - start_date
        days = delta.days + 1  # Include end date
        
        data = []
        for i in range(days):
            current_date = start_date + datetime.timedelta(days=i)
            # Generate a somewhat realistic oil price
            base_price = 80.0
            price = base_price + (i % 10) * 0.1 + random.uniform(-0.5, 0.5)
            data.append({
                "date": current_date.isoformat(),
                "value": round(price, 2)
            })
        
        stats = self._calculate_statistics(data)
        
        # If location parameter exists, calculate local retail price for mock data as well
        if "location" in parameters and parameters["location"] in COUNTRY_FUEL_DATA:
            country = parameters["location"]
            
            # Get latest oil price in USD
            latest_usd = data[-1]["value"]
            
            # For mock data, use fixed exchange rates
            usd_to_local = 1.0
            if COUNTRY_FUEL_DATA[country]["currency"] == "EUR":
                usd_to_local = 0.92
            elif COUNTRY_FUEL_DATA[country]["currency"] == "GBP":
                usd_to_local = 0.79
            
            # Calculate retail price
            retail = self._compute_retail_price(latest_usd, country)
            if retail:
                stats["retail_price"] = retail
                stats["fx_rate"] = usd_to_local
        
        return {
            "data": data,
            "stats": stats,
            "source": "Mock data",
            "parameters": parameters
        }
    
    async def _fetch_fx_rates(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch foreign exchange rates"""
        api_key = API_KEYS.get("openexchange")
        if not api_key:
            return self._generate_mock_fx_data(parameters)
        
        symbols = parameters.get("currencies", "EUR,USD,GBP,JPY,CAD")
        base = parameters.get("base_currency", "USD")
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                params = {
                    "app_id": api_key,
                    "base": base,
                    "symbols": symbols
                }
                
                response = await client.get(API_ENDPOINTS["fx_rates"], params=params)
                response.raise_for_status()
                
                data = response.json()
                
                if "rates" in data:
                    return {
                        "rates": data["rates"],
                        "base": data.get("base", base),
                        "timestamp": data.get("timestamp"),
                        "source": "Open Exchange Rates API"
                    }
                else:
                    return self._generate_mock_fx_data(parameters)
                    
        except Exception as e:
            logger.error(f"Error fetching FX rates: {e}")
            return self._generate_mock_fx_data(parameters)
    
    def _generate_mock_fx_data(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Generate mock foreign exchange rate data"""
        symbols = parameters.get("currencies", "EUR,USD,GBP,JPY,CAD").split(",")
        base = parameters.get("base_currency", "USD")
        
        rates = {}
        for i, symbol in enumerate(symbols):
            if symbol != base:
                rates[symbol] = 1.0 + (i * 0.1)  # Mock rate values
        
        return {
            "rates": rates,
            "base": base,
            "timestamp": int(datetime.datetime.now().timestamp()),
            "source": "Mock data"
        }
    
    async def _fetch_weather(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch weather data for a location"""
        api_key = API_KEYS.get("weather")
        if not api_key:
            return self._generate_mock_weather_data(parameters)
        
        location = parameters.get("location", "New York")
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                params = {
                    "q": location,
                    "appid": api_key,
                    "units": "metric"
                }
                
                response = await client.get(API_ENDPOINTS["weather"], params=params)
                response.raise_for_status()
                
                data = response.json()
                
                return {
                    "location": data.get("name", location),
                    "country": data.get("sys", {}).get("country"),
                    "temperature": data.get("main", {}).get("temp"),
                    "feels_like": data.get("main", {}).get("feels_like"),
                    "humidity": data.get("main", {}).get("humidity"),
                    "description": data.get("weather", [{}])[0].get("description"),
                    "timestamp": data.get("dt"),
                    "source": "OpenWeatherMap API"
                }
                    
        except Exception as e:
            logger.error(f"Error fetching weather data: {e}")
            return self._generate_mock_weather_data(parameters)
    
    def _generate_mock_weather_data(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Generate mock weather data"""
        location = parameters.get("location", "New York")
        
        return {
            "location": location,
            "country": "US",
            "temperature": 22.5,  # celsius
            "feels_like": 23.0,
            "humidity": 65,
            "description": "partly cloudy",
            "timestamp": int(datetime.datetime.now().timestamp()),
            "source": "Mock data"
        }
    
    def _calculate_statistics(self, data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate statistics from price data"""
        if not data or len(data) < 2:
            return None
        
        values = [item["value"] for item in data]
        
        first_price = values[0]
        last_price = values[-1]
        percent_change = ((last_price - first_price) / first_price) * 100
        
        stats = {
            "min": min(values),
            "max": max(values),
            "mean": statistics.mean(values),
            "median": statistics.median(values),
            "range": max(values) - min(values),
            "start_price": first_price,
            "end_price": last_price,
            "percent_change": round(percent_change, 2),
            "volatility": round(statistics.stdev(values), 2) if len(values) > 1 else 0
        }
        
        return stats


class ResponseGenerator:
    """Generate responses based on fetched data and user query."""
    
    def generate_response(self, query_analysis: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate a structured response using the fetched data
        
        Args:
            query_analysis: The analyzed query with intent and parameters
            data: The fetched data
            
        Returns:
            A structured response with text and visualization data
        """
        intent = query_analysis["intent"]
        query = query_analysis["original_query"]
        
        if "error" in data:
            return {
                "text": f"Sorry, I encountered an error: {data['error']}",
                "data": None
            }
        
        if intent == "oil_price":
            return self._generate_oil_price_response(query, data)
        elif intent == "fx_rates":
            return self._generate_fx_rate_response(query, data)
        elif intent == "weather":
            return self._generate_weather_response(query, data)
        else:
            return {
                "text": "I'm not sure how to answer that question. Could you try asking about oil prices, exchange rates, or weather?",
                "data": None
            }
    
    def _generate_oil_price_response(self, query: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Generate response for oil price queries"""
        price_data = data.get("data", [])
        stats = data.get("stats")
        source = data.get("source", "Unknown")
        parameters = data.get("parameters", {})
        
        if not price_data:
            return {
                "text": "I couldn't find any oil price data for your query.",
                "data": None
            }
        
        # Format dates for display
        start_date = price_data[0]["date"]
        end_date = price_data[-1]["date"]
        latest_price = price_data[-1]["value"]
        
        # Generate text response
        response_text = f"Based on {source} from {start_date} to {end_date}, "
        
        if stats:
            trend_description = "stable"
            if stats["percent_change"] > 5:
                trend_description = "strongly upward"
            elif stats["percent_change"] > 1:
                trend_description = "moderately upward"
            elif stats["percent_change"] < -5:
                trend_description = "strongly downward"
            elif stats["percent_change"] < -1:
                trend_description = "moderately downward"
            
            response_text += f"Brent crude oil prices have shown a {trend_description} trend of {stats['percent_change']}%. "
            response_text += f"Prices ranged from ${stats['min']} to ${stats['max']} USD per barrel. "
            response_text += f"The latest price is ${latest_price} USD/bbl (as of {end_date}). "
            
            if "volatility" in stats:
                response_text += f"Price volatility over this period was ${stats['volatility']} USD/bbl (standard deviation)."
                
            # Add retail price information if available
            if "retail_price" in stats:
                retail = stats["retail_price"]
                fx_rate = stats.get("fx_rate", 1.0)
                country = retail["country"]
                
                # Add a new paragraph with retail price information
                response_text += f"\n\n**Estimated pump price in {country}**: {retail['price']} {retail['unit']} for {retail['common_fuel']} (including taxes & VAT). "
                response_text += f"This is based on the current Brent crude price (${latest_price}/bbl), converted at a rate of {fx_rate} {retail['currency']}/USD, "
                response_text += f"with applicable fuel duties and {COUNTRY_FUEL_DATA.get(parameters.get('location', ''), {}).get('vat', 0)}% VAT."
        else:
            response_text += f"the latest Brent crude oil price is ${latest_price} USD/bbl (as of {end_date})."
        
        # Return structured response
        return {
            "text": response_text,
            "data": {
                "type": "oil_price",
                "price_data": price_data,
                "stats": stats,
                "visualization": {
                    "x_axis": [item["date"] for item in price_data],
                    "y_axis": [item["value"] for item in price_data],
                    "title": "Brent Crude Oil Prices",
                    "type": "line"
                }
            }
        }
    
    def _generate_fx_rate_response(self, query: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Generate response for FX rate queries"""
        rates = data.get("rates", {})
        base = data.get("base", "USD")
        source = data.get("source", "Unknown")
        
        if not rates:
            return {
                "text": "I couldn't find any exchange rate data for your query.",
                "data": None
            }
        
        # Format timestamp for display
        timestamp = data.get("timestamp")
        if timestamp:
            date_str = datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
        else:
            date_str = datetime.date.today().isoformat()
        
        # Generate text response
        response_text = f"Based on {source} as of {date_str}, here are the exchange rates relative to {base}:\n\n"
        
        for currency, rate in rates.items():
            response_text += f"• {currency}: {rate:.4f}\n"
        
        # Return structured response
        return {
            "text": response_text,
            "data": {
                "type": "fx_rates",
                "rates": rates,
                "base": base,
                "date": date_str,
                "visualization": {
                    "x_axis": list(rates.keys()),
                    "y_axis": list(rates.values()),
                    "title": f"Exchange Rates vs {base}",
                    "type": "bar"
                }
            }
        }
    
    def _generate_weather_response(self, query: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Generate response for weather queries"""
        location = data.get("location")
        country = data.get("country")
        temperature = data.get("temperature")
        feels_like = data.get("feels_like")
        humidity = data.get("humidity")
        description = data.get("description")
        source = data.get("source", "Unknown")
        
        if not location or temperature is None:
            return {
                "text": "I couldn't find any weather data for your query.",
                "data": None
            }
        
        # Format timestamp for display
        timestamp = data.get("timestamp")
        if timestamp:
            date_str = datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
        else:
            date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        
        # Generate text response
        response_text = f"Based on {source} as of {date_str}, the weather in {location}"
        if country:
            response_text += f", {country}"
        response_text += f" is {description} with a temperature of {temperature}°C (feels like {feels_like}°C) and {humidity}% humidity."
        
        # Return structured response
        return {
            "text": response_text,
            "data": {
                "type": "weather",
                "location": location,
                "country": country,
                "temperature": temperature,
                "feels_like": feels_like,
                "humidity": humidity,
                "description": description,
                "date": date_str
            }
        }


class DynamicDataModel:
    """Main class that orchestrates the query processing, data fetching, and response generation."""
    
    def __init__(self):
        self.query_processor = QueryProcessor()
        self.data_fetcher = DataFetcher()
        self.response_generator = ResponseGenerator()
    
    async def process_query(self, query: str) -> Dict[str, Any]:
        """
        Process a user query from start to finish
        
        Args:
            query: The user's query text
            
        Returns:
            A structured response with text and data
        """
        # 1. Analyze the query to extract intent and parameters
        query_analysis = self.query_processor.analyze_query(query)
        logger.info(f"Query analysis: {query_analysis}")
        
        # 2. Fetch data based on the intent and parameters
        data = await self.data_fetcher.fetch_data(
            query_analysis["intent"], 
            query_analysis["parameters"]
        )
        logger.info(f"Fetched data for {query_analysis['intent']}")
        
        # 3. Generate a response using the fetched data
        response = self.response_generator.generate_response(query_analysis, data)
        
        return {
            "query": query,
            "analysis": query_analysis,
            "response": response
        }


# Example usage
async def main():
    model = DynamicDataModel()
    
    # Example queries to demonstrate functionality
    test_queries = [
        "What is the current oil price?",
        "Show me oil prices for the last 30 days",
        "What were oil prices between 2023-01-01 and 2023-03-31?",
        "How have oil prices changed in the past 6 months?",
        "What are the current exchange rates for EUR, GBP, and JPY?",
        "What's the weather like in London today?"
    ]
    
    # Process each test query
    for query in test_queries:
        print(f"\n\nProcessing query: \"{query}\"")
        result = await model.process_query(query)
        print(f"Response: {result['response']['text']}")
        
        # Show data structure (would be used for visualization)
        if result['response']['data']:
            data_type = result['response']['data']['type']
            print(f"Data type: {data_type}")
            
            if 'visualization' in result['response']['data']:
                viz = result['response']['data']['visualization']
                print(f"Visualization type: {viz['type']}")
                print(f"Title: {viz['title']}")
                print(f"X-axis data points: {len(viz['x_axis'])}")


if __name__ == "__main__":
    asyncio.run(main())