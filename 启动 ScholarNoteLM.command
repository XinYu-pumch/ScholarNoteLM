#!/bin/sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
APP="$ROOT/dist/macos/ScholarNoteLM.app"
if [ ! -d "$APP" ]; then
  echo "未找到桌面应用，请先运行：./scripts/npm-local.sh run desktop:build -- --debug --bundles app"
  exit 1
fi
open "$APP"
