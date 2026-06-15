FROM python:3.11-slim
WORKDIR /app
COPY requirements-mcp.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=${PORT:-8080}
CMD python mcp_sse_360_server.py