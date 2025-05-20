import json
import os
import datetime
import random
import logging
import statistics
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Import backend services (using try-except to handle potential import errors)
try:
    from backend.services.data import fetch_oil_prices, fetch_fx_rates
    from backend.services.mcp_tools import process_market_query, analyze_price_data, COUNTRY_FUEL_DATA
except ImportError as e:
    logger.error(f"Failed to import backend services: {e}")
    raise

# Create FastAPI app
app = FastAPI(title="MiView OpenWebUI")

# Create templates directory (you need to create this folder)
os.makedirs("templates", exist_ok=True)
os.makedirs("static", exist_ok=True)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Setup Jinja2 templates
templates = Jinja2Templates(directory="templates")

class ChatMessage(BaseModel):
    message: str
    
class OilPriceData(BaseModel):
    date: str
    value: float

def generate_mock_oil_data(days=180) -> List[Dict[str, Any]]:
    """Generate mock oil price data if API fails"""
    end_date = datetime.date.today()
    
    data = []
    for i in range(days):
        # Go back in time
        current_date = end_date - datetime.timedelta(days=days-i-1)
        # Generate a somewhat realistic oil price between 70 and 90 with some randomness
        base_price = 80.0
        # Add a slight trend and some randomness
        price = base_price + (i/10) + random.uniform(-3, 3)
        data.append({
            "date": current_date.strftime("%Y-%m-%d"),
            "value": round(price, 2)
        })
    return data

