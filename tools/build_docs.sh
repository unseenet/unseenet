#!/usr/bin/env bash
# Build the documentation site. The UN-RFCs live in rfc/ (their canonical
# place); they are copied into docs/spec/ at build time.
#   pip install mkdocs-material "mkdocstrings[python]" ruff && tools/build_docs.sh [serve]
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf docs/spec && mkdir -p docs/spec
cp rfc/un-rfc-*.md rfc/LICENSE.md docs/spec/
cp rfc/README.md docs/spec/index.md
if [ "${1:-}" = "serve" ]; then mkdocs serve; else
  mkdocs build --strict
  cp -r site-extra/.well-known site/          # mkdocs skips dot folders
fi
