#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TARGET_ROOT="${NAS_TARGET_ROOT:-/Volumes/docker/yishu-canvas/yishu-canvas-fnos}"
NAS_SSH_HOST="${NAS_SSH_HOST:-yishu-nas}"
NAS_SSH_USER="${NAS_SSH_USER:-}"
NAS_DEPLOY_ROOT="${NAS_DEPLOY_ROOT:-/vol1/1000/docker/yishu-canvas/yishu-canvas-fnos}"
REBUILD="${NAS_REBUILD:-0}"
DRY_RUN="${NAS_DRY_RUN:-0}"

if [ ! -d "${TARGET_ROOT}" ]; then
  cat >&2 <<EOF
NAS target does not exist: ${TARGET_ROOT}

Mount the NAS SMB share first, for example:
  Finder -> Go -> Connect to Server -> smb://192.168.1.3/docker

Then rerun this script, or set NAS_TARGET_ROOT to the mounted deploy directory.
EOF
  exit 1
fi

case "${TARGET_ROOT}" in
  */yishu-canvas-fnos) ;;
  *)
    echo "Refusing to mirror into unexpected target: ${TARGET_ROOT}" >&2
    exit 1
    ;;
esac

echo "Syncing source:"
echo "  from: ${SOURCE_ROOT}"
echo "  to:   ${TARGET_ROOT}"
echo "Protected runtime paths:"
printf '  %s\n' \
  "deploy/fnos/.env" \
  "deploy/fnos/api-env/" \
  "deploy/fnos/assets/" \
  "deploy/fnos/data/" \
  "deploy/fnos/output/" \
  "deploy/fnos/team-assets/" \
  "data/" \
  "output/" \
  "assets/"

rsync_args=(-a --delete)
if [ "${DRY_RUN}" = "1" ]; then
  rsync_args+=(-n --itemize-changes)
  echo "Dry run enabled; no files will be changed."
fi

COPYFILE_DISABLE=1 rsync "${rsync_args[@]}" \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude '.DS_Store' \
  --exclude '._*' \
  --exclude '.codex-speedtest-current/' \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude 'tmp/' \
  --exclude 'api-env/' \
  --exclude 'data/' \
  --exclude 'output/' \
  --exclude 'team-assets/' \
  --exclude 'assets/' \
  --exclude '.env' \
  --exclude '.env.*' \
  --exclude '*.log' \
  --exclude '*.pyc' \
  --exclude '*.pyo' \
  --exclude 'DEPLOYED_COMMIT.txt' \
  "${SOURCE_ROOT}/" "${TARGET_ROOT}/"

commit="$(git -C "${SOURCE_ROOT}" rev-parse --short HEAD)"
if [ "${DRY_RUN}" = "1" ]; then
  echo "Dry run complete for commit ${commit}"
else
  printf '%s\n' "${commit}" > "${TARGET_ROOT}/DEPLOYED_COMMIT.txt"
  echo "NAS source sync complete at commit ${commit}"
fi

if [ "${REBUILD}" = "1" ] && [ "${DRY_RUN}" != "1" ]; then
  ssh_target="${NAS_SSH_HOST}"
  if [ -n "${NAS_SSH_USER}" ]; then
    ssh_target="${NAS_SSH_USER}@${NAS_SSH_HOST}"
  fi
  echo "Rebuilding Docker on ${ssh_target}:${NAS_DEPLOY_ROOT}"
  echo "Docker rebuild order: stop -> clean containers -> build without cache -> force recreate"
  ssh "${ssh_target}" \
    "set -e
     cd '${NAS_DEPLOY_ROOT}/deploy/fnos'
     docker compose -p yishu-canvas stop
     docker compose -p yishu-canvas rm -f
     docker compose -p yishu-canvas build --no-cache
     docker compose -p yishu-canvas up -d --force-recreate
     docker compose -p yishu-canvas ps"
fi
