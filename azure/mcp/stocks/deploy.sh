#!/bin/bash

# Stocks MCP Deployment Script

set -e

echo "🚀 Starting Stocks MCP Deployment..."
echo ""

RESOURCE_GROUP="wealth_management"
REGISTRY_NAME="wmagentacr"
REGISTRY_SERVER="wmagentacr-hmf9f2atgjd6a5ce.azurecr.io"
REGISTRY_USERNAME="wmagentacr"
REGISTRY_PASSWORD="99bDrGd0BGRye6GOM8cL2w4QKF5q0kJVOlT5ESuRBTBbNM0BkwzyJQQJ99CBACHYHv6Eqg7NAAACAZCR8GqI"
IMAGE_NAME="stocks-mcp"
IMAGE_TAG="v3"
FULL_IMAGE="${REGISTRY_SERVER}/${IMAGE_NAME}:${IMAGE_TAG}"
CONTAINER_APP_NAME="stocks-mcp"
CONTAINER_ENV="wm-env"

echo "📋 Configuration:"
echo "  Resource Group: ${RESOURCE_GROUP}"
echo "  Registry: ${REGISTRY_SERVER}"
echo "  Image: ${FULL_IMAGE}"
echo "  Container App: ${CONTAINER_APP_NAME}"
echo ""

echo "🐳 Step 1/3: Building Docker image..."
docker build -t ${FULL_IMAGE} .
echo "✅ Docker image built successfully"
echo ""

echo "📤 Step 2/3: Pushing image to Azure Container Registry..."
az acr login --name ${REGISTRY_NAME}
docker push ${FULL_IMAGE}
echo "✅ Image pushed successfully"
echo ""

echo "🚢 Step 3/3: Deploying to Azure Container Apps..."

if az containerapp show --name ${CONTAINER_APP_NAME} --resource-group ${RESOURCE_GROUP} &>/dev/null; then
    echo "Container app exists, updating..."
    az containerapp update \
        --name ${CONTAINER_APP_NAME} \
        --resource-group ${RESOURCE_GROUP} \
        --image ${FULL_IMAGE}
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
        --max-replicas 3 \
        --env-vars \
            AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=https;AccountName=wmfundstorage;AccountKey=ESu1j6iYnU7/0mcufMvGqRjUyfTpCpKB10xkP8pBnw2q2CEmJ4jBFFvwu+dqElJBY2GeJzmQvRsp+ASt8mRCWQ==;EndpointSuffix=core.windows.net" \
            BLOB_CONTAINER=stock-charts \
            APP_BASE_URL=https://stocks-mcp.livelybay-96634f40.eastus2.azurecontainerapps.io \
            FINNHUB_API_KEY=d1nou89r01qovv8kko50d1nou89r01qovv8kko5g \
            ALPHA_VANTAGE_API_KEY=N9H9UKMG4IK4IC7M
fi

echo "✅ Deployment completed successfully"
echo ""

APP_URL=$(az containerapp show \
    --name ${CONTAINER_APP_NAME} \
    --resource-group ${RESOURCE_GROUP} \
    --query properties.configuration.ingress.fqdn \
    -o tsv)

echo "✅ Stocks MCP deployed successfully!"
echo ""
echo "📍 Application URL: https://${APP_URL}"
echo "🔗 MCP Endpoint: https://${APP_URL}/mcp"
echo ""
echo "🧪 Test with:"
echo "  curl https://${APP_URL}/mcp"
echo ""
