#!/usr/bin/env bash
# Builds the crawler image and deploys it as an hourly Cloud Run Job that
# appends each crawl's offers to BigQuery. Safe to re-run: existing
# resources are left in place and the job/schedule are updated.
#
# Usage: deploy/deploy.sh   (from the repo root, with gcloud authenticated)

set -euo pipefail

PROJECT="${PROJECT:-open-mateo}"
REGION="${REGION:-europe-west2}"
DATASET="${DATASET:-mobile_pricing}"
TABLE="${TABLE:-offers}"
JOB="${JOB:-mobile-competition-crawler}"
REPO="${REPO:-crawler}"
SCHEDULE="${SCHEDULE:-0 * * * *}"
TIME_ZONE="${TIME_ZONE:-Europe/London}"

JOB_SA="crawler-job@${PROJECT}.iam.gserviceaccount.com"
SCHEDULER_SA="crawler-scheduler@${PROJECT}.iam.gserviceaccount.com"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${JOB}:$(date +%Y%m%d-%H%M%S)"
BQ_TABLE="${PROJECT}.${DATASET}.${TABLE}"

cd "$(dirname "$0")/.."

echo "==> Enabling APIs"
gcloud services enable \
    run.googleapis.com \
    cloudscheduler.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    bigquery.googleapis.com \
    --project="$PROJECT"

echo "==> BigQuery dataset and table"
if ! bq --project_id="$PROJECT" show "${PROJECT}:${DATASET}" >/dev/null 2>&1; then
    bq --project_id="$PROJECT" mk --dataset --location="$REGION" \
        --description="Competitor mobile pricing crawled hourly" \
        "${PROJECT}:${DATASET}"
fi

if ! bq --project_id="$PROJECT" show "${PROJECT}:${DATASET}.${TABLE}" >/dev/null 2>&1; then
    bq --project_id="$PROJECT" mk --table \
        --time_partitioning_field=observed_at \
        --time_partitioning_type=DAY \
        --clustering_fields=competitor,offer_id \
        --description="One row per offer per crawl" \
        "${PROJECT}:${DATASET}.${TABLE}" \
        crawler/bigquery_schema.json
fi

echo "==> Service accounts"
for sa in crawler-job crawler-scheduler; do
    if ! gcloud iam service-accounts describe "${sa}@${PROJECT}.iam.gserviceaccount.com" \
            --project="$PROJECT" >/dev/null 2>&1; then
        gcloud iam service-accounts create "$sa" --project="$PROJECT" \
            --display-name="Mobile competition crawler (${sa#crawler-})"
    fi
done

# The job can run BigQuery load jobs in the project, and write only to
# its own table (dataset-level bq IAM bindings need allowlisting)
gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:${JOB_SA}" \
    --role="roles/bigquery.jobUser" \
    --condition=None >/dev/null

bq --project_id="$PROJECT" add-iam-policy-binding \
    --member="serviceAccount:${JOB_SA}" \
    --role="roles/bigquery.dataEditor" \
    "${PROJECT}:${DATASET}.${TABLE}" >/dev/null

echo "==> Building image ${IMAGE}"
if ! gcloud artifacts repositories describe "$REPO" \
        --location="$REGION" --project="$PROJECT" >/dev/null 2>&1; then
    gcloud artifacts repositories create "$REPO" \
        --repository-format=docker --location="$REGION" --project="$PROJECT"
fi

gcloud builds submit --tag="$IMAGE" --project="$PROJECT" --region="$REGION" .

echo "==> Cloud Run Job"
# No retries: a retry after a partly failed run would insert the
# successful URLs' offers twice. The next hourly run picks up instead.
gcloud run jobs deploy "$JOB" \
    --image="$IMAGE" \
    --region="$REGION" \
    --project="$PROJECT" \
    --service-account="$JOB_SA" \
    --set-env-vars="BQ_TABLE=${BQ_TABLE}" \
    --cpu=1 \
    --memory=2Gi \
    --task-timeout=10m \
    --max-retries=0

# The scheduler can start this job and nothing else
gcloud run jobs add-iam-policy-binding "$JOB" \
    --region="$REGION" \
    --project="$PROJECT" \
    --member="serviceAccount:${SCHEDULER_SA}" \
    --role="roles/run.invoker" >/dev/null

echo "==> Cloud Scheduler (${SCHEDULE}, ${TIME_ZONE})"
RUN_URI="https://run.googleapis.com/v2/projects/${PROJECT}/locations/${REGION}/jobs/${JOB}:run"

if gcloud scheduler jobs describe "$JOB" --location="$REGION" \
        --project="$PROJECT" >/dev/null 2>&1; then
    SCHEDULER_ACTION=update
else
    SCHEDULER_ACTION=create
fi

gcloud scheduler jobs "$SCHEDULER_ACTION" http "$JOB" \
    --location="$REGION" \
    --project="$PROJECT" \
    --schedule="$SCHEDULE" \
    --time-zone="$TIME_ZONE" \
    --uri="$RUN_URI" \
    --http-method=POST \
    --oauth-service-account-email="$SCHEDULER_SA"

echo
echo "Deployed. Run once now with:"
echo "  gcloud run jobs execute ${JOB} --region=${REGION} --project=${PROJECT} --wait"
echo "Results land in ${BQ_TABLE}"
