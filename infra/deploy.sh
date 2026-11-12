#!/usr/bin/env bash
# Build and deploy RoleReady to Cloud Run.
#   PROJECT_ID=... OWNER_EMAIL=owner@example.com \
#   FIREBASE_API_KEY=... FIREBASE_AUTH_DOMAIN=your-project.firebaseapp.com \
#   bash infra/deploy.sh
#
# Hackathon fallback without Firebase (demo identity picker, NOT for real users):
#   AUTH_MODE=demo ALLOW_DEMO_AUTH_ON_CLOUD_RUN=true PROJECT_ID=... OWNER_EMAIL=... bash infra/deploy.sh
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?Set PROJECT_ID}"
OWNER_EMAIL="${OWNER_EMAIL:?Set OWNER_EMAIL (the workspace owner sign-in email)}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-roleready}"
AUTH_MODE="${AUTH_MODE:-firebase}"
RUN_SA="roleready-run@${PROJECT_ID}.iam.gserviceaccount.com"
SCHED_SA="roleready-scheduler@${PROJECT_ID}.iam.gserviceaccount.com"

cd "$(dirname "$0")/.."
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

EXISTING_URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT_ID" \
  --format='value(status.url)' 2>/dev/null || true)"

cat > "$TMP/env.yaml" <<EOF
STORE_BACKEND: "firestore"
AUTH_MODE: "${AUTH_MODE}"
ALLOW_DEMO_AUTH_ON_CLOUD_RUN: "${ALLOW_DEMO_AUTH_ON_CLOUD_RUN:-false}"
GOOGLE_CLOUD_PROJECT: "${PROJECT_ID}"
FIREBASE_PROJECT_ID: "${PROJECT_ID}"
FIREBASE_API_KEY: "${FIREBASE_API_KEY:-}"
FIREBASE_AUTH_DOMAIN: "${FIREBASE_AUTH_DOMAIN:-${PROJECT_ID}.firebaseapp.com}"
OWNER_EMAIL: "${OWNER_EMAIL}"
WORKSPACE_ID: "${WORKSPACE_ID:-bloom-and-crumb}"
WORKSPACE_NAME: "${WORKSPACE_NAME:-Bloom & Crumb}"
DEFAULT_TIMEZONE: "${DEFAULT_TIMEZONE:-America/Chicago}"
NVIDIA_MODEL: "${NVIDIA_MODEL:-nvidia/nemotron-3.5-lightning-30b-a3b}"
SCHEDULER_SERVICE_ACCOUNT: "${SCHED_SA}"
SCHEDULER_AUDIENCE: "${EXISTING_URL}"
INTEGRATION_NAME: "newly"
INTEGRATION_ALLOW_OWNER: "${INTEGRATION_ALLOW_OWNER:-false}"
CORS_ALLOWED_ORIGINS: "${CORS_ALLOWED_ORIGINS:-}"
EOF

# Secrets are mounted as env vars. The integration key is optional: create the roleready-integration-key secret to turn it on.
SECRETS="NVIDIA_API_KEY=nvidia-api-key:latest"
if gcloud secrets describe roleready-integration-key --project "$PROJECT_ID" >/dev/null 2>&1; then
  SECRETS="${SECRETS},INTEGRATION_API_KEY=roleready-integration-key:latest"
fi

echo "== Deploying ${SERVICE} (auth: ${AUTH_MODE})"
gcloud run deploy "$SERVICE" \
  --project "$PROJECT_ID" --region "$REGION" --source . \
  --service-account "$RUN_SA" \
  --allow-unauthenticated \
  --env-vars-file "$TMP/env.yaml" \
  --set-secrets "$SECRETS" \
  --min-instances 0 --max-instances 3 --memory 512Mi

URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT_ID" --format='value(status.url)')"
if [[ "$URL" != "$EXISTING_URL" ]]; then
  echo "== First deploy: setting SCHEDULER_AUDIENCE=${URL}"
  gcloud run services update "$SERVICE" --region "$REGION" --project "$PROJECT_ID" \
    --update-env-vars "SCHEDULER_AUDIENCE=${URL}"
fi

echo
echo "Live at: ${URL}"
echo "Health:  curl ${URL}/health"
