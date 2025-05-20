"""
MCP Tools for MiView-Lite
These tools connect to external services like OpenRouter for LLM functionality
"""
from typing import Any, Dict, List
import os
import json
import datetime
import logging
import statistics
from dotenv import load_dotenv
import httpx
from .data import fetch_oil_prices, fetch_fx_rates

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Get API key from environment with fallback
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# System prompt for more precise responses
SYSTEM_PROMPT = """You are an expert market data analyst with access to precise oil price and currency exchange information.
When responding to queries:
1. Provide specific numerical values with proper units
2. Include precise date ranges for any data referenced
3. Offer exact price points and clear trends
4. Never generalize when specific data is available
5. Include quantitative analysis where relevant (e.g., percentage changes, statistical measures)
6. Cite the source and timestamp of your data
7. When providing ranges, define the upper and lower bounds precisely
8. If country-specific fuel data is provided, use it to answer in local units (€/L, $/gal, £/L)

Always prioritize accuracy over generalization."""

# Sample responses for when API is unavailable
FALLBACK_RESPONSES = {
    "oil_price": "Based on the latest data available, oil prices have been fluctuating. The recent Brent crude oil price is shown in the chart below. The overall trend has been [upward/downward] in the past month.",
    "fx_rate": "Foreign exchange rates fluctuate based on market conditions. The chart shows the latest available rates against the USD.",
    "general": "I'm currently operating in offline mode due to API connection issues. I can still show you the latest oil prices and FX rates from our cached data."
}

# Define country data for retail price calculations
COUNTRY_FUEL_DATA = {
    "germany": {
        "tax_rate": 65.45,
        "vat": 19.0,
        "currency": "EUR",
        "local_name": "Germany",
        "common_fuels": ["Diesel", "Super E10", "Super E5", "Super Plus"],
        "price_factor": 1.15,
        "price_unit": "€/liter",
        "crude_conversion": 159,
        "notes": "Germany has among the highest fuel taxes in Europe, with prices varying significantly across regions."
    },
    "usa": {
        "tax_rate": 18.4,
        "vat": 0.0,
        "currency": "USD",
        "local_name": "United States",
        "common_fuels": ["Regular Gasoline", "Premium Gasoline", "Diesel"],
        "price_factor": 1.05,
        "price_unit": "$/gallon",
        "crude_conversion": 42,
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
        "crude_conversion": 159,
        "notes": "UK fuel prices include fuel duty and VAT."
    }
}

