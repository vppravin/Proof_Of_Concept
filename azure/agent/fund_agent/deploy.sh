#!/bin/bash

# Fund Agent Deployment Script
# This script builds, pushes, and deploys the Fund Agent to Azure Container Apps

set -e  # Exit on any error

echo "🚀 Starting Fund Agent Deployment..."
echo ""

# Configuration
RESOURCE_GROUP="wealth_management"
REGISTRY_NAME="wmagentacr"
REGISTRY_SERVER="wmagentacr-hmf9f2atgjd6a5ce.azurecr.io"
REGISTRY_USERNAME="wmagentacr"
REGISTRY_PASSWORD="99bDrGd0BGRye6GOM8cL2w4QKF5q0kJVOlT5ESuRBTBbNM0BkwzyJQQJ99CBACHYHv6Eqg7NAAACAZCR8GqI"
IMAGE_NAME="fund-agent"
IMAGE_TAG="v2"
FULL_IMAGE="${REGISTRY_SERVER}/${IMAGE_NAME}:${IMAGE_TAG}"
CONTAINER_APP_NAME="fund-agent"
CONTAINER_ENV="wm-env"
LOCATION="eastus2"

echo "📋 Configuration:"
echo "  Resource Group: ${RESOURCE_GROUP}"
echo "  Registry: ${REGISTRY_SERVER}"
echo "  Image: ${FULL_IMAGE}"
echo "  Container App: ${CONTAINER_APP_NAME}"
echo ""

# Step 1: Build Docker image
echo "🐳 Step 1/3: Building Docker image..."
docker build -t ${FULL_IMAGE} .
echo "✅ Docker image built successfully"
echo ""

# Step 2: Login to ACR and push image
echo "📤 Step 2/3: Pushing image to Azure Container Registry..."
az acr login --name ${REGISTRY_NAME}
docker push ${FULL_IMAGE}
echo "✅ Image pushed successfully"
echo ""

# Step 3: Deploy to Container Apps
echo "🚢 Step 3/3: Deploying to Azure Container Apps..."

# Check if container app exists
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
        --max-replicas 5 \
        --env-vars \
            AZURE_OPENAI_ENDPOINT=https://wealth-management-openai.openai.azure.com/ \
            AZURE_OPENAI_DEPLOYMENT=wm-gpt4o \
            MCP_SERVER_URL=https://fund-agent-mcp.livelybay-96634f40.eastus2.azurecontainerapps.io/mcp
    
    # Enable Managed Identity
    echo "🔐 Enabling Managed Identity..."
    az containerapp identity assign \
        --name ${CONTAINER_APP_NAME} \
        --resource-group ${RESOURCE_GROUP} \
        --system-assigned
    
    echo "✅ Managed Identity enabled"
    echo "⚠️  IMPORTANT: Manually add AZURE_OPENAI_API_KEY environment variable via Azure Portal or CLI"
fi

echo "✅ Deployment completed successfully"
echo ""

# Get the URL
echo "🌐 Getting application URL..."
APP_URL=$(az containerapp show \
    --name ${CONTAINER_APP_NAME} \
    --resource-group ${RESOURCE_GROUP} \
    --query properties.configuration.ingress.fqdn \
    -o tsv)

echo ""
echo "✅ Fund Agent deployed successfully!"
echo ""
echo "📍 Application URL: https://${APP_URL}"
echo "🔗 Health Endpoint: https://${APP_URL}/health"
echo "🔗 Query Endpoint: https://${APP_URL}/query"
echo ""
echo "🧪 Test with:"
echo "  curl https://${APP_URL}/health"
echo "  curl -X POST https://${APP_URL}/query -H 'Content-Type: application/json' -d '{\"query\": \"Show fund returns for Peter Griffin\"}'"
echo ""
