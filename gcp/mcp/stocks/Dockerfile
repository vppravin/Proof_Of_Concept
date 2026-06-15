# Use Python slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy .env file
COPY .env .

# Copy MCP requirements
COPY requirements-mcp.txt requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the MCP server file
COPY mcp_tools.py .

# Expose port (Cloud Run default)
EXPOSE 8080

# Start the MCP server
CMD ["python", "mcp_tools.py"]
