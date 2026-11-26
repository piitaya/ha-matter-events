#!/bin/sh
# Copy the integration to a Home Assistant host over SSH (the files there belong to root,
# hence sudo). Restart Core afterwards: Python modules and translations are read at startup.
#
#   tools/deploy.sh            # host "home" from ~/.ssh/config
#   tools/deploy.sh hometest   # another host
set -e
cd "$(dirname "$0")/.."
host="${1:-home}"
rsync -rlpt --delete --exclude '__pycache__' --exclude '*.pyc' --rsync-path='sudo rsync' \
  custom_components/matter_events/ "$host:/config/custom_components/matter_events/"
