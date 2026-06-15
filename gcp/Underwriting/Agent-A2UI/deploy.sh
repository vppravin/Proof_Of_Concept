#!/bin/bash
set -e

PROJECT_ID="gbu-demo-playground"
SERVICE_NAME="underwriting-workbench-a2ui"
MODEL_NAME="gemini-2.5-pro"
REGION="us-central1"
MEMORY="2Gi"

echo "Deploying $SERVICE_NAME to $PROJECT_ID ($REGION) with model $MODEL_NAME..."

gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --memory "$MEMORY" \
  --timeout 540 \
  --allow-unauthenticated \
  --set-env-vars=GOOGLE_CLOUD_PROJECT="$PROJECT_ID",GOOGLE_CLOUD_LOCATION="$REGION",GOOGLE_GENAI_USE_VERTEXAI=TRUE,MODEL="$MODEL_NAME",GOOGLE_PYTHON_PACKAGE_MANAGER=uv

SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --format='value(status.url)')

echo "Updating service with AGENT_URL: $SERVICE_URL"
gcloud run services update "$SERVICE_NAME" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --update-env-vars=AGENT_URL="$SERVICE_URL"

echo ""
echo "✅ Deployment Complete!"
echo "Agent URL: ${SERVICE_URL}"
echo ""
echo "Register with Gemini Enterprise:"
echo "  ENGINE_ID=helio-agentic-mlr-engine_1774872699923"
echo "  Run the register command from SYSTEM.md"
