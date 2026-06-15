#!/bin/bash

set -e

echo "🚀 Deploying wealth-management webui..."
echo ""

RESOURCE_GROUP="wealth_management"
REGISTRY_NAME="wmagentacr"
REGISTRY_SERVER="wmagentacr-hmf9f2atgjd6a5ce.azurecr.io"
REGISTRY_USERNAME="wmagentacr"
REGISTRY_PASSWORD="99bDrGd0BGRye6GOM8cL2w4QKF5q0kJVOlT5ESuRBTBbNM0BkwzyJQQJ99CBACHYHv6Eqg7NAAACAZCR8GqI"
IMAGE_NAME="wealth-management-webui"
IMAGE_TAG="v5"
FULL_IMAGE="${REGISTRY_SERVER}/${IMAGE_NAME}:${IMAGE_TAG}"
CONTAINER_APP_NAME="wealth-management"
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

cat > /tmp/webui-deploy.yaml << 'EOF'
properties:
  template:
    containers:
      - name: wealth-management
        image: wmagentacr-hmf9f2atgjd6a5ce.azurecr.io/wealth-management-webui:v5
        resources:
          cpu: 1.0
          memory: 2Gi
        env:
          - name: OPENAI_API_BASE_URL
            value: https://router-agent.livelybay-96634f40.eastus2.azurecontainerapps.io/v1
          - name: OPENAI_API_KEY
            value: wm-router-2026-secret
          - name: WEBUI_NAME
            value: Wealth Management
          - name: ENABLE_SIGNUP
            value: "true"
          - name: DEFAULT_MODELS
            value: router
          - name: WEBUI_SECRET_KEY
            value: ca28d550b94ea5a5585a74d0d08410dba7ed951c2babe3e22bc92e6538ff2c49
          - name: JWT_EXPIRES_IN
            value: "24h"
          - name: DATABASE_URL
            value: postgresql://openwebui:WM%40openwebui2026@wm-openwebui-db.postgres.database.azure.com:5432/openwebui
        probes:
          - type: startup
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 30
            periodSeconds: 10
            failureThreshold: 30
            timeoutSeconds: 10
          - type: liveness
            httpGet:
              path: /health
              port: 8080
            periodSeconds: 30
            failureThreshold: 5
            timeoutSeconds: 10
        volumeMounts:
          - mountPath: /app/backend/data/uploads
            volumeName: webui-data
    volumes:
      - name: webui-data
        storageName: webui-data
        storageType: AzureFile
EOF

az containerapp update \
    --name ${CONTAINER_APP_NAME} \
    --resource-group ${RESOURCE_GROUP} \
    --yaml /tmp/webui-deploy.yaml

echo ""
APP_URL=$(az containerapp show \
    --name ${CONTAINER_APP_NAME} \
    --resource-group ${RESOURCE_GROUP} \
    --query properties.configuration.ingress.fqdn \
    -o tsv)

echo "✅ wealth-management deployed!"
echo "📍 URL: https://${APP_URL}"
