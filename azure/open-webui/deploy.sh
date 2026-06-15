#!/bin/bash

set -e

echo "🚀 Deploying Open WebUI..."
echo ""

RESOURCE_GROUP="wealth_management"
CONTAINER_APP_NAME="open-webui"
CONTAINER_ENV="wm-env"
ROUTER_URL="https://router-agent--0000001.livelybay-96634f40.eastus2.azurecontainerapps.io"
ROUTER_API_KEY="wm-router-2026-secret"

if az containerapp show --name ${CONTAINER_APP_NAME} --resource-group ${RESOURCE_GROUP} &>/dev/null; then
    echo "Container app exists, updating..."
    az containerapp update \
        --name ${CONTAINER_APP_NAME} \
        --resource-group ${RESOURCE_GROUP} \
        --image ghcr.io/open-webui/open-webui:main
else
    echo "Creating Open WebUI container app..."
    az containerapp create \
        --name ${CONTAINER_APP_NAME} \
        --resource-group ${RESOURCE_GROUP} \
        --environment ${CONTAINER_ENV} \
        --image ghcr.io/open-webui/open-webui:main \
        --target-port 8080 \
        --ingress external \
        --cpu 1.0 \
        --memory 2.0Gi \
        --min-replicas 1 \
        --max-replicas 2 \
        --env-vars \
            OPENAI_API_BASE_URL="${ROUTER_URL}/v1" \
            OPENAI_API_KEY="${ROUTER_API_KEY}" \
            WEBUI_NAME="WM AI Assistant" \
            ENABLE_SIGNUP=true \
            DEFAULT_MODELS="router"
fi

echo ""
APP_URL=$(az containerapp show \
    --name ${CONTAINER_APP_NAME} \
    --resource-group ${RESOURCE_GROUP} \
    --query properties.configuration.ingress.fqdn \
    -o tsv)

echo "✅ Open WebUI deployed!"
echo "📍 URL: https://${APP_URL}"
echo ""
echo "First time setup:"
echo "  1. Open https://${APP_URL}"
echo "  2. Create admin account"
echo "  3. Start chatting — router handles everything"
