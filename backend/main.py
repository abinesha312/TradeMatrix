"""
MiView-Lite API - FastAPI backend
Provides data and LLM endpoints
"""
import os
import sys
import datetime
from pathlib import Path

# Add backend directory to Python path to fix imports
current_dir = Path(__file__).parent.absolute()
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

# Wrap imports in try-except to handle potential reload errors
try:
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from dotenv import load_dotenv
    from services.data import fetch_oil_prices, fetch_fx_rates
    from services.mcp_tools import MCP_TOOLS
    from pydantic import BaseModel
except Exception as e:
    print(f"Error importing modules: {e}")
    # Re-raise to ensure FastAPI knows there's a problem
    raise

# Load environment variables
load_dotenv()

# Create FastAPI app
app = FastAPI(title="MiView‑Lite API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AskRequest(BaseModel):
    question: str

@app.get("/")
async def root():
    return {"message": "Welcome to MiView-Lite API", "status": "online"}

@app.get("/api/oil")
async def oil(start: str, end: str):
    """Get oil price data for a date range"""
    try:
        data = await fetch_oil_prices(start, end)
        return data
    except Exception as e:
        print(f"Error in /api/oil endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/fx")
async def fx(base: str = "USD", symbols: str = "EUR,JPY"):
    """Get forex rates for specified currencies"""
    try:
        data = await fetch_fx_rates(base, symbols)
        return data
    except Exception as e:
        print(f"Error in /api/fx endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/ask")
async def ask(request: AskRequest):
    """Ask a question to the LLM via OpenRouter, with oil price data included"""
    try:
        # Use the enhanced process_market_query function for better results
        response = await MCP_TOOLS["process_market_query"](request.question)
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/oil_price")
async def oil_price(date: str):
    """Get oil price for a specific date"""
    try:
        data = await MCP_TOOLS["get_oil_price"](date)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/fx_rate")
async def fx_rate(symbol: str):
    """Get forex rate for a specific currency pair"""
    try:
        data = await MCP_TOOLS["get_fx_rate"](symbol)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/fuel_price")
async def fuel_price(country: str):
    """Get retail fuel price for a specific country"""
    try:
        # Fetch recent oil price data
        end_date = datetime.date.today()
        start_date = end_date - datetime.timedelta(days=1)  # Just get most recent data
        oil_data = await fetch_oil_prices(str(start_date), str(end_date))
        
        if not oil_data or len(oil_data) == 0:
            raise HTTPException(status_code=404, detail="No recent oil price data available")
        
        # Get the latest price
        latest_price_usd = oil_data[-1]["value"]
        
        # Ensure numeric value
        if isinstance(latest_price_usd, str):
            try:
                latest_price_usd = float(latest_price_usd)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid oil price data")
        
        # Import country data from MCP tools (available through circular import reference)
        from services.mcp_tools import COUNTRY_FUEL_DATA
        
        # Normalize country name
        country_lower = country.lower()
        if country_lower not in COUNTRY_FUEL_DATA:
            raise HTTPException(status_code=404, detail=f"Country {country} not supported")
        
        country_data = COUNTRY_FUEL_DATA[country_lower]
        
        # Get currency conversion if needed
        fx_rate = 1.0
        if country_data["currency"] != "USD":
            fx_data = await fetch_fx_rates(symbols=country_data["currency"])
            if country_data["currency"] in fx_data:
                fx_rate = fx_data[country_data["currency"]]
        
        # Calculate retail price
        price_local = (latest_price_usd * country_data["price_factor"]) / country_data["crude_conversion"]
        price_local *= 1 + country_data["tax_rate"] / 100
        price_local *= 1 + country_data["vat"] / 100
        price_local *= fx_rate
        
        # Format result
        result = {
            "country": country_data["local_name"],
            "price": round(price_local, 2),
            "unit": country_data["price_unit"],
            "currency": country_data["currency"],
            "fuel_types": country_data["common_fuels"],
            "primary_fuel": country_data["common_fuels"][0] if country_data["common_fuels"] else "Fuel",
            "tax_rate": country_data["tax_rate"],
            "vat": country_data["vat"],
            "brent_price_usd": latest_price_usd,
            "fx_rate": fx_rate,
            "date": oil_data[-1]["date"]
        }
        
        return result
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))