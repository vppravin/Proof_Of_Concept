FROM ghcr.io/open-webui/open-webui:main

# Custom branding — replace ALL logo/favicon/splash/manifest icons
COPY logo.png /app/build/static/logo.png
COPY logo.png /app/backend/open_webui/static/logo.png
COPY logo.png /app/build/static/splash.png
COPY logo.png /app/build/static/splash-dark.png
COPY logo.png /app/backend/open_webui/static/splash.png
COPY logo.png /app/backend/open_webui/static/splash-dark.png
COPY logo.png /app/build/static/web-app-manifest-192x192.png
COPY logo.png /app/build/static/web-app-manifest-512x512.png
COPY logo.png /app/build/static/apple-touch-icon.png
COPY favicon.png /app/build/favicon.png
COPY favicon.png /app/build/static/favicon.png
COPY favicon.png /app/build/static/favicon-96x96.png
COPY favicon.png /app/build/static/favicon-dark.png
COPY favicon.png /app/backend/open_webui/static/favicon.png
COPY favicon.png /app/backend/open_webui/static/favicon-96x96.png
COPY favicon.png /app/backend/open_webui/static/favicon-dark.png

# Custom CSS to hide Open WebUI text
COPY custom.css /app/backend/open_webui/static/custom.css

# Patch all Open WebUI text references in the build
RUN find /app/build -name "*.js" -o -name "*.html" -o -name "*.json" -o -name "*.xml" | \
    xargs sed -i 's/Open WebUI/Wealth Management/g' 2>/dev/null || true

# Connector dependencies
RUN pip install --no-cache-dir \
    # Salesforce
    simple-salesforce \
    # ServiceNow
    pysnow \
    # Azure SQL
    pyodbc \
    sqlalchemy \
    # Azure Storage / Tables
    azure-data-tables \
    azure-storage-blob \
    # Google Calendar & Gmail
    google-api-python-client \
    google-auth \
    google-auth-httplib2 \
    google-auth-oauthlib \
    # HTTP utilities
    httpx \
    requests
