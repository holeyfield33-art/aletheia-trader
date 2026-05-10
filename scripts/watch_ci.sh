#!/usr/bin/env bash
set -euo pipefail

workflow="CI"
branch="main"
repo=""
max_reruns=2

usage() {
  cat <<'EOF'
Usage: scripts/watch_ci.sh [options]

Watch the latest GitHub Actions run for a workflow, rerun failed jobs, and wait for completion.

Options:
  --workflow <name>     Workflow name (default: CI)
  --branch <name>       Branch to inspect (default: main)
  --repo <owner/name>   Optional repository override
  --max-reruns <n>      Max rerun attempts on failure (default: 2)
  -h, --help            Show this help message

Examples:
  scripts/watch_ci.sh
  scripts/watch_ci.sh --workflow CI --branch main
  scripts/watch_ci.sh --repo holeyfield33-art/aletheia-trader --max-reruns 3
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workflow)
      workflow="$2"
      shift 2
      ;;
    --branch)
      branch="$2"
      shift 2
      ;;
    --repo)
      repo="$2"
      shift 2
      ;;
    --max-reruns)
      max_reruns="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI ('gh') is required but not installed." >&2
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "GitHub CLI is not authenticated. Run: gh auth login" >&2
  exit 1
fi

repo_args=()
if [[ -n "$repo" ]]; then
  repo_args+=(--repo "$repo")
fi

get_latest_run_id() {
  gh run list "${repo_args[@]}" --workflow "$workflow" --branch "$branch" --limit 1 --json databaseId --jq '.[0].databaseId // empty'
}

get_run_conclusion() {
  local run_id="$1"
  gh run view "${repo_args[@]}" "$run_id" --json conclusion --jq '.conclusion // ""'
}

get_run_status() {
  local run_id="$1"
  gh run view "${repo_args[@]}" "$run_id" --json status --jq '.status // ""'
}

run_id="$(get_latest_run_id)"
if [[ -z "$run_id" ]]; then
  echo "No workflow runs found for workflow='$workflow' branch='$branch'."
  exit 1
fi

echo "Watching run $run_id for workflow '$workflow' on branch '$branch'..."

gh run watch "${repo_args[@]}" "$run_id"

attempt=0
while true; do
  status="$(get_run_status "$run_id")"
  conclusion="$(get_run_conclusion "$run_id")"

  echo "Run $run_id status='$status' conclusion='$conclusion'"

  if [[ "$conclusion" == "success" ]]; then
    echo "CI succeeded."
    exit 0
  fi

  if [[ "$status" != "completed" ]]; then
    gh run watch "${repo_args[@]}" "$run_id"
    continue
  fi

  if (( attempt >= max_reruns )); then
    echo "CI failed after $attempt rerun attempts." >&2
    exit 1
  fi

  attempt=$((attempt + 1))
  echo "Rerunning failed jobs (attempt $attempt/$max_reruns)..."
  rerun_output=""
  if ! rerun_output="$(gh run rerun "${repo_args[@]}" --failed "$run_id" 2>&1)"; then
    if [[ "$rerun_output" == *"Resource not accessible by integration"* ]]; then
      echo "Unable to rerun workflow due to token permissions." >&2
      echo "Grant Actions: write permission or rerun manually in GitHub UI." >&2
      exit 2
    fi

    if ! rerun_output="$(gh run rerun "${repo_args[@]}" "$run_id" 2>&1)"; then
      if [[ "$rerun_output" == *"Resource not accessible by integration"* ]]; then
        echo "Unable to rerun workflow due to token permissions." >&2
        echo "Grant Actions: write permission or rerun manually in GitHub UI." >&2
        exit 2
      fi
      echo "$rerun_output" >&2
      exit 1
    fi
  fi
  gh run watch "${repo_args[@]}" "$run_id"
done
