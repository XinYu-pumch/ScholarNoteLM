#!/bin/sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
export PATH="$ROOT/cache/cargo/bin:$ROOT/runtimes/node/bin:$PATH"
export CARGO_HOME="$ROOT/cache/cargo"
export RUSTUP_HOME="$ROOT/runtimes/rust"
export CARGO_TARGET_DIR="$ROOT/cache/tauri-target"
export TMPDIR="$ROOT/tmp"
cd "$ROOT"
exec "$ROOT/cache/cargo/bin/cargo" "$@"
