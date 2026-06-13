#!/bin/bash
set -e

PROJECT_ID="gbu-demo-playground"
SERVICE_NAME="underwriting-workbench-ui"
REGION="us-central1"

echo "Building React frontend..."
cd frontend && npx vite build && cd ..

echo "Copying build to backend/static..."
rm -rf backend/static
cp -r frontend/dist backend/static

echo "Deploying to Cloud Run..."
cd backend
gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --memory 1Gi \
  --timeout 540 \
  --allow-unauthenticated \
  --set-env-vars=GOOGLE_CLOUD_PROJECT="$PROJECT_ID"

SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --format='value(status.url)')

echo ""
echo "✅ Deployed!"
echo "URL: ${SERVICE_URL}"
