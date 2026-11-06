#!/usr/bin/env bash
# One-time Google Cloud setup for RoleReady. Run in Cloud Shell (or anywhere gcloud is signed in).
#   PROJECT_ID=your-project REGION=us-central1 bash infra/setup.sh
#
# Order:  1) this script (APIs, Firestore, the NVIDIA secret value)
#         2) python scripts/iam.py apply --target gcp --project $PROJECT_ID   (service accounts + every IAM binding)
#         3) bash infra/deploy.sh   4) bash infra/scheduler.sh
# IAM lives in infra/iam/iam.yaml only. This script grants nothing.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?Set PROJECT_ID}"
REGION="${REGION:-us-central1}"

gcloud config set project "$PROJECT_ID"

echo "== Enabling APIs"
gcloud services enable \
  run.googleapis.com firestore.googleapis.com secretmanager.googleapis.com \
  cloudscheduler.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  identitytoolkit.googleapis.com iam.googleapis.com iamcredentials.googleapis.com \
  cloudresourcemanager.googleapis.com bigquery.googleapis.com policytroubleshooter.googleapis.com

echo "== Firestore (Native mode)"
if ! gcloud firestore databases describe --database="(default)" >/dev/null 2>&1; then
  gcloud firestore databases create --location="$REGION" --type=firestore-native
fi

echo "== NVIDIA API key into Secret Manager (value only; access is granted by scripts/iam.py)"
if ! gcloud secrets describe nvidia-api-key >/dev/null 2>&1; then
  read -r -s -p "Paste the NVIDIA API key from build.nvidia.com (input hidden): " NVIDIA_KEY; echo
  printf '%s' "$NVIDIA_KEY" | gcloud secrets create nvidia-api-key --replication-policy=automatic --data-file=-
  unset NVIDIA_KEY
fi

echo
echo "Done. Next (Andrew):"
echo "  cp infra/iam/team.local.example.yaml infra/iam/team.local.yaml   # real emails, git-ignored"
echo "  python scripts/iam.py plan  --target gcp --project ${PROJECT_ID}"
echo "  python scripts/iam.py apply --target gcp --project ${PROJECT_ID}"
echo "Then (Mohamed): Firebase console setup, firestore rules, infra/deploy.sh, infra/scheduler.sh"
