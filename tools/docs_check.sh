#!/usr/bin/env bash
# The docs this repository keeps (docs/), checked strictly as one small site,
# with the UN-RFCs copied in as on unseenet.org. The site itself is built by
# unseenet/unseenet-docs, which gathers these pages (#547).
#   pip install mkdocs-material "mkdocstrings[python]" && tools/docs_check.sh [serve]
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf docs/spec && mkdir -p docs/spec
cp rfc/un-rfc-*.md rfc/LICENSE.md docs/spec/
cp rfc/README.md docs/spec/index.md
if [ "${1:-}" = "serve" ]; then mkdocs serve; else mkdocs build --strict; fi
