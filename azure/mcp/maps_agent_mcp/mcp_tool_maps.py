import os
import logging
import requests
from dotenv import load_dotenv
from fastmcp import FastMCP
import uvicorn

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [MAPS_MCP_SERVER] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

logger.info("Initializing FastMCP server...")
mcp = FastMCP("Maps Agent MCP Server")
logger.info("FastMCP server initialized")


@mcp.tool()
def get_directions(origin: str, destination: str) -> dict:
    """Get driving directions from origin to destination."""
    logger.info(f"Tool invoked: get_directions from {origin} to {destination}")
    resp = requests.get("https://maps.googleapis.com/maps/api/directions/json",
        params={"origin": origin, "destination": destination, "mode": "driving", "key": GOOGLE_MAPS_API_KEY}).json()
    if resp.get("status") != "OK":
        return {"error": f"Directions API error: {resp.get('status')}"}
    steps = resp["routes"][0]["legs"][0]["steps"]
    directions = "\n".join([s["html_instructions"].replace("<b>", "").replace("</b>", "") for s in steps])
    return {"result": directions}


@mcp.tool()
def search_nearby(location: str, keyword: str) -> dict:
    """Search for nearby places by keyword around a location."""
    logger.info(f"Tool invoked: search_nearby at {location} for {keyword}")
    geo = requests.get("https://maps.googleapis.com/maps/api/geocode/json",
        params={"address": location, "key": GOOGLE_MAPS_API_KEY}).json()
    if geo.get("status") != "OK":
        return {"error": f"Geocoding error: {geo.get('status')}"}
    loc = geo["results"][0]["geometry"]["location"]
    resp = requests.get("https://maps.googleapis.com/maps/api/place/nearbysearch/json",
        params={"location": f"{loc['lat']},{loc['lng']}", "radius": 5000, "keyword": keyword, "key": GOOGLE_MAPS_API_KEY}).json()
    if resp.get("status") != "OK":
        return {"error": f"Nearby Search error: {resp.get('status')}"}
    results = sorted(resp["results"], key=lambda r: r.get("rating", 0), reverse=True)
    top = [f"{r['name']} - {r.get('vicinity', 'Unknown')} (Rating: {r.get('rating', 'N/A')})" for r in results[:5]]
    return {"result": "\n".join(top)}


@mcp.tool()
def get_coordinates(address: str) -> dict:
    """Get latitude and longitude coordinates for an address."""
    logger.info(f"Tool invoked: get_coordinates for {address}")
    resp = requests.get("https://maps.googleapis.com/maps/api/geocode/json",
        params={"address": address, "key": GOOGLE_MAPS_API_KEY}).json()
    if resp.get("status") != "OK":
        return {"error": f"Geocoding error: {resp.get('status')}"}
    loc = resp["results"][0]["geometry"]["location"]
    return {"result": f"Latitude: {loc['lat']}, Longitude: {loc['lng']}"}


@mcp.tool()
def reverse_geocode(lat: float, lng: float) -> dict:
    """Get address from latitude and longitude coordinates."""
    logger.info(f"Tool invoked: reverse_geocode for ({lat}, {lng})")
    resp = requests.get("https://maps.googleapis.com/maps/api/geocode/json",
        params={"latlng": f"{lat},{lng}", "key": GOOGLE_MAPS_API_KEY}).json()
    if resp.get("status") != "OK":
        return {"error": f"Reverse Geocoding error: {resp.get('status')}"}
    return {"result": resp["results"][0]["formatted_address"]}


@mcp.tool()
def text_search_place(query: str) -> dict:
    """Search for places using text query."""
    logger.info(f"Tool invoked: text_search_place for '{query}'")
    resp = requests.get("https://maps.googleapis.com/maps/api/place/textsearch/json",
        params={"query": query, "key": GOOGLE_MAPS_API_KEY}).json()
    if resp.get("status") != "OK":
        return {"error": f"Text Search error: {resp.get('status')}"}
    results = sorted(resp["results"], key=lambda r: r.get("rating", 0), reverse=True)
    top = [f"{r['name']}\nAddress: {r.get('formatted_address')}\nRating: {r.get('rating', 'N/A')}" for r in results[:5]]
    return {"result": "\n\n".join(top)}


app = mcp.http_app()

if __name__ == "__main__":
    logger.info("🚀 Starting Maps MCP Server...")
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
