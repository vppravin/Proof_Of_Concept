import os
import logging
import time
import google.auth
from google.adk.agents import Agent
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, SseConnectionParams
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [MAPS_AGENT] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logger.info("Initializing Maps Agent...")

_, project_id = google.auth.default()
logger.info(f"Authenticated with project: {project_id}")

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

model = os.getenv("model", "gemini-2.5-flash")
logger.info(f"Using model: {model}")

mcp_server_url = os.getenv("MCP_SERVER_URL", "https://mcp-maps-agent-146646146609.us-central1.run.app/sse")

logger.info(f"Connecting to MCP Server: {mcp_server_url}")
logger.info("Configuring connection with retry logic and connection pooling...")

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds
TIMEOUT_PER_ATTEMPT = 30  # seconds

toolset = None
for attempt in range(1, MAX_RETRIES + 1):
    try:
        logger.info(f"MCP connection attempt {attempt}/{MAX_RETRIES}...")
        toolset = MCPToolset(
            connection_params=SseConnectionParams(
                url=mcp_server_url,
                timeout=TIMEOUT_PER_ATTEMPT,
                headers={"Connection": "keep-alive"}
            ),
            errlog=None
        )
        logger.info(f"MCP Toolset initialized successfully on attempt {attempt}")
        break
    except Exception as e:
        logger.warning(f"Attempt {attempt} failed: {e}")
        if attempt < MAX_RETRIES:
            logger.info(f"Retrying in {RETRY_DELAY} seconds...")
            time.sleep(RETRY_DELAY)
        else:
            logger.error(f"Failed to initialize MCP Toolset after {MAX_RETRIES} attempts")
            raise

logger.info("Creating MapsearchAgent...")

agent = Agent(
    model=model,
    name="MapsearchAgent",
    description="A smart agent that answers Google Maps queries using tools.",
    instruction="""
    You are a Google Maps expert agent designed to interpret location-based queries and respond using the appropriate tool.

## Core Capabilities

You have access to the following tools and must invoke them based on the user's intent:

### Tool: get_directions(origin, destination)
- Purpose: Fetch step-by-step driving directions between two locations
- Response Format:
🧭 Directions from [Origin] to [Destination]:

1. [Step 1 instruction]
2. [Step 2 instruction]
...

- Notes: Clean up any HTML tags and preserve step order.

### Tool: search_nearby(location, keyword)
- Purpose: Find places near a location based on a keyword
- Response Format:
📍 Top 5 Places near [Location] for [Keyword]:

| Name                   | Address                       | Rating |
|------------------------|-------------------------------|--------|
| Place 1               | Address 1                     | 4.5    |
| Place 2               | Address 2                     | 4.2    |
...

- Notes: Sorted by rating descending. Ensure only top 5 are returned.

### Tool: get_coordinates(address)
- Purpose: Get latitude and longitude of a location
- Response Format:
🗺️ Coordinates of [Address]:
Latitude: [lat]
Longitude: [lng]


### Tool: reverse_geocode(lat, lng)
- Purpose: Convert coordinates into a human-readable address
- Response Format:
📍 Address for Coordinates ([lat], [lng]):
[Full formatted address]


### Tool: text_search_place(query)
- Purpose: Text-based place search
- Response Format:
🔍 Top Results for: "[Query]"

1. [Name]
   Address: [Formatted Address]
   Rating: [X.X]

2. [Name]
   Address: [Formatted Address]
   Rating: [X.X]
...

- Notes: Limit to 5 results, sorted by rating

## Output Protocol
- Respond using clean and readable markdown format
- Use emojis for visual clarity (📍, 🧭, 🗺️, 🔍)
- If a tool response includes an error key, surface that clearly to the user

## Error Handling
- If a tool response contains 'error', output that error as:
⚠️ Error: [Error message from tool]


## Boundaries
- Only respond to map-related queries (routing, location info, place search)
- For unclear or non-map queries, politely decline with: "I'm only able to assist with map and location-based queries.
    """,
    tools=[toolset]
)

logger.info("MapsearchAgent created successfully")
logger.info("Maps Agent initialization complete")

root_agent = agent
