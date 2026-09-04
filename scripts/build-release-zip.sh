#!/usr/bin/env bash
#
# Build a skill-only release zip for upload to a GitHub release.
#
# Produces a zip with the same structure as v0.9.0-beta:
#   hermetiq/SKILL.md
#   hermetiq/references/*.md
#
# The evals/ directory is excluded — it's a dev-time artifact and not needed
# by Claude Desktop users installing the skill.
#
# Usage:
#   scripts/build-release-zip.sh <version>
#
# Example:
#   scripts/build-release-zip.sh v0.9.2-beta
#
# Output:
#   tmp/release-<version>/hermetiq-ai-plugin-<version>.zip
#
# Upload with:
#   gh release upload <version> \
#     tmp/release-<version>/hermetiq-ai-plugin-<version>.zip \
#     --repo Hermetiq/hermetiq-ai-plugin

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <version>" >&2
  echo "example: $0 v0.9.2-beta" >&2
  exit 1
fi

VERSION="$1"

# Resolve repo root from this script's location so the script works from any cwd.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

SKILL_SRC="$REPO_ROOT/plugins/hermetiq/skills/hermetiq"
STAGE_DIR="$REPO_ROOT/tmp/release-$VERSION"
ZIP_NAME="hermetiq-ai-plugin-$VERSION.zip"
ZIP_PATH="$STAGE_DIR/$ZIP_NAME"

if [[ ! -d "$SKILL_SRC" ]]; then
  echo "error: skill source not found at $SKILL_SRC" >&2
  exit 1
fi

# Fresh stage dir each run so re-builds don't pick up stale files.
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"

# Copy the skill tree, then strip dev-only directories.
cp -R "$SKILL_SRC" "$STAGE_DIR/"
rm -rf "$STAGE_DIR/hermetiq/evals"

# Zip from inside the stage dir so the archive paths start with `hermetiq/`,
# not a longer absolute path.
( cd "$STAGE_DIR" && zip -r "$ZIP_NAME" hermetiq/ )

echo
echo "Built: $ZIP_PATH"
echo
echo "Contents:"
unzip -l "$ZIP_PATH"
echo
echo "Upload with:"
echo "  gh release upload $VERSION \\"
echo "    $ZIP_PATH \\"
echo "    --repo Hermetiq/hermetiq-ai-plugin"
