import os
import logging
from dotenv import load_dotenv
from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.requests import Request
from starlette.responses import JSONResponse
from mcp.server.sse import SseServerTransport
import uvicorn
import requests
from google.cloud import secretmanager

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [MAPS_MCP_SERVER] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logger.info("Initializing FastMCP server...")
mcp = FastMCP("Maps Agent MCP Server")
logger.info("FastMCP server initialized")

# Retrieve API key from Secret Manager
def get_secret(secret_id: str, project_id: str = "gbu-demo-playground") -> str:
    logger.info(f"Retrieving secret: {secret_id}")
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    logger.info("Secret retrieved successfully")
    return response.payload.data.decode("UTF-8")

GOOGLE_MAPS_API_KEY = get_secret("WM")

@mcp.tool()
def get_directions(origin: str, destination: str) -> dict:
    """Get driving directions from origin to destination."""
    logger.info(f"Tool invoked: get_directions from {origin} to {destination}")
    url = "https://maps.googleapis.com/maps/api/directions/json"
    params = {"origin": origin, "destination": destination, "mode": "driving", "key": GOOGLE_MAPS_API_KEY}
    resp = requests.get(url, params=params).json()
    if resp.get("status") != "OK":
        logger.error(f"Directions API error: {resp.get('status')}")
        return {"error": f"Directions API error: {resp.get('status')}"}
    steps = resp["routes"][0]["legs"][0]["steps"]
    directions = "\n".join([s["html_instructions"].replace("<b>", "").replace("</b>", "") for s in steps])
    logger.info(f"Directions retrieved: {len(steps)} steps")
    return {"result": directions}

@mcp.tool()
def search_nearby(location: str, keyword: str) -> dict:
    """Search for nearby places by keyword around a location."""
    logger.info(f"Tool invoked: search_nearby at {location} for {keyword}")
    geo_url = "https://maps.googleapis.com/maps/api/geocode/json"
    geo_resp = requests.get(geo_url, params={"address": location, "key": GOOGLE_MAPS_API_KEY}).json()
    if geo_resp.get("status") != "OK":
        logger.error(f"Geocoding error: {geo_resp.get('status')}")
        return {"error": f"Geocoding error: {geo_resp.get('status')}"}
    loc = geo_resp["results"][0]["geometry"]["location"]
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {"location": f"{loc['lat']},{loc['lng']}", "radius": 5000, "keyword": keyword, "key": GOOGLE_MAPS_API_KEY}
    resp = requests.get(url, params=params).json()
    if resp.get("status") != "OK":
        logger.error(f"Nearby Search error: {resp.get('status')}")
        return {"error": f"Nearby Search error: {resp.get('status')}"}
    results = sorted(resp["results"], key=lambda r: r.get("rating", 0), reverse=True)
    top_results = [f"{r['name']} - {r.get('vicinity', 'Unknown')} (Rating: {r.get('rating', 'N/A')})" for r in results[:5]]
    logger.info(f"Found {len(top_results)} nearby places")
    return {"result": "\n".join(top_results)}

@mcp.tool()
def get_coordinates(address: str) -> dict:
    """Get latitude and longitude coordinates for an address."""
    logger.info(f"Tool invoked: get_coordinates for {address}")
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    resp = requests.get(url, params={"address": address, "key": GOOGLE_MAPS_API_KEY}).json()
    if resp.get("status") != "OK":
        logger.error(f"Geocoding error: {resp.get('status')}")
        return {"error": f"Geocoding error: {resp.get('status')}"}
    loc = resp["results"][0]["geometry"]["location"]
    logger.info(f"Coordinates found: {loc['lat']}, {loc['lng']}")
    return {"result": f"Latitude: {loc['lat']}, Longitude: {loc['lng']}"}

@mcp.tool()
def reverse_geocode(lat: float, lng: float) -> dict:
    """Get address from latitude and longitude coordinates."""
    logger.info(f"Tool invoked: reverse_geocode for ({lat}, {lng})")
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    resp = requests.get(url, params={"latlng": f"{lat},{lng}", "key": GOOGLE_MAPS_API_KEY}).json()
    if resp.get("status") != "OK":
        logger.error(f"Reverse Geocoding error: {resp.get('status')}")
        return {"error": f"Reverse Geocoding error: {resp.get('status')}"}
    address = resp["results"][0]["formatted_address"]
    logger.info(f"Address found: {address}")
    return {"result": address}

@mcp.tool()
def text_search_place(query: str) -> dict:
    """Search for places using text query."""
    logger.info(f"Tool invoked: text_search_place for '{query}'")
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    resp = requests.get(url, params={"query": query, "key": GOOGLE_MAPS_API_KEY}).json()
    if resp.get("status") != "OK":
        logger.error(f"Text Search error: {resp.get('status')}")
        return {"error": f"Text Search error: {resp.get('status')}"}
    results = sorted(resp["results"], key=lambda r: r.get("rating", 0), reverse=True)
    top_results = [f"{r['name']}\nAddress: {r.get('formatted_address')}\nRating: {r.get('rating', 'N/A')}" for r in results[:5]]
    logger.info(f"Found {len(top_results)} places")
    return {"result": "\n\n".join(top_results)}

# SSE + Starlette app config
sse = SseServerTransport("/sse/messages")

async def handle_sse(request: Request):
    logger.info(f"SSE connection request received from {request.client.host}")
    _server = mcp._mcp_server
    try:
        async with sse.connect_sse(
            request.scope,
            request.receive,
            request._send,
        ) as (reader, writer):
            logger.info("SSE connection established, running MCP server...")
            await _server.run(reader, writer, _server.create_initialization_options())
            logger.info("MCP server session completed")
    except Exception as e:
        logger.error(f"Error in SSE handler: {e}")
        raise

async def health_check(request: Request):
    """Health check endpoint for Cloud Run"""
    logger.debug("Health check requested")
    return JSONResponse({"status": "healthy", "service": "Maps MCP Server"})

# Starlette app
app = Starlette(
    debug=False,
    routes=[
        Route("/", endpoint=health_check),
        Route("/health", endpoint=health_check),
        Route("/sse", endpoint=handle_sse),
        Mount("/sse/", app=sse.handle_post_message),
    ],
)

if __name__ == "__main__":
    logger.info("🚀 Starting Maps MCP Server...")
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Server will listen on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
