#!/bin/bash

# Fund Agent MCP Deployment Script
# This script builds, pushes, and deploys the Fund Agent MCP to Azure Container Apps

set -e  # Exit on any error

echo "🚀 Starting Fund Agent MCP Deployment..."
echo ""

# Configuration
RESOURCE_GROUP="wealth_management"
REGISTRY_NAME="wmagentacr"
REGISTRY_SERVER="wmagentacr-hmf9f2atgjd6a5ce.azurecr.io"
REGISTRY_USERNAME="wmagentacr"
REGISTRY_PASSWORD="99bDrGd0BGRye6GOM8cL2w4QKF5q0kJVOlT5ESuRBTBbNM0BkwzyJQQJ99CBACHYHv6Eqg7NAAACAZCR8GqI"
IMAGE_NAME="fund-agent-mcp"
IMAGE_TAG="v1"
FULL_IMAGE="${REGISTRY_SERVER}/${IMAGE_NAME}:${IMAGE_TAG}"
CONTAINER_APP_NAME="fund-agent-mcp"
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
        --max-replicas 3 \
        --env-vars \
            AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=https;AccountName=wmfundstorage;AccountKey=ESu1j6iYnU7/0mcufMvGqRjUyfTpCpKB10xkP8pBnw2q2CEmJ4jBFFvwu+dqElJBY2GeJzmQvRsp+ASt8mRCWQ==;EndpointSuffix=core.windows.net" \
            AZURE_SQL_CONNECTION_STRING="Driver={ODBC Driver 18 for SQL Server};Server=tcp:wm-sql-server-2026.database.windows.net,1433;Database=WealthManagement;Uid=sqladmin;Pwd=WM@wealthmanagement;Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=30;" \
            AZURE_OPENAI_ENDPOINT=https://wealth-management-openai.openai.azure.com/ \
            AZURE_OPENAI_DEPLOYMENT=wm-gpt4o \
            BLOB_CONTAINER=fund-analyzer \
            INPUT_PDF_BLOB="trend_document/trend_document_Franklin India Fund Factsheet.pdf" \
            OUTPUT_TXT_BLOB=trend_document/trend_document_funds_trend_insight.txt
    
    echo ""
    echo "⚠️  ========================================"
    echo "⚠️  IMPORTANT: Add AZURE_OPENAI_API_KEY manually via Azure Portal"
    echo "⚠️  ========================================"
    echo ""
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
echo "✅ Fund Agent MCP deployed successfully!"
echo ""
echo "📍 Application URL: https://${APP_URL}"
echo "🔗 MCP Endpoint: https://${APP_URL}/mcp"
echo ""
echo "🧪 Test with:"
echo "  curl https://${APP_URL}/mcp"
echo ""
