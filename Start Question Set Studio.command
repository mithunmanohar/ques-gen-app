#!/usr/bin/env bash
# macOS: double-click this file in Finder to set up and start Question Set Studio.
# (If macOS says it can't be opened, right-click it and choose Open once.)
cd "$(dirname "$0")" || exit 1
./run.sh "$@"
status=$?
echo ""
read -r -p "Press Enter to close this window..." _
exit $status
