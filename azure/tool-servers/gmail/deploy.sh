#!/bin/bash
set -e

RESOURCE_GROUP="wealth_management"
REGISTRY_NAME="wmagentacr"
REGISTRY_SERVER="wmagentacr-hmf9f2atgjd6a5ce.azurecr.io"
REGISTRY_USERNAME="wmagentacr"
REGISTRY_PASSWORD="99bDrGd0BGRye6GOM8cL2w4QKF5q0kJVOlT5ESuRBTBbNM0BkwzyJQQJ99CBACHYHv6Eqg7NAAACAZCR8GqI"
IMAGE_NAME="gmail-tool-server"
IMAGE_TAG="v1"
FULL_IMAGE="${REGISTRY_SERVER}/${IMAGE_NAME}:${IMAGE_TAG}"
CONTAINER_APP_NAME="gmail-tool-server"
CONTAINER_ENV="wm-env"

echo "🐳 Building..."
docker build -t ${FULL_IMAGE} .

echo "📤 Pushing..."
az acr login --name ${REGISTRY_NAME}
docker push ${FULL_IMAGE}

echo "🚢 Deploying..."
if az containerapp show --name ${CONTAINER_APP_NAME} --resource-group ${RESOURCE_GROUP} &>/dev/null; then
    az containerapp update \
        --name ${CONTAINER_APP_NAME} \
        --resource-group ${RESOURCE_GROUP} \
        --image ${FULL_IMAGE}
else
    az containerapp create \
        --name ${CONTAINER_APP_NAME} \
        --resource-group ${RESOURCE_GROUP} \
        --environment ${CONTAINER_ENV} \
        --image ${FULL_IMAGE} \
        --target-port 8080 \
        --ingress external \
        --registry-server ${REGISTRY_SERVER} \
        --registry-username ${REGISTRY_USERNAME} \
        --registry-password ${REGISTRY_PASSWORD} \
        --cpu 0.5 \
        --memory 1.0Gi \
        --min-replicas 1 \
        --max-replicas 2 \
        --env-vars \
            GOOGLE_CLIENT_ID="<your-google-client-id>" \
            GOOGLE_CLIENT_SECRET="<your-google-client-secret>" \
            GOOGLE_REFRESH_TOKEN="<your-google-refresh-token>" \
            TOOL_API_KEY="wm-router-2026-secret"
fi

APP_URL=$(az containerapp show \
    --name ${CONTAINER_APP_NAME} \
    --resource-group ${RESOURCE_GROUP} \
    --query properties.configuration.ingress.fqdn \
    -o tsv)

echo ""
echo "✅ Deployed: https://${APP_URL}"
echo "📋 OpenAPI spec: https://${APP_URL}/openapi.json"
echo ""
echo "Add in Open WebUI → Admin → Tool Servers → Add Connection:"
echo "  Type: OpenAPI"
echo "  URL:  https://${APP_URL}/openapi.json"
echo "  Auth: Bearer  |  API Key: wm-router-2026-secret"
