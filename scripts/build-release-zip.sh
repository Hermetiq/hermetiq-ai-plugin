#!/usr/bin/env bash
#
# Build one skill-only release zip per supported manual-install skill.
#
# Produces:
#   hermetiq-ai-plugin-<version>.zip
#   hermetiq-on-prem-gke-install-<version>.zip
#
# Each archive has exactly one top-level skill directory, as expected by
# Claude Desktop. Development-only evals are excluded.
#
# Usage:
#   scripts/build-release-zip.sh <version>
#
# Example:
#   scripts/build-release-zip.sh v0.9.2-beta
#
# Output:
#   tmp/release-<version>/*.zip
#
# Upload with:
#   gh release upload <version> \
#     tmp/release-<version>/hermetiq-ai-plugin-<version>.zip \
#     tmp/release-<version>/hermetiq-on-prem-gke-install-<version>.zip \
#     --repo Hermetiq/hermetiq-ai-plugin

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <version>" >&2
  echo "example: $0 v0.9.2-beta" >&2
  exit 1
fi

VERSION="$1"

RELEASE_TAG_PATTERN='^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?(\+[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?$'
if [[ ! "$VERSION" =~ $RELEASE_TAG_PATTERN ]]; then
  echo "error: version must be a valid release tag such as v0.9.6-beta" >&2
  exit 1
fi

# Resolve repo root from this script's location so the script works from any cwd.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

SKILLS_ROOT="$REPO_ROOT/plugins/hermetiq/skills"
TMP_ROOT="$REPO_ROOT/tmp"
STAGE_DIR="$TMP_ROOT/release-$VERSION"
SUPPORTED_SKILLS=("hermetiq" "on-prem-gke-install")

for skill in "${SUPPORTED_SKILLS[@]}"; do
  if [[ ! -d "$SKILLS_ROOT/$skill" ]]; then
    echo "error: skill source not found at $SKILLS_ROOT/$skill" >&2
    exit 1
  fi
done

# Refuse symlinked deletion roots, then verify the normalized stage path is the
# expected immediate child of this checkout's canonical tmp root. Delete the
# literal checked path, never the resolved target of a symlink.
if [[ -L "$TMP_ROOT" ]]; then
  echo "error: refusing to use path because tmp root is a symlink: $TMP_ROOT" >&2
  exit 1
fi
if [[ -L "$STAGE_DIR" ]]; then
  echo "error: refusing to recreate path because stage path is a symlink: $STAGE_DIR" >&2
  exit 1
fi
CANONICAL_TMP_ROOT="$(realpath -m -- "$TMP_ROOT")"
CANONICAL_STAGE_DIR="$(realpath -m -- "$STAGE_DIR")"
EXPECTED_CANONICAL_STAGE="$CANONICAL_TMP_ROOT/release-$VERSION"
if [[ "$CANONICAL_STAGE_DIR" != "$EXPECTED_CANONICAL_STAGE" ]]; then
  echo "error: refusing to recreate stage path outside $CANONICAL_TMP_ROOT: $CANONICAL_STAGE_DIR" >&2
  exit 1
fi
if [[ -e "$STAGE_DIR" ]]; then
  echo "Recreating existing stage directory: $STAGE_DIR"
  find "$STAGE_DIR" -mindepth 1 -maxdepth 2 -printf '  %P\n' | sort
fi
rm -rf -- "$STAGE_DIR"
mkdir -p "$STAGE_DIR"

for skill in "${SUPPORTED_SKILLS[@]}"; do
  cp -R "$SKILLS_ROOT/$skill" "$STAGE_DIR/"
  if [[ -d "$STAGE_DIR/$skill/evals" ]]; then
    rm -rf -- "$STAGE_DIR/$skill/evals"
  fi

  if [[ "$skill" == "hermetiq" ]]; then
    zip_name="hermetiq-ai-plugin-$VERSION.zip"
  else
    zip_name="hermetiq-$skill-$VERSION.zip"
  fi

  # Zip from inside the stage dir so each archive has one skill at its root.
  ( cd "$STAGE_DIR" && zip -r "$zip_name" "$skill/" )
  rm -rf -- "$STAGE_DIR/$skill"

  echo
  echo "Built: $STAGE_DIR/$zip_name"
  echo
  echo "Contents:"
  unzip -l "$STAGE_DIR/$zip_name"
done
echo
echo "Upload with:"
echo "  gh release upload $VERSION \\"
echo "    $STAGE_DIR/hermetiq-ai-plugin-$VERSION.zip \\"
echo "    $STAGE_DIR/hermetiq-on-prem-gke-install-$VERSION.zip \\"
echo "    --repo Hermetiq/hermetiq-ai-plugin"
