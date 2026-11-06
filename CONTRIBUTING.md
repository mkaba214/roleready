# Working together on RoleReady

Repository: `https://github.com/mkaba214/roleready` (owner: Mohamed, Team Lead). `main` is protected: every change goes through a pull request with one teammate's approval and green CI. Nobody pushes to `main` directly, the owner included.

## Team on GitHub

| Teammate | GitHub username | Repo access | Reviews (`.github/CODEOWNERS`) |
| --- | --- | --- | --- |
| Mohamed Kaba (Team Lead) | [@mkaba214](https://github.com/mkaba214) | Owner (settings, invites, branch protection) | Deploy scripts, Dockerfile, Compose, analytics |
| Andrew Hernandez | [@dmandrew01](https://github.com/dmandrew01) | Collaborator (push branches, open and merge PRs) | IAM, policy, auth, CI, Claude Code rules, agent, evals, deploy |
| Ashley Phillips | [@Aphillipstech](https://github.com/Aphillipstech) | Collaborator | IAM, policy, auth, CI, Claude Code rules |
| Joclyn Davis | [@JDenise25](https://github.com/JDenise25) | Collaborator | Agent, evals, BigQuery export, metrics |

Every teammate reviews anything not listed. Mention a teammate in a pull request or comment with their username, for example `@Aphillipstech please review the expiry test`.

## One-time setup (each teammate)

1. **Keep your email private in commits.** GitHub, Settings, Emails: tick "Keep my email addresses private" and "Block command line pushes that expose my email". Copy the `...@users.noreply.github.com` address shown there.
2. **Set your commit identity** (this links your commits to your GitHub profile, which is how BUILD sees your contributions):

```bash
git config --global user.name  "Your Name"
git config --global user.email "12345678+your-username@users.noreply.github.com"
```

3. **Sign in to GitHub from your laptop.** Install the GitHub CLI, then:

```bash
gh auth login        # GitHub.com, HTTPS, log in with a web browser
gh auth setup-git    # lets git push and pull with that sign-in
```

4. **Accept the invitation** in your email or at `https://github.com/mkaba214/roleready/invitations`. Mohamed invites @dmandrew01, @Aphillipstech and @JDenise25 (the setup script does this).
5. **Clone and set up:**

```bash
gh repo clone mkaba214/roleready && cd roleready
python3.12 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pip install pre-commit && pre-commit install              # blocks commits that contain a secret
pytest
```

## Every piece of work

```bash
git switch main && git pull                              # start from the latest main
git switch -c ashley/invite-rate-limit                   # branch: <your-name>/<topic>
# ... make the change (Claude Code is fine) ...
pytest && python scripts/iam.py lint                     # must pass
git status                                               # check: no .env, no data/, no team.local.yaml
git add -A && git commit -m "Rate-limit failed invite accepts"
git push -u origin ashley/invite-rate-limit
gh pr create --fill --base main                          # or click "Compare & pull request" on GitHub
```

Then:

- CI runs `tests`, `secret-scan` and `iam-floci`. Fix anything red by pushing more commits to the same branch.
- GitHub asks the code owners in `.github/CODEOWNERS` to review. IAM, policy and auth files need Andrew (@dmandrew01) or Ashley (@Aphillipstech).
- After one approval and green checks, click **Squash and merge**. The branch deletes itself.
- Everyone else runs `git switch main && git pull` to get it.

If `main` moved while you worked: `git fetch origin && git merge origin/main`, fix any conflicts, run `pytest`, `git push`.

## Reviewing a teammate's pull request

Read the diff, pull the branch if you want to try it (`gh pr checkout <number>`), then approve or request changes with a comment that names the line. Aim to review within one day.

## Floci and Git

Floci runs in Docker on your own laptop. Git pushes **code**, never Floci data. Your emulator state (test users, placeholder secrets, Firestore documents) stays on your machine, and `.gitignore` keeps `data/` out of commits. Everyone gets the same local cloud from the same repo files:

```bash
docker compose up -d floci-gcp
python scripts/iam.py apply --target floci
python scripts/floci_seed.py
```

So push and pull work exactly the same with or without Floci running. If you need data the whole team shares, that belongs in the real Google Cloud project, not in Floci.

## Never commit

`.env`, `.env.floci`, `infra/iam/team.local.yaml`, Floci `data/`, service-account keys, NVIDIA keys, tokens, or anyone's personal email. If you do by accident: tell Andrew (@dmandrew01, security) and Mohamed (@mkaba214) right away, rotate the secret, and do not try to hide it with a force push (main blocks it anyway).

## Final submission

Near Nov 27, Mohamed pushes the full history to the Google Cloud Launchpad Showcase repository on the team branch the program names, then opens the pull request there:

```bash
git remote add showcase <showcase-repo-url>
git push showcase main:<team-branch-name>
```

Every commit keeps its author, so each teammate's contributions show in the showcase repo too.
