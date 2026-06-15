# Use Python slim image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app
COPY . .

# Expose port (Cloud Run default)
EXPOSE 8080

# Start the FastMCP server using Uvicorn
CMD uvicorn mcp_tool_checking:app --host 0.0.0.0 --port ${PORT:-8080}