def analyze_price_data(oil_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Perform statistical analysis on price data for more precise responses"""
    if not oil_data or len(oil_data) < 2:
        return {"trend": "insufficient data", "stats": None}
    
    # Extract numeric values
    values = []
    for item in oil_data:
        if isinstance(item["value"], str):
            try:
                values.append(float(item["value"]))
            except ValueError:
                continue
        else:
            values.append(item["value"])
    
    if not values:
        return {"trend": "invalid data", "stats": None}
    
    # Calculate statistics
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
    
    # Determine trend
    if percent_change > 5:
        trend = "strongly upward"
    elif percent_change > 1:
        trend = "moderately upward"
    elif percent_change < -5:
        trend = "strongly downward"
    elif percent_change < -1:
        trend = "moderately downward"
    else:
        trend = "relatively stable"
    
    return {"trend": trend, "stats": stats}

async def ask_llm(question: str) -> Dict[str, Any]:
    """Send a question to OpenRouter LLM and get a response, including oil price data"""
    try:
        # Extract parameters from the question first
        parameters = {}
        
        # Simple extraction of country names from the question
        country_names = {
            "germany": ["germany", "deutschland"],
            "usa": ["usa", "united states", "america", "us"],
            "uk": ["uk", "united kingdom", "britain", "england", "london"]
        }
        
        question_lower = question.lower()
        for country, aliases in country_names.items():
            for alias in aliases:
                if alias in question_lower:
                    parameters["location"] = country
                    break
            if "location" in parameters:
                break
                
        # Extract date range information (using simplified patterns)
        date_range_pattern = r"(?:from|between)\s+((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})\s+(?:to|and|until|-)\s+((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})"
        import re
        
        # Try to extract date range
        date_range_match = re.search(date_range_pattern, question, re.IGNORECASE)
        if date_range_match:
            start_date_str = date_range_match.group(1)
            end_date_str = date_range_match.group(2)
            
            # Convert to ISO format if necessary - simplified version
            month_names = {
                "jan": "01", "january": "01", "feb": "02", "february": "02",
                "mar": "03", "march": "03", "apr": "04", "april": "04",
                "may": "05", "jun": "06", "june": "06", "jul": "07", "july": "07",
                "aug": "08", "august": "08", "sep": "09", "september": "09",
                "oct": "10", "october": "10", "nov": "11", "november": "11",
                "dec": "12", "december": "12"
            }
            
            # Process start date
            start_month_match = re.search(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{4})", start_date_str.lower())
            if start_month_match:
                month = month_names[start_month_match.group(1)]
                year = start_month_match.group(2)
                start_date = f"{year}-{month}-01"
            else:
                # Default to safe format
                start_date = datetime.date.today() - datetime.timedelta(days=30)
                start_date = start_date.isoformat()
                
            # Process end date
            end_month_match = re.search(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{4})", end_date_str.lower())
            if end_month_match:
                month = month_names[end_month_match.group(1)]
                year = end_month_match.group(2)
                
                # For month-year end dates, use the last day of the month
                import calendar
                last_day = calendar.monthrange(int(year), int(month))[1]
                end_date = f"{year}-{month}-{last_day:02d}"
            else:
                # Default to today
                end_date = datetime.date.today().isoformat()
                
            # Store the dates
            parameters["start_date"] = start_date
            parameters["end_date"] = end_date
        else:
            # Default to last 30 days if no date range found
            end_date = datetime.date.today()
            start_date = end_date - datetime.timedelta(days=30)
            parameters["start_date"] = start_date.isoformat()
            parameters["end_date"] = end_date.isoformat()
        
        # Use the extracted dates to fetch oil price data
        start_date = parameters["start_date"]
        end_date = parameters["end_date"]
        oil_data = await fetch_oil_prices(start_date, end_date)
        
        # Analyze the oil price data
        analysis = analyze_price_data(oil_data)
        trend = analysis["trend"]
        stats = analysis["stats"]
        
        # Prepare oil data context with precise information
        oil_context = f"Recent Brent crude oil prices from {start_date} to {end_date}:\n"
        if oil_data and len(oil_data) > 0:
            # Include statistical information
            if stats:
                oil_context += f"- Price range: ${stats['min']} to ${stats['max']} USD/bbl\n"
                oil_context += f"- Current price: ${stats['end_price']} USD/bbl (as of {oil_data[-1]['date']})\n"
                oil_context += f"- 30-day change: {stats['percent_change']}%\n"
                oil_context += f"- 30-day average: ${stats['mean']:.2f} USD/bbl\n"
                oil_context += f"- Volatility (std dev): ${stats['volatility']} USD/bbl\n"
            
            # Take the most recent prices
            oil_context += "\nMost recent prices:\n"
            recent_prices = oil_data[-5:]
            for entry in recent_prices:
                oil_context += f"- {entry['date']}: ${entry['value']} USD/bbl\n"
                
            # Add retail price information if location is available
            if parameters and "location" in parameters and parameters["location"] in COUNTRY_FUEL_DATA:
                country = parameters["location"]
                country_data = COUNTRY_FUEL_DATA[country]
                latest_price_usd = oil_data[-1]["value"]
                
                # Ensure the price is a float
                if isinstance(latest_price_usd, str):
                    try:
                        latest_price_usd = float(latest_price_usd)
                    except ValueError:
                        logger.error(f"Could not convert price {latest_price_usd} to float")
                        latest_price_usd = 80.0  # Default fallback price
                
                # Get currency conversion if needed
                fx_rate = 1.0
                if country_data["currency"] != "USD":
                    try:
                        fx_rates = await fetch_fx_rates(symbols=country_data["currency"])
                        if fx_rates and country_data["currency"] in fx_rates:
                            fx_rate = fx_rates[country_data["currency"]]
                    except Exception as e:
                        logger.warning(f"Could not fetch FX data for {country_data['currency']}: {e}")
                
                # Calculate local retail price
                price_local = (latest_price_usd * country_data["price_factor"]) / country_data["crude_conversion"]
                # Apply fuel duty
                price_local *= 1 + country_data["tax_rate"] / 100
                # Apply VAT
                price_local *= 1 + country_data["vat"] / 100
                # Convert to local currency
                price_local *= fx_rate
                
                oil_context += f"\nEstimated pump price in {country_data['local_name']}: "
                oil_context += f"{round(price_local, 2)} {country_data['price_unit']} for {country_data['common_fuels'][0]} (incl. tax & VAT)\n"
                oil_context += f"This includes {country_data['tax_rate']}% fuel duty and {country_data['vat']}% VAT.\n"
                if country_data["notes"]:
                    oil_context += f"Note: {country_data['notes']}\n"
        else:
            oil_context += "No recent oil price data available.\n"
        
        # Fetch FX data
        fx_data = None
        try:
            fx_rates = await fetch_fx_rates(symbols="EUR,JPY,GBP,CAD")
            if fx_rates:
                fx_data = "\nCurrent FX rates vs USD:\n"
                for currency, rate in fx_rates.items():
                    fx_data += f"- {currency}: {rate}\n"
                oil_context += fx_data
        except Exception as e:
            logger.warning(f"Could not fetch FX data: {e}")
        
        # Check if we have a valid API key before attempting a call
        if not OPENROUTER_API_KEY:
            logger.warning("No OpenRouter API key found. Using fallback response.")
            return get_fallback_response(question, oil_data, trend, stats, parameters)
        
        # Prepare enhanced prompt with precise data context
        enhanced_question = f"""{SYSTEM_PROMPT}

Here is up-to-date market data (as of {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}):

{oil_context}

User question: {question}"""
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "HTTP-Referer": "https://miview-dashboard.example.com",
            "X-Title": "MiView Dashboard"
        }
        
        payload = {
            "model": "openai/gpt-4o-mini",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": enhanced_question}
            ]
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                OPENROUTER_URL,
                headers=headers,
                json=payload,
                timeout=30.0
            )
            
            if response.status_code == 401:
                logger.error("Authentication failed for OpenRouter API. Check your API key.")
                return get_fallback_response(question, oil_data, trend, stats, parameters)
                
            response.raise_for_status()
            result = response.json()
            answer = result["choices"][0]["message"]["content"]
            
            # Return a structured response with both the answer and oil data
            return {
                "answer": answer,
                "oil_data": {
                    "recent_prices": oil_data[-5:] if oil_data and len(oil_data) >= 5 else oil_data,
                    "latest_price": oil_data[-1] if oil_data and len(oil_data) > 0 else None,
                    "stats": stats,
                    "parameters": parameters
                }
            }
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error calling OpenRouter: {e}")
        return get_fallback_response(question, oil_data, trend, stats, parameters)
    except Exception as e:
        logger.exception(f"Error calling OpenRouter: {e}")
        return get_fallback_response(question, oil_data, trend, stats, parameters)

def get_fallback_response(question: str, oil_data: list, trend: str = "stable", stats: Dict = None, parameters: Dict = None) -> Dict[str, Any]:
    """Generate a precise fallback response when the LLM API is unavailable"""
    question_lower = question.lower()
    today = datetime.date.today().strftime('%Y-%m-%d')
    
    # Build a response with available precise data
    if "oil" in question_lower or "price" in question_lower or "brent" in question_lower:
        if stats:
            response = f"Based on precise market data from the past 30 days, Brent crude oil prices have shown a {trend} trend. "
            response += f"Prices have ranged from ${stats['min']} to ${stats['max']} USD/bbl, with a 30-day volatility of ${stats['volatility']} USD/bbl. "
            response += f"The price has changed by {stats['percent_change']}% during this period."
            
            # Add retail price if location is available
            if parameters and "location" in parameters and parameters["location"] in COUNTRY_FUEL_DATA:
                country = parameters["location"]
                country_data = COUNTRY_FUEL_DATA[country]
                
                if oil_data and len(oil_data) > 0:
                    latest_price_usd = oil_data[-1]["value"]
                    
                    # Ensure the price is a float
                    if isinstance(latest_price_usd, str):
                        try:
                            latest_price_usd = float(latest_price_usd)
                        except ValueError:
                            logger.error(f"Could not convert price {latest_price_usd} to float")
                            latest_price_usd = 80.0  # Default fallback price
                    
                    # Calculate local retail price
                    fx_rate = 1.1 if country_data["currency"] == "EUR" else (0.8 if country_data["currency"] == "GBP" else 1.0)
                    price_local = (latest_price_usd * country_data["price_factor"]) / country_data["crude_conversion"]
                    price_local *= 1 + country_data["tax_rate"] / 100
                    price_local *= 1 + country_data["vat"] / 100
                    price_local *= fx_rate
                    
                    response += f"\n\nFor {country_data['local_name']}, the estimated retail price for {country_data['common_fuels'][0]} is "
                    response += f"{round(price_local, 2)} {country_data['price_unit']} (including {country_data['tax_rate']}% fuel duty and {country_data['vat']}% VAT)."
        else:
            response = FALLBACK_RESPONSES["oil_price"].replace("[upward/downward]", trend)
    elif "fx" in question_lower or "currency" in question_lower or "exchange" in question_lower:
        response = FALLBACK_RESPONSES["fx_rate"]
    else:
        if stats:
            response = f"As of {today}, I can provide precise market data based on available information. "
            response += f"Brent crude oil is trading at ${stats['end_price']} USD/bbl, which represents a {stats['percent_change']}% change over the past 30 days. "
            response += f"The 30-day price range has been ${stats['min']} to ${stats['max']} USD/bbl."
        else:
            response = FALLBACK_RESPONSES["general"]
    
    # Add more specific information if available
    if oil_data and len(oil_data) > 0:
        latest = oil_data[-1]
        response += f"\n\nThe latest available oil price is ${latest['value']} USD/bbl as of {latest['date']}."
        
        # Add source information for accuracy
        response += f"\n\nThis data is sourced from the EIA API with timestamp {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}."
    
    # Return formatted response with oil data
    return {
        "answer": response,
        "oil_data": {
            "recent_prices": oil_data[-5:] if oil_data and len(oil_data) >= 5 else oil_data,
            "latest_price": oil_data[-1] if oil_data and len(oil_data) > 0 else None,
            "stats": stats,
            "parameters": parameters
        }
    }

async def get_oil_price(date: str) -> Dict[str, Any]:
    """Get oil price for a specific date"""
    data = await fetch_oil_prices(date, date)
    return data[0] if data else {"date": date, "value": None}

async def get_fx_rate(symbol: str) -> Dict[str, float]:
    """Get FX rate for a specific currency vs USD"""
    rates = await fetch_fx_rates(symbols=symbol)
    return {symbol: rates.get(symbol)}

async def parse_query_with_llm(question: str) -> Dict[str, Any]:
    """Use LLM to parse and extract structured parameters from user query"""
    try:
        # Define the system prompt for parameter extraction
        extraction_prompt = """You are a specialized query parser for a financial data system.
Your task is to extract precise parameters from user queries about oil prices and market data.
Return a JSON object with the following structure:
{
  "intent": "oil_price" | "fx_rates" | "weather" | "unknown",
  "date_range": {
    "start_date": "YYYY-MM-DD",  // Convert any date format to ISO
    "end_date": "YYYY-MM-DD"     // For month references like "May 2024", use the last day of that month
  },
  "location": {  // Normalize country names
    "country_code": "germany" | "usa" | "uk",
    "original_text": "the extracted location text",
    "is_explicit": true | false  // Whether location was explicitly mentioned
  },
  "currency": "USD" | "EUR" | "GBP",  // Currency of interest if mentioned
  "other_parameters": {
    // Any other relevant parameters detected
  },
  "query_type": "historical" | "current" | "forecast",
  "refined_question": "A clear, direct version of the user's query"
}

If a parameter is not present, omit it from the JSON rather than using null values.
Be precise with date parsing - use YYYY-MM-DD format and handle month names correctly.
For date ranges with just month and year (e.g., "May 2024"), use the first day for start dates and last day for end dates.
"""

        if not OPENROUTER_API_KEY:
            logger.warning("No OpenRouter API key found. Using fallback parsing.")
            return parse_query_fallback(question)
        
        # Prepare payload for the LLM
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "HTTP-Referer": "https://miview-dashboard.example.com",
            "X-Title": "MiView Dashboard"
        }
        
        payload = {
            "model": "openai/gpt-4o-mini",
            "messages": [
                {"role": "system", "content": extraction_prompt},
                {"role": "user", "content": f"Parse this query: {question}"}
            ],
            "response_format": {"type": "json_object"}
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                OPENROUTER_URL,
                headers=headers,
                json=payload,
                timeout=30.0
            )
            
            if response.status_code == 401:
                logger.error("Authentication failed for OpenRouter API. Using fallback parsing.")
                return parse_query_fallback(question)
                
            response.raise_for_status()
            result = response.json()
            extracted_json = result["choices"][0]["message"]["content"]
            
            try:
                # Parse the JSON response
                import json
                parameters = json.loads(extracted_json)
                
                # Process the extracted parameters
                processed_params = {}
                
                # Set intent
                processed_params["intent"] = parameters.get("intent", "oil_price")
                
                # Process date range
                if "date_range" in parameters:
                    date_range = parameters["date_range"]
                    processed_params["start_date"] = date_range.get("start_date")
                    processed_params["end_date"] = date_range.get("end_date")
                else:
                    # Default to last 30 days
                    end_date = datetime.date.today()
                    start_date = end_date - datetime.timedelta(days=30)
                    processed_params["start_date"] = start_date.isoformat()
                    processed_params["end_date"] = end_date.isoformat()
                
                # Process location
                if "location" in parameters and "country_code" in parameters["location"]:
                    processed_params["location"] = parameters["location"]["country_code"].lower()
                
                # Add any additional parameters
                if "currency" in parameters:
                    processed_params["currency"] = parameters["currency"]
                
                if "other_parameters" in parameters:
                    for key, value in parameters["other_parameters"].items():
                        processed_params[key] = value
                
                # Add the refined question
                processed_params["refined_question"] = parameters.get("refined_question", question)
                
                # Add original query for reference
                processed_params["original_query"] = question
                
                return processed_params
                
            except json.JSONDecodeError:
                logger.error(f"Failed to parse JSON from LLM: {extracted_json}")
                return parse_query_fallback(question)
                
    except Exception as e:
        logger.exception(f"Error in parse_query_with_llm: {e}")
        return parse_query_fallback(question)

def parse_query_fallback(question: str) -> Dict[str, Any]:
    """Fallback query parser using regex patterns when LLM is unavailable"""
    parameters = {}
    question_lower = question.lower()
    
    # Extract intent
    if any(term in question_lower for term in ["oil", "crude", "price", "brent", "fuel", "gas", "petrol"]):
        parameters["intent"] = "oil_price"
    elif any(term in question_lower for term in ["fx", "exchange", "currency", "rate"]):
        parameters["intent"] = "fx_rates"
    elif any(term in question_lower for term in ["weather", "temperature", "rain", "forecast"]):
        parameters["intent"] = "weather"
    else:
        parameters["intent"] = "oil_price"  # Default intent
    
    # Extract location using simple pattern matching
    country_names = {
        "germany": ["germany", "deutschland"],
        "usa": ["usa", "united states", "america", "us"],
        "uk": ["uk", "united kingdom", "britain", "england", "london"]
    }
    
    for country, aliases in country_names.items():
        for alias in aliases:
            if alias in question_lower:
                parameters["location"] = country
                break
        if "location" in parameters:
            break
            
    # Extract date range using regex
    date_range_pattern = r"(?:from|between)\s+((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})\s+(?:to|and|until|-)\s+((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})"
    import re
    
    # Try to extract date range
    date_range_match = re.search(date_range_pattern, question, re.IGNORECASE)
    if date_range_match:
        start_date_str = date_range_match.group(1)
        end_date_str = date_range_match.group(2)
        
        # Convert to ISO format
        month_names = {
            "jan": "01", "january": "01", "feb": "02", "february": "02",
            "mar": "03", "march": "03", "apr": "04", "april": "04",
            "may": "05", "jun": "06", "june": "06", "jul": "07", "july": "07",
            "aug": "08", "august": "08", "sep": "09", "september": "09",
            "oct": "10", "october": "10", "nov": "11", "november": "11",
            "dec": "12", "december": "12"
        }
        
        # Process start date
        start_month_match = re.search(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{4})", start_date_str.lower())
        if start_month_match:
            month = month_names[start_month_match.group(1)]
            year = start_month_match.group(2)
            start_date = f"{year}-{month}-01"
        else:
            # Default to safe format
            start_date = datetime.date.today() - datetime.timedelta(days=30)
            start_date = start_date.isoformat()
            
        # Process end date
        end_month_match = re.search(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{4})", end_date_str.lower())
        if end_month_match:
            month = month_names[end_month_match.group(1)]
            year = end_month_match.group(2)
            
            # For month-year end dates, use the last day of the month
            import calendar
            last_day = calendar.monthrange(int(year), int(month))[1]
            end_date = f"{year}-{month}-{last_day:02d}"
        else:
            # Default to today
            end_date = datetime.date.today().isoformat()
            
        # Store the dates
        parameters["start_date"] = start_date
        parameters["end_date"] = end_date
    else:
        # Default to last 30 days if no date range found
        end_date = datetime.date.today()
        start_date = end_date - datetime.timedelta(days=30)
        parameters["start_date"] = start_date.isoformat()
        parameters["end_date"] = end_date.isoformat()
    
    # Add refined question (same as original in fallback)
    parameters["refined_question"] = question
    parameters["original_query"] = question
    
    return parameters

async def generate_polished_response(data: Dict[str, Any], parameters: Dict[str, Any]) -> str:
    """Generate a polished response using LLM with the fetched data and parameters"""
    try:
        # Create context for the LLM
        context = "Data Summary:\n"
        
        # Add oil price data if available
        if "oil_data" in data:
            oil_data = data["oil_data"]
            stats = oil_data.get("stats")
            
            if stats:
                context += f"- Brent Crude Price Range: ${stats.get('min', 'N/A')} to ${stats.get('max', 'N/A')} USD/bbl\n"
                context += f"- Latest Price: ${stats.get('end_price', 'N/A')} USD/bbl\n"
                context += f"- Price Change: {stats.get('percent_change', 'N/A')}%\n"
                context += f"- Volatility: ${stats.get('volatility', 'N/A')} USD/bbl\n"
                
                # Add retail price if available
                if "retail_price" in stats:
                    retail = stats["retail_price"]
                    context += f"- Local Retail Price ({retail.get('country', 'N/A')}): {retail.get('price', 'N/A')} {retail.get('unit', '')}\n"
                    context += f"- Common Fuel Type: {retail.get('common_fuel', 'N/A')}\n"
                    
            # Add price data dates
            latest_price = oil_data.get("latest_price", {})
            if latest_price:
                context += f"- Latest Data Date: {latest_price.get('date', 'N/A')}\n"
                
            # Add date range
            context += f"- Date Range: {parameters.get('start_date', 'N/A')} to {parameters.get('end_date', 'N/A')}\n"
            
        # Add FX data if available
        if "fx_data" in data:
            fx_data = data["fx_data"]
            context += "\nFX Rates:\n"
            for currency, rate in fx_data.get("rates", {}).items():
                context += f"- {currency}: {rate}\n"
                
        # Create system prompt for response generation
        response_prompt = """You are an expert market analyst providing concise, data-driven responses about oil prices and currency markets.
Your responses should be:
1. Clear and direct, focused on the data
2. Include specific numbers with proper units
3. Highlight significant trends or changes
4. Include local retail prices when available
5. Mention the date range of the data
6. Cite data sources
7. Use a professional, analytical tone

Your response should be a single, well-structured paragraph unless the complexity requires multiple paragraphs.
When mentioning retail fuel prices, explicitly note they include taxes and VAT.
"""

        # Check for API key
        if not OPENROUTER_API_KEY:
            logger.warning("No OpenRouter API key found. Using template response.")
            return format_fallback_response(data, parameters)
        
        # Prepare the question for the LLM
        refined_question = parameters.get("refined_question", parameters.get("original_query", "Tell me about oil prices"))
        
        user_prompt = f"""Based on the following data, answer this question:
"{refined_question}"

{context}

Current timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

        # Prepare LLM request
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "HTTP-Referer": "https://miview-dashboard.example.com",
            "X-Title": "MiView Dashboard"
        }
        
        payload = {
            "model": "openai/gpt-4o-mini",
            "messages": [
                {"role": "system", "content": response_prompt},
                {"role": "user", "content": user_prompt}
            ]
        }
        
        # Call the LLM
        async with httpx.AsyncClient() as client:
            response = await client.post(
                OPENROUTER_URL,
                headers=headers,
                json=payload,
                timeout=30.0
            )
            
            if response.status_code == 401:
                logger.error("Authentication failed for OpenRouter API. Using template response.")
                return format_fallback_response(data, parameters)
                
            response.raise_for_status()
            result = response.json()
            answer = result["choices"][0]["message"]["content"]
            
            return answer
            
    except Exception as e:
        logger.exception(f"Error generating polished response: {e}")
        return format_fallback_response(data, parameters)

