#!/usr/bin/env bash
# Set up and lock down the team repository on GitHub. Run once, by the repo OWNER (Mohamed, Team Lead),
# from a clone of mkaba214/roleready (or the unzipped project folder), after `gh auth login` and `gh auth setup-git`.
#
#   bash scripts/github_setup.sh --dry-run     # print every step, change nothing
#   bash scripts/github_setup.sh
#
# Team GitHub usernames (built in): Mohamed mkaba214 · Andrew dmandrew01 · Ashley Aphillipstech · Joclyn JDenise25
# Options: --mohamed/--andrew/--ashley/--joclyn USERNAME (override one) · --name roleready (repo name)
#          · --private (new repos only) · --dry-run
#
# What it does
#   1. Refuses to continue if a secret or local-only file (.env, team.local.yaml, Floci data/) would be committed.
#   2. Fills any CODEOWNERS placeholders with the four usernames and commits.
#   3. Pushes main to OWNER/roleready (uses the existing empty repo, or creates it if missing).
#   4. Squash merges only; branches auto-delete after merge.
#   5. Dependabot alerts and fixes; secret scanning with push protection (public repos).
#   6. Invites the three teammates who are not the owner (they can push branches and open pull requests).
#   7. Protects main: pull request + 1 approval + code-owner review + green CI, no force pushes,
#      and the rules apply to the owner too.
set -euo pipefail

REPO_NAME="roleready"
VISIBILITY="public"
DRY_RUN=0
MOHAMED="mkaba214" ANDREW="dmandrew01" ASHLEY="Aphillipstech" JOCLYN="JDenise25"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mohamed) MOHAMED="$2"; shift 2 ;;
    --andrew)  ANDREW="$2";  shift 2 ;;
    --ashley)  ASHLEY="$2";  shift 2 ;;
    --joclyn)  JOCLYN="$2";  shift 2 ;;
    --name)    REPO_NAME="$2"; shift 2 ;;
    --private) VISIBILITY="private"; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) sed -n 2,20p "$0"; exit 0 ;;
    *) echo "Unknown option $1"; exit 2 ;;
  esac
done

run() {
  echo "+ $*" >&2
  if [[ "$DRY_RUN" != 1 ]]; then "$@"; fi
}
warn() { echo "  ! $*" >&2; }

cd "$(dirname "$0")/.."
[[ -f CLAUDE.md && -d app ]] || { echo "Run this from the RoleReady project folder."; exit 1; }
for u in "$MOHAMED" "$ANDREW" "$ASHLEY" "$JOCLYN"; do
  [[ -n "$u" ]] || { echo "Every teammate needs a GitHub username (--mohamed, --andrew, --ashley, --joclyn)."; exit 2; }
  [[ "$u" =~ ^[A-Za-z0-9-]+$ ]] || { echo "Not a GitHub username: $u"; exit 2; }
done

echo "== Checking GitHub sign-in"
if [[ "$DRY_RUN" == 1 ]]; then
  OWNER="${OWNER:-$MOHAMED}"
else
  gh auth status >/dev/null 2>&1 || { echo "Run: gh auth login   (then gh auth setup-git)"; exit 1; }
  OWNER="$(gh api user --jq .login)"
fi
REPO="${OWNER}/${REPO_NAME}"
echo "  signed in as: ${OWNER}   repo: ${REPO}"
shopt -s nocasematch
case "$OWNER" in
  "$MOHAMED"|"$ANDREW"|"$ASHLEY"|"$JOCLYN") ;;
  *) warn "${OWNER} is not one of the four usernames you passed; the repo will live under ${OWNER}" ;;
esac
shopt -u nocasematch

echo "== Commit identity"
EMAIL="$(git config user.email || true)"
if [[ -z "$EMAIL" ]]; then
  echo "Set your commit identity first (your GitHub noreply address keeps your email private):"
  echo "  git config --global user.name  \"Your Name\""
  echo "  git config --global user.email \"ID+${OWNER}@users.noreply.github.com\"   # GitHub Settings > Emails"
  exit 1
fi
[[ "$EMAIL" == *users.noreply.github.com ]] || warn "commits will show ${EMAIL} publicly; consider your GitHub noreply address"

echo "== Filling CODEOWNERS"
if grep -q "@[A-Z]*_GITHUB" .github/CODEOWNERS; then
  run sed -i.bak -e "s/@MOHAMED_GITHUB/@${MOHAMED}/g" -e "s/@ANDREW_GITHUB/@${ANDREW}/g" \
    -e "s/@ASHLEY_GITHUB/@${ASHLEY}/g" -e "s/@JOCLYN_GITHUB/@${JOCLYN}/g" .github/CODEOWNERS
  run rm -f .github/CODEOWNERS.bak
