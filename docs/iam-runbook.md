# IAM runbook (owner: Andrew, Cloud Cybersecurity)

Your job: decide who and what can touch the Google Cloud project, apply it, prove it, and keep it that way until access ends on Dec 1, 2026. Everything runs from `infra/iam/iam.yaml` and `scripts/iam.py`.

## Who gets what

| Principal | Roles | Scope | Ends |
| --- | --- | --- | --- |
| `roleready-run` (Cloud Run identity) | datastore.user; secretAccessor | project; each secret | never (workload) |
| `roleready-scheduler` (OIDC identity for /jobs/expire) | none | none | never |
| `roleready-export` (BigQuery batch) | datastore.viewer, bigquery.jobUser, bigquery.dataEditor | project | never |
| Mohamed (deployer) | run.admin, run.sourceDeveloper, serviceUsageConsumer, cloudscheduler.admin, logging.viewer; serviceAccountUser | project; on run + scheduler accounts only | Dec 1 |
| Andrew (IAM admin) | projectIamAdmin, serviceAccountAdmin, secretmanager.admin, securityReviewer, privateLogViewer | project | Dec 1 |
| Ashley (auth and lifecycle) | securityReviewer, firebaseauth.admin, cloudscheduler.admin, datastore.viewer, logging.viewer; serviceAccountUser | project; on scheduler account only | Dec 1 |
| Joclyn (analytics) | bigquery.user, datastore.viewer | project | Dec 1 |
| Project Owner (whoever created it) | owner | project | break-glass only, not managed by iam.yaml |

Rules enforced by `python scripts/iam.py lint` (and CI): no basic roles, no public members, no impersonation or key-admin roles, secrets readable only by `roleready-run`, act-as only on one account, every person's access expires, and nobody both rewrites IAM and deploys (separation of duties).

## Phase 1: practice on Floci (today, no cloud account needed)

```bash
docker compose up -d floci-gcp                      # IAM enforcement is on in docker-compose.yml
python scripts/iam.py lint
python scripts/iam.py apply --target floci          # creates accounts, secrets (placeholders) and bindings
FLOCI_GCP_URL=http://localhost:4588 pytest tests/iam -v
```

Show a denial by hand (good for the demo video):

```bash
TOKEN=$(python scripts/iam.py token --target floci --as joclyn)
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:4588/v1/projects/floci-local/secrets/nvidia-api-key/versions/latest:access   # 403
TOKEN=$(python scripts/iam.py token --target floci --as roleready-run)
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:4588/v1/projects/floci-local/secrets/nvidia-api-key/versions/latest:access   # 200
```

Floci is a test tool, not a security boundary. It proves the policy is right. Real protection comes from applying the same policy to Google Cloud.

## Phase 2: apply to the real project

1. The project Owner grants you just enough to run the tool, time-boxed:

```bash
for ROLE in roles/resourcemanager.projectIamAdmin roles/iam.serviceAccountAdmin roles/secretmanager.admin; do
  gcloud projects add-iam-policy-binding $PROJECT_ID --member="user:ANDREW_EMAIL" --role="$ROLE" \
    --condition="expression=request.time < timestamp('2026-12-01T00:00:00Z'),title=expires-2026-12-01"
done
```

2. You, in Cloud Shell or your terminal:

```bash
gcloud auth login && gcloud config set project $PROJECT_ID
PROJECT_ID=$PROJECT_ID bash infra/setup.sh          # APIs, Firestore, NVIDIA key value
cp infra/iam/team.local.example.yaml infra/iam/team.local.yaml   # add real emails; git-ignored
python scripts/iam.py plan  --target gcp --project $PROJECT_ID
python scripts/iam.py apply --target gcp --project $PROJECT_ID   # type the project id to confirm
python scripts/iam.py plan  --target gcp --project $PROJECT_ID   # expect 0 changes
```

3. Prove it on the real project (save the output for the README and deck):

```bash
gcloud projects get-iam-policy $PROJECT_ID --format=json \
  | sed -E 's/user:[^"]+/user:REDACTED/g' > docs/evidence/project-iam-policy.json   # no emails in the repo
gcloud secrets get-iam-policy nvidia-api-key
gcloud policy-intelligence troubleshoot-policy iam \
  //secretmanager.googleapis.com/projects/$PROJECT_ID/secrets/nvidia-api-key \
  --principal-email=JOCLYN_EMAIL --permission=secretmanager.versions.access   # expect: not granted
```

Ask Joclyn to run `gcloud secrets versions access latest --secret=nvidia-api-key` and screenshot the PERMISSION_DENIED.

## Phase 3: manage it until Dec 1

| When | Do |
| --- | --- |
| Someone needs new access | Edit `iam.yaml` in a branch, open a PR, CI runs lint + Floci tests, a teammate reviews, then `plan` and `apply` on gcp |
| A deploy fails with PERMISSION_DENIED | The error names the missing permission. Add the smallest predefined role that has it, through a PR |
| Every Tuesday | `python scripts/iam.py audit --target gcp --project $PROJECT_ID`; paste the summary in the Slack update |
| Someone leaves early | Remove them from `iam.yaml` (apply only adds), then `gcloud projects remove-iam-policy-binding $PROJECT_ID --member=user:EMAIL --role=ROLE --all` for each role |
| Rotate the NVIDIA key | New key at build.nvidia.com, `gcloud secrets versions add nvidia-api-key --data-file=-`, redeploy, disable the old version, revoke the old key at NVIDIA |
| Who read a secret? | Logs Explorer: `protoPayload.serviceName="secretmanager.googleapis.com" AND protoPayload.methodName:"AccessSecretVersion"` (Data Access logs are turned on by apply) |
| Dec 1 | Teammate grants stop working on their own. Run `audit` once more and attach it to the final submission |

## Never

- Create service-account keys. Cloud Run, Scheduler and your own gcloud sign-in all work without them.
- Paste a key, token or teammate email into Slack, a PR or a commit. `team.local.yaml` and `.env*` are git-ignored; gitleaks runs in CI.
- Grant `roles/owner` or `roles/editor` to fix a permission error.
