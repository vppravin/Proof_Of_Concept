#!/bin/bash

set -e

echo "🚀 Deploying latest-azure-webui..."
echo ""

RESOURCE_GROUP="wealth_management"
REGISTRY_NAME="wmagentacr"
REGISTRY_SERVER="wmagentacr-hmf9f2atgjd6a5ce.azurecr.io"
REGISTRY_USERNAME="wmagentacr"
REGISTRY_PASSWORD="99bDrGd0BGRye6GOM8cL2w4QKF5q0kJVOlT5ESuRBTBbNM0BkwzyJQQJ99CBACHYHv6Eqg7NAAACAZCR8GqI"
IMAGE_NAME="latest-azure-webui"
IMAGE_TAG="v1"
FULL_IMAGE="${REGISTRY_SERVER}/${IMAGE_NAME}:${IMAGE_TAG}"
CONTAINER_APP_NAME="latest-azure-webui"
CONTAINER_ENV="wm-env"
ROUTER_URL="https://router-agent.livelybay-96634f40.eastus2.azurecontainerapps.io"
ROUTER_API_KEY="wm-router-2026-secret"

echo "🐳 Step 1/3: Building Docker image..."
docker build -t ${FULL_IMAGE} .
echo "✅ Docker image built"
echo ""

echo "📤 Step 2/3: Pushing to ACR..."
az acr login --name ${REGISTRY_NAME}
docker push ${FULL_IMAGE}
echo "✅ Image pushed"
echo ""

echo "🚢 Step 3/3: Deploying to Azure Container Apps..."

if az containerapp show --name ${CONTAINER_APP_NAME} --resource-group ${RESOURCE_GROUP} &>/dev/null; then
    echo "Container app exists, updating..."
    az containerapp update \
        --name ${CONTAINER_APP_NAME} \
        --resource-group ${RESOURCE_GROUP} \
        --image ${FULL_IMAGE} \
        --registry-server ${REGISTRY_SERVER} \
        --registry-username ${REGISTRY_USERNAME} \
        --registry-password ${REGISTRY_PASSWORD}
else
    echo "Creating new container app..."
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

echo "✅ latest-azure-webui deployed!"
echo "📍 URL: https://${APP_URL}"
