#!/bin/bash

set -e

echo "🚀 Starting Azure Router Agent Deployment..."

RESOURCE_GROUP="wealth_management"
REGISTRY_NAME="wmagentacr"
REGISTRY_SERVER="wmagentacr-hmf9f2atgjd6a5ce.azurecr.io"
REGISTRY_USERNAME="wmagentacr"
REGISTRY_PASSWORD="99bDrGd0BGRye6GOM8cL2w4QKF5q0kJVOlT5ESuRBTBbNM0BkwzyJQQJ99CBACHYHv6Eqg7NAAACAZCR8GqI"
IMAGE_NAME="azure-router"
IMAGE_TAG="v6"
FULL_IMAGE="${REGISTRY_SERVER}/${IMAGE_NAME}:${IMAGE_TAG}"
CONTAINER_APP_NAME="azure-router"
CONTAINER_ENV="wm-env"

echo "🐳 Step 1/3: Building Docker image..."
docker build -t ${FULL_IMAGE} .
echo "✅ Built"

echo "📤 Step 2/3: Pushing to ACR..."
az acr login --name ${REGISTRY_NAME}
docker push ${FULL_IMAGE}
echo "✅ Pushed"

echo "🚢 Step 3/3: Deploying to Container Apps..."

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
        --target-port 8000 \
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
            AZURE_OPENAI_API_KEY=ARtgSVjX4btoK5QfpdhlgzAy3lWaVOVCWcKvxm9ncUEElRBw7tm2JQQJ99CBACHYHv6XJ3w3AAABACOGO7pn \
            AZURE_OPENAI_DEPLOYMENT=wm-gpt4o \
            ROUTER_API_KEY=wm-router-2026-secret \
            AGENT_360_URL=https://agent-360.livelybay-96634f40.eastus2.azurecontainerapps.io \
            COMPARISON_LEADS_AGENT_URL=https://comparison-leads-agent.livelybay-96634f40.eastus2.azurecontainerapps.io \
            FUND_AGENT_URL=https://fund-agent.livelybay-96634f40.eastus2.azurecontainerapps.io \
            LEAD_AGENT_URL=https://lead-agent.livelybay-96634f40.eastus2.azurecontainerapps.io \
            MAPS_AGENT_URL=https://maps-agent.livelybay-96634f40.eastus2.azurecontainerapps.io \
            SDI_AGENT_URL=https://sdi-agent.livelybay-96634f40.eastus2.azurecontainerapps.io \
            SMA_AGENT_URL=https://sma-agent.livelybay-96634f40.eastus2.azurecontainerapps.io \
            SOLD_STOCKS_AGENT_URL=https://sold-stocks-agent.livelybay-96634f40.eastus2.azurecontainerapps.io \
            STOCKS_AGENT_URL=https://stocks-agent.livelybay-96634f40.eastus2.azurecontainerapps.io \
            CHECKING_AGENT_URL=https://checking-agent.livelybay-96634f40.eastus2.azurecontainerapps.io \
            SFDC_TASK_AGENT_URL=https://sfdc-task-agent.livelybay-96634f40.eastus2.azurecontainerapps.io
fi

APP_URL=$(az containerapp show --name ${CONTAINER_APP_NAME} --resource-group ${RESOURCE_GROUP} --query properties.configuration.ingress.fqdn -o tsv)

echo ""
echo "✅ Azure Router deployed!"
echo "📍 URL: https://${APP_URL}"
echo "🔗 Chat: https://${APP_URL}/v1/chat/completions"
