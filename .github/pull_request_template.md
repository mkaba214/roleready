## What and why

<!-- One or two sentences. Link the brief section, roadmap week or issue this supports. -->

## How I tested

- [ ] `pytest` passes
- [ ] `python scripts/iam.py lint` passes
- [ ] IAM change: `FLOCI_GCP_URL=http://localhost:4588 pytest tests/iam -v` passes against Floci
- [ ] UI change: screenshot attached below
- [ ] Ran the app locally (memory or Floci) and tried the change by hand

## Safety

- [ ] No keys, tokens, `.env` files, Floci data or personal emails in this diff
- [ ] Permission, expiry, auth or agent change: a test was written first and is included

## Notes for the reviewer

<!-- Anything you want a second pair of eyes on. -->
