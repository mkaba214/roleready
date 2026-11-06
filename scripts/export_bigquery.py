"""Copy audit events from Firestore to BigQuery for the success-measure dashboard (batch).

Real Google Cloud:
  pip install -r requirements-scripts.txt
  gcloud auth application-default login
  python scripts/export_bigquery.py --project YOUR_PROJECT_ID

Floci (local practice, no account needed):
  python scripts/export_bigquery.py --project floci-local --emulator http://localhost:4588

Creates dataset `roleready` and replaces table `audit_events` each run.
Then open Looker Studio, add a BigQuery source, and use the queries in scripts/metrics.sql.
"""

from __future__ import annotations

import argparse
import json
import os

from google.cloud import bigquery, firestore

SCHEMA = [
    bigquery.SchemaField("id", "STRING"),
    bigquery.SchemaField("seq", "INTEGER"),
    bigquery.SchemaField("ts", "TIMESTAMP"),
    bigquery.SchemaField("workspace_id", "STRING"),
    bigquery.SchemaField("actor", "STRING"),
    bigquery.SchemaField("action", "STRING"),
    bigquery.SchemaField("target", "STRING"),
    bigquery.SchemaField("decision", "STRING"),
    bigquery.SchemaField("reason", "STRING"),
    bigquery.SchemaField("details", "STRING"),  # JSON text; query with JSON_VALUE()
    bigquery.SchemaField("hash", "STRING"),
]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--project", required=True)
    p.add_argument("--dataset", default="roleready")
    p.add_argument("--table", default="audit_events")
    p.add_argument("--location", default="US")
    p.add_argument("--emulator", default="", help="Floci URL, e.g. http://localhost:4588")
    a = p.parse_args()

    bq_kwargs: dict = {}
    if a.emulator:
        from google.api_core.client_options import ClientOptions
        from google.auth.credentials import AnonymousCredentials

        os.environ.setdefault("FIRESTORE_EMULATOR_HOST", a.emulator.split("://", 1)[-1])
        bq_kwargs = {"credentials": AnonymousCredentials(), "client_options": ClientOptions(api_endpoint=a.emulator)}

    rows = []
    for snap in firestore.Client(project=a.project).collection("audit_events").stream():
        d = snap.to_dict()
        rows.append({
            "id": d["id"], "seq": d["seq"], "ts": d["ts"].isoformat(), "workspace_id": d["workspace_id"],
            "actor": d["actor"], "action": d["action"], "target": d.get("target", ""),
            "decision": d.get("decision"), "reason": d.get("reason", ""),
            "details": json.dumps(d.get("details") or {}, default=str), "hash": d.get("hash", ""),
        })

    bq = bigquery.Client(project=a.project, **bq_kwargs)
    dataset = bigquery.Dataset(f"{a.project}.{a.dataset}")
    dataset.location = a.location
    bq.create_dataset(dataset, exists_ok=True)
    job = bq.load_table_from_json(
        rows,
        f"{a.project}.{a.dataset}.{a.table}",
        job_config=bigquery.LoadJobConfig(schema=SCHEMA, write_disposition="WRITE_TRUNCATE"),
    )
    job.result()
    print(f"Loaded {len(rows)} audit events into {a.project}.{a.dataset}.{a.table}")


if __name__ == "__main__":
    main()
