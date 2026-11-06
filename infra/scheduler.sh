#!/usr/bin/env bash
# Create (or update) the Cloud Scheduler job that runs the expiry job every minute.
# The job signs each call with an OIDC token for the roleready-scheduler service account.
# The app accepts /jobs/expire only from that account, for that audience.
#   PROJECT_ID=... bash infra/scheduler.sh
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?Set PROJECT_ID}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-roleready}"
JOB="${JOB:-roleready-expire}"
SCHED_SA="roleready-scheduler@${PROJECT_ID}.iam.gserviceaccount.com"

URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT_ID" --format='value(status.url)')"

if gcloud scheduler jobs describe "$JOB" --location "$REGION" --project "$PROJECT_ID" >/dev/null 2>&1; then
  VERB=update
else
  VERB=create
fi

gcloud scheduler jobs "$VERB" http "$JOB" \
  --project "$PROJECT_ID" --location "$REGION" \
  --schedule="* * * * *" --time-zone="Etc/UTC" \
  --http-method=POST --uri="${URL}/jobs/expire" \
  --oidc-service-account-email="$SCHED_SA" \
  --oidc-token-audience="$URL" \
  --attempt-deadline=60s

echo "Scheduler job ${JOB}: POST ${URL}/jobs/expire every minute as ${SCHED_SA}"
echo "Run it now:  gcloud scheduler jobs run ${JOB} --location ${REGION} --project ${PROJECT_ID}"
