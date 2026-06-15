#!/bin/bash

set -e

echo "🚀 Deploying wealth-management-workflow..."
echo ""

RESOURCE_GROUP="wealth_management"
REGISTRY_NAME="wmagentacr"
REGISTRY_SERVER="wmagentacr-hmf9f2atgjd6a5ce.azurecr.io"
REGISTRY_USERNAME="wmagentacr"
REGISTRY_PASSWORD="99bDrGd0BGRye6GOM8cL2w4QKF5q0kJVOlT5ESuRBTBbNM0BkwzyJQQJ99CBACHYHv6Eqg7NAAACAZCR8GqI"
IMAGE_NAME="wealth-management-workflow"
IMAGE_TAG="v1"
FULL_IMAGE="${REGISTRY_SERVER}/${IMAGE_NAME}:${IMAGE_TAG}"
CONTAINER_APP_NAME="wealth-management-workflow"
CONTAINER_ENV="wm-env"
ROUTER_URL="https://a2a-router.livelybay-96634f40.eastus2.azurecontainerapps.io"
ROUTER_API_KEY="wm-router-2026-secret"
STORAGE_ACCOUNT="wmfundstorage"
FILE_SHARE="webui-data-workflow"

echo "🐳 Step 1/4: Building Docker image..."
docker build -t ${FULL_IMAGE} .
echo "✅ Docker image built"
echo ""

echo "📤 Step 2/4: Pushing to ACR..."
az acr login --name ${REGISTRY_NAME}
docker push ${FULL_IMAGE}
echo "✅ Image pushed"
echo ""

echo "📦 Step 3/4: Creating Azure File Share for persistent storage..."
az storage share-rm create \
    --resource-group ${RESOURCE_GROUP} \
    --storage-account ${STORAGE_ACCOUNT} \
    --name ${FILE_SHARE} \
    --quota 5 \
    --output none 2>/dev/null || echo "File share already exists, skipping."

az containerapp env storage set \
    --name ${CONTAINER_ENV} \
    --resource-group ${RESOURCE_GROUP} \
    --storage-name ${FILE_SHARE} \
    --azure-file-account-name ${STORAGE_ACCOUNT} \
    --azure-file-account-key $(az storage account keys list --resource-group ${RESOURCE_GROUP} --account-name ${STORAGE_ACCOUNT} --query '[0].value' -o tsv) \
    --azure-file-share-name ${FILE_SHARE} \
    --access-mode ReadWrite
echo "✅ File share ready"
echo ""

echo "🚢 Step 4/4: Deploying to Azure Container Apps..."

if az containerapp show --name ${CONTAINER_APP_NAME} --resource-group ${RESOURCE_GROUP} &>/dev/null; then
    echo "Container app exists, updating image..."
    az containerapp update \
        --name ${CONTAINER_APP_NAME} \
        --resource-group ${RESOURCE_GROUP} \
        --image ${FULL_IMAGE} \
        --set-env-vars \
            WEBUI_NAME="Wealth Management"
    echo "Attaching volume via patch..."
    az containerapp update \
        --name ${CONTAINER_APP_NAME} \
        --resource-group ${RESOURCE_GROUP} \
        --yaml volume-patch.yaml
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
            WEBUI_NAME="Wealth Management" \
            ENABLE_SIGNUP=true \
            DEFAULT_MODELS="router"
    echo "Attaching volume via patch..."
    az containerapp update \
        --name ${CONTAINER_APP_NAME} \
        --resource-group ${RESOURCE_GROUP} \
        --yaml volume-patch.yaml
fi

echo ""
APP_URL=$(az containerapp show \
    --name ${CONTAINER_APP_NAME} \
    --resource-group ${RESOURCE_GROUP} \
    --query properties.configuration.ingress.fqdn \
    -o tsv)

echo "✅ wealth-management-workflow deployed!"
echo "📍 URL: https://${APP_URL}"
