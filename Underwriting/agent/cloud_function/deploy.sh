#!/bin/bash
# Deploy the Cloud Function with Eventarc GCS trigger
# Triggers when any file is created/uploaded under gs://underwriting-workbench/Input_Files/

PROJECT_ID="gbu-demo-playground"
REGION="us-central1"
FUNCTION_NAME="process-submission-trigger"
BUCKET_NAME="underwriting-workbench"
SERVICE_ACCOUNT="146646146609-compute@developer.gserviceaccount.com"

gcloud functions deploy $FUNCTION_NAME \
    --gen2 \
    --runtime=python311 \
    --region=$REGION \
    --source=. \
    --entry-point=process_submission \
    --trigger-location=us \
    --trigger-event-filters="type=google.cloud.storage.object.v1.finalized" \
    --trigger-event-filters="bucket=$BUCKET_NAME" \
    --service-account=$SERVICE_ACCOUNT \
    --memory=512MB \
    --timeout=540s \
    --min-instances=0 \
    --max-instances=3 \
    --project=$PROJECT_ID

echo ""
echo "✅ Deployed. New files in gs://$BUCKET_NAME/Input_Files/ will auto-trigger processing."