def format_fallback_response(data: Dict[str, Any], parameters: Dict[str, Any]) -> str:
    """Format a fallback response when LLM is unavailable"""
    try:
        # Get basic data
        oil_data = data.get("oil_data", {})
        stats = oil_data.get("stats", {})
        latest_price = oil_data.get("latest_price", {})
        
        if not stats or not latest_price:
            return "Sorry, I couldn't find any market data for your query. Please try again later."
        
        # Basic information
        start_date = parameters.get("start_date", "N/A")
        end_date = parameters.get("end_date", "N/A")
        latest_date = latest_price.get("date", "N/A")
        latest_value = latest_price.get("value", "N/A")
        
        # Format the response
        response = f"Based on data from {start_date} to {end_date}, "
        
        # Add trend information
        trend = "stable"
        if stats.get("percent_change", 0) > 5:
            trend = "strongly upward"
        elif stats.get("percent_change", 0) > 1:
            trend = "moderately upward"
        elif stats.get("percent_change", 0) < -5:
            trend = "strongly downward"
        elif stats.get("percent_change", 0) < -1:
            trend = "moderately downward"
            
        response += f"Brent crude oil prices have shown a {trend} trend. "
        response += f"Prices ranged from ${stats.get('min', 'N/A')} to ${stats.get('max', 'N/A')} USD/bbl, "
        response += f"with a 30-day volatility of ${stats.get('volatility', 'N/A')} USD/bbl. "
        response += f"The price has changed by {stats.get('percent_change', 'N/A')}% during this period. "
        
        # Add retail price if available
        if "retail_price" in stats:
            retail = stats["retail_price"]
            response += f"\n\nFor {retail.get('country', 'N/A')}, the estimated retail price for {retail.get('common_fuel', 'fuel')} is "
            response += f"{retail.get('price', 'N/A')} {retail.get('unit', '')} (including taxes and VAT). "
        
        # Add latest price
        response += f"\n\nThe latest available oil price is ${latest_value} USD/bbl as of {latest_date}. "
        
        # Add data source
        response += f"\n\nThis data is sourced from market APIs with timestamp {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}."
        
        return response
        
    except Exception as e:
        logger.exception(f"Error formatting fallback response: {e}")
        return "Sorry, I couldn't process your query due to a system error. Please try again later."