fi

echo "== Commit (secret check first)"
if [[ ! -d .git ]]; then
  run git init -b main
fi
run git add -A
if [[ "$DRY_RUN" != 1 ]]; then
  BAD="$(git diff --cached --name-only | grep -E '(^|/)\.env$|(^|/)\.env\.floci$|(^|/)\.env\.local$|team\.local\.yaml$|(^|/)data/' || true)"
  if [[ -n "$BAD" ]]; then
    echo "Refusing to commit secret or local-only files:"; echo "$BAD"
    echo "Remove them from the folder (or fix .gitignore) and run again."; exit 1
  fi
  if command -v gitleaks >/dev/null 2>&1; then gitleaks protect --staged --redact; else warn "gitleaks not installed; CI will scan after the push"; fi
  if git rev-parse --verify HEAD >/dev/null 2>&1; then
    git diff --cached --quiet || git commit -m "Set up team repository: CODEOWNERS, PR template, contributing guide"
  else
    git commit -m "RoleReady starter: brief, Floci, IAM as code, Claude Code setup"
  fi
fi

echo "== Pushing main to ${REPO}"
if [[ "$DRY_RUN" == 1 ]]; then
  echo "+ (if ${REPO} exists) git remote add origin https://github.com/${REPO}.git && git push -u origin main" >&2
  echo "+ (if missing) gh repo create ${REPO} --${VISIBILITY} --source . --remote origin --push" >&2
elif gh repo view "$REPO" >/dev/null 2>&1; then
  git remote get-url origin >/dev/null 2>&1 || git remote add origin "https://github.com/${REPO}.git"
  if [[ -n "$(git ls-remote --heads origin main)" ]] && ! git merge-base --is-ancestor "$(git ls-remote --heads origin main | cut -f1)" HEAD 2>/dev/null; then
    echo "${REPO} already has commits that are not in this folder."
    echo "Clone it (gh repo clone ${REPO}). If the project files are not in the clone yet, copy them in"
    echo "(everything except a .git folder), then run this script again from the clone."
    exit 1
  fi
  git push -u origin main
else
  gh repo create "$REPO" "--${VISIBILITY}" --source . --remote origin --push \
    --description "Time-boxed, least-privilege access for small businesses that hire freelancers (GCLP BUILD, SDG 9)"
fi

echo "== Repository settings"
run gh api -X PATCH "repos/${REPO}" -F allow_squash_merge=true -F allow_merge_commit=false \
  -F allow_rebase_merge=false -F delete_branch_on_merge=true -F allow_auto_merge=false >/dev/null

echo "== Security features"
run gh api -X PUT "repos/${REPO}/vulnerability-alerts" || warn "could not enable Dependabot alerts"
run gh api -X PUT "repos/${REPO}/automated-security-fixes" || warn "could not enable Dependabot security fixes"
run gh api -X PATCH "repos/${REPO}" \
  -f "security_and_analysis[secret_scanning][status]=enabled" \
  -f "security_and_analysis[secret_scanning_push_protection][status]=enabled" >/dev/null \
  || warn "turn on Secret scanning and Push protection by hand in Settings (needs a public repo on GitHub Free)"

echo "== Inviting collaborators"
shopt -s nocasematch
for u in "$MOHAMED" "$ANDREW" "$ASHLEY" "$JOCLYN"; do
  if [[ "$u" == "$OWNER" ]]; then continue; fi
  run gh api -X PUT "repos/${REPO}/collaborators/${u}" >/dev/null || warn "could not invite ${u}"
done
shopt -u nocasematch

echo "== Protecting main"
PROTECTION="$(mktemp)"
trap 'rm -f "$PROTECTION"' EXIT
cat > "$PROTECTION" <<'JSON'
{
  "required_status_checks": { "strict": true, "contexts": ["tests", "secret-scan"] },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "require_code_owner_reviews": true,
    "dismiss_stale_reviews": true
  },
  "restrictions": null,
  "required_conversation_resolution": true,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
if ! run gh api -X PUT "repos/${REPO}/branches/main/protection" --input "$PROTECTION" >/dev/null; then
  warn "branch protection failed. On GitHub Free it works only on public repos;"
  warn "for a private repo the owner needs GitHub Pro (free with the GitHub Student Developer Pack if eligible)."
fi

echo
echo "Done: https://github.com/${REPO}"
echo "Teammates accept their invitation at: https://github.com/${REPO}/invitations"
echo "Then each one follows CONTRIBUTING.md."
