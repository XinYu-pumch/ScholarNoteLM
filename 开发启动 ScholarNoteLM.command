#!/bin/sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$ROOT"
printf '\nScholarNoteLM 开发版：界面自动刷新，Rust 修改自动编译重启。\n请保留此终端，按 Control+C 退出。\n\n'
exec "$ROOT/scripts/npm-local.sh" run desktop