async def process_market_query(question: str) -> Dict[str, Any]:
    """Process a query about market data with LLM-enhanced parsing and response generation"""
    try:
        # Step 1: Parse the query using LLM to extract structured parameters
        parameters = await parse_query_with_llm(question)
        logger.info(f"Extracted parameters: {parameters}")
        
        # Step 2: Fetch data based on the extracted parameters
        data = {}
        
        # Fetch oil price data if needed
        if parameters.get("intent") in ["oil_price", "unknown"]:
            start_date = parameters.get("start_date")
            end_date = parameters.get("end_date")
            oil_data = await fetch_oil_prices(start_date, end_date)
            
            # Analyze the data
            analysis = analyze_price_data(oil_data)
            trend = analysis["trend"]
            stats = analysis["stats"]
            
            # Add location-specific retail price if available
            if "location" in parameters and parameters["location"] in COUNTRY_FUEL_DATA:
                country = parameters["location"]
                country_data = COUNTRY_FUEL_DATA[country]
                
                if oil_data and len(oil_data) > 0:
                    latest_price_usd = oil_data[-1]["value"]
                    
                    # Ensure the price is a float
                    if isinstance(latest_price_usd, str):
                        try:
                            latest_price_usd = float(latest_price_usd)
                        except ValueError:
                            logger.error(f"Could not convert price {latest_price_usd} to float")
                            latest_price_usd = 80.0
                    
                    # Get currency conversion
                    fx_rate = 1.0
                    if country_data["currency"] != "USD":
                        try:
                            fx_rates = await fetch_fx_rates(symbols=country_data["currency"])
                            if fx_rates and country_data["currency"] in fx_rates:
                                fx_rate = fx_rates[country_data["currency"]]
                        except Exception as e:
                            logger.warning(f"Could not fetch FX data for {country_data['currency']}: {e}")
                            # Use fallback rates
                            fx_rate = 1.1 if country_data["currency"] == "EUR" else (0.8 if country_data["currency"] == "GBP" else 1.0)
                    
                    # Calculate retail price
                    price_local = (latest_price_usd * country_data["price_factor"]) / country_data["crude_conversion"]
                    price_local *= 1 + country_data["tax_rate"] / 100
                    price_local *= 1 + country_data["vat"] / 100
                    price_local *= fx_rate
                    
                    # Store retail price information
                    stats["retail_price"] = {
                        "price": round(price_local, 2),
                        "unit": country_data["price_unit"],
                        "country": country_data["local_name"],
                        "common_fuel": country_data["common_fuels"][0] if country_data["common_fuels"] else "Fuel",
                        "currency": country_data["currency"],
                        "tax_rate": country_data["tax_rate"],
                        "vat": country_data["vat"]
                    }
                    stats["fx_rate"] = fx_rate
            
            # Store the oil data
            data["oil_data"] = {
                "recent_prices": oil_data[-5:] if oil_data and len(oil_data) >= 5 else oil_data,
                "latest_price": oil_data[-1] if oil_data and len(oil_data) > 0 else None,
                "stats": stats
            }
        
        # Fetch FX data if needed
        if parameters.get("intent") == "fx_rates":
            currency = parameters.get("currency", "EUR")
            fx_rates = await fetch_fx_rates(symbols=f"{currency},USD,GBP,JPY,CAD")
            
            data["fx_data"] = {
                "rates": fx_rates,
                "base": "USD",
                "timestamp": int(datetime.datetime.now().timestamp())
            }
        
        # Step 3: Generate a polished response using the data and parameters
        polished_answer = await generate_polished_response(data, parameters)
        
        # Return the complete result
        return {
            "answer": polished_answer,
            "data": data,
            "parameters": parameters
        }
        
    except Exception as e:
        logger.exception(f"Error in process_market_query: {e}")
        return {
            "answer": f"Sorry, I encountered an error while processing your query: {str(e)}",
            "data": {},
            "parameters": {"original_query": question}
        }

# Export tools for FastAPI to use
MCP_TOOLS = {
    "get_oil_price": get_oil_price,
    "get_fx_rate": get_fx_rate,
    "ask_llm": ask_llm,
    "parse_query_with_llm": parse_query_with_llm,
    "process_market_query": process_market_query,
}