#!/bin/sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
export PATH="$ROOT/runtimes/node/bin:$ROOT/cache/cargo/bin:$PATH"
export npm_config_cache="$ROOT/cache/npm"
export CARGO_HOME="$ROOT/cache/cargo"
export RUSTUP_HOME="$ROOT/runtimes/rust"
export CARGO_TARGET_DIR="$ROOT/cache/tauri-target"
export TMPDIR="$ROOT/tmp"
export PLAYWRIGHT_BROWSERS_PATH="$ROOT/runtimes/playwright"
mkdir -p "$TMPDIR"
cd "$ROOT"
exec "$ROOT/runtimes/node/bin/node" "$ROOT/runtimes/node/lib/node_modules/npm/bin/npm-cli.js" "$@"