def analyze_oil_data(oil_data: List[Dict[str, Any]]) -> Dict[str, Any]:
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

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Render the main dashboard page"""
    return templates.TemplateResponse("index.html", {"request": request, "title": "MiView Dashboard"})

@app.get("/api/dashboard-data")
async def dashboard_data():
    """Get initial dashboard data for oil prices and FX rates"""
    try:
        # Fetch last 6 months of oil prices
        end = datetime.date.today()
        start = end - datetime.timedelta(days=180)
        
        try:
            oil_data = await fetch_oil_prices(str(start), str(end))
            oil_data_source = "API data"
            
            # If the API returned empty data, use mock data
            if not oil_data:
                oil_data = generate_mock_oil_data()
                oil_data_source = "Mock data (API returned empty results)"
        except Exception as e:
            # If API fails, use mock data
            logger.error(f"API error: {e}, using mock data instead")
            oil_data = generate_mock_oil_data()
            oil_data_source = "Mock data (API error)"
            
        # Prepare data for charts
        oil_dates = [d["date"] for d in oil_data]
        oil_values = [float(d["value"]) if isinstance(d["value"], str) else d["value"] for d in oil_data]
        
        # Get statistical analysis
        analysis = analyze_oil_data(oil_data)
        trend = analysis["trend"]
        stats = analysis["stats"]
        
        # Fetch FX rates
        try:
            fx_rates = await fetch_fx_rates(symbols="EUR,JPY,GBP,CAD")
            fx_data_source = "API data"
            if not fx_rates:
                # Generate mock FX data if API returns empty
                fx_rates = {"EUR": 0.9345, "JPY": 157.23, "GBP": 0.7945, "CAD": 1.3678}
                fx_data_source = "Mock data (API returned empty results)"
        except Exception as e:
            # Generate mock FX data if API fails
            logger.error(f"API error for FX rates: {e}, using mock data instead")
            fx_rates = {"EUR": 0.9345, "JPY": 157.23, "GBP": 0.7945, "CAD": 1.3678}
            fx_data_source = "Mock data (API error)"
        
        # Return formatted data for the dashboard
        return {
            "oil_data": {
                "dates": oil_dates,
                "values": oil_values,
                "source": oil_data_source,
                "title": f"Brent Oil Prices (Last 6 Months) - {oil_data_source}",
                "trend": trend,
                "stats": stats
            },
            "fx_data": {
                "currencies": list(fx_rates.keys()),
                "rates": list(fx_rates.values()),
                "source": fx_data_source,
                "title": f"FX Rates vs USD - {fx_data_source}"
            }
        }
            
    except Exception as e:
        logger.exception(f"Error fetching dashboard data: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat")
async def chat(message: ChatMessage):
    """Handle user chat messages by forwarding to the LLM"""
    try:
        # Get response from LLM using the enhanced process_market_query function
        logger.info(f"Processing query: {message.message}")
        response = await process_market_query(message.message)
        logger.info(f"Got response type: {type(response)}")
        
        # Check if the response includes oil data
        if isinstance(response, dict) and "answer" in response and "data" in response:
            logger.info("Processing structured response with data")
            # Extract structured data from the response
            answer_text = response["answer"]
            data = response["data"]
            parameters = response.get("parameters", {})
            
            # Handle oil data if present
            if "oil_data" in data:
                oil_data = data["oil_data"]
                recent_prices = oil_data.get("recent_prices", [])
                latest_price = oil_data.get("latest_price")
                stats = oil_data.get("stats")
                
                # Format the response with oil data
                text_response = answer_text
                
                if latest_price:
                    latest_price_formatted = {
                        "date": latest_price.get("date", "N/A"),
                        "value": latest_price.get("value", "N/A")
                    }
                else:
                    latest_price_formatted = None
                    
                # Process recent prices for chart data
                if recent_prices and len(recent_prices) > 0:
                    dates = [item["date"] for item in recent_prices]
                    values = [float(item["value"]) if isinstance(item["value"], str) else item["value"] for item in recent_prices]
                    
                    # Create chart title with date range if available
                    chart_title = "Brent Crude Oil Prices"
                    date_range = None
                    
                    if parameters and "start_date" in parameters and "end_date" in parameters:
                        date_range = f"{parameters['start_date']} to {parameters['end_date']}"
                    
                    chart_data = {
                        "dates": dates,
                        "values": values,
                        "title": chart_title,
                        "date_range": date_range
                    }
                else:
                    chart_data = None
                
                # Include retail price information if available
                retail_price = None
                if stats and "retail_price" in stats:
                    retail_price = stats["retail_price"]
                
                # Return structured response
                return {
                    "text": text_response,
                    "latest_price": latest_price_formatted,
                    "chart_data": chart_data,
                    "oil_data": {
                        "recent_prices": recent_prices,
                        "stats": stats
                    },
                    "retail_price": retail_price,
                    "parameters": parameters
                }
            
            # Handle FX data if present
            elif "fx_data" in data:
                fx_data = data["fx_data"]
                
                # Process FX data for chart display
                currencies = list(fx_data.get("rates", {}).keys())
                rates = list(fx_data.get("rates", {}).values())
                
                chart_data = {
                    "currencies": currencies,
                    "rates": rates,
                    "title": "Exchange Rates vs USD"
                }
                
                return {
                    "text": answer_text,
                    "chart_data": chart_data,
                    "fx_data": fx_data,
                    "parameters": parameters
                }
                
            else:
                # Generic structured response
                return {
                    "text": answer_text,
                    "parameters": parameters
                }
                
        else:
            # Handle simple text response
            logger.info("Processing simple text response")
            if isinstance(response, dict):
                # Try to extract answer if it's a dict but doesn't have the expected structure
                content = response.get("answer", str(response))
            elif not isinstance(response, str):
                # Convert any non-string response to string
                content = str(response)
            else:
                content = response
                
            return {"text": content}
        
    except Exception as e:
        logger.exception(f"Error processing chat message: {e}")
        return {"text": f"Error: {str(e)}. Please try again."}

# Run the application if this script is executed directly
if __name__ == "__main__":
    import uvicorn
    # Configure uvicorn with limited worker lifetime to avoid hanging on reload
    uvicorn.run(
        "miview_openwebui:app", 
        host="0.0.0.0", 
        port=8000, 
        reload=True,
        reload_delay=1.0,
        workers=1,
        log_level="info"
    ) 