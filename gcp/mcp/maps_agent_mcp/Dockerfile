FROM python:3.11-slim
WORKDIR /app
COPY requirements-mcp.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY mcp_tool_maps.py .
ENV PORT=${PORT:-8080}
CMD python mcp_tool_maps.py
