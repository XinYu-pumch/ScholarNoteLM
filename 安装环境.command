#!/bin/bash
# Bootstrap only with macOS system tools; no Git, Python, Homebrew or Xcode needed.
set -euo pipefail
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
cd "$ROOT"
finish() { code=$?; if [ "$code" != 0 ]; then echo "安装未完成。请根据上方提示处理后重试，已下载内容会保留。"; fi; if [ -t 0 ]; then read -r -p '按回车关闭窗口…' _answer || true; fi; }
trap finish EXIT
if [ "$(/usr/bin/uname -s)" != Darwin ] || [ "$(/usr/bin/uname -m)" != arm64 ]; then echo '需要 Apple Silicon Mac，请在原生终端中运行。'; exit 1; fi
major=$(/usr/bin/sw_vers -productVersion); major=${major%%.*}
if [ "$major" -lt 14 ]; then echo '需要 macOS 14 或更新版本。'; exit 1; fi
if [ "$#" -eq 0 ]; then set -- --apply; fi
if [ -x "$ROOT/runtimes/downloader/bin/python" ]; then
  # The installer itself decides whether the existing environment is managed.
  "$ROOT/runtimes/downloader/bin/python" "$ROOT/scripts/setup-runtime.py" --uv "$ROOT/cache/bootstrap/uv-aarch64-apple-darwin/uv" "$@"
  exit $?
fi
if [ -e runtimes ] && [ ! -f runtimes/install-state.json ]; then echo '检测到已有运行环境，拒绝覆盖。请在干净源码目录安装。'; exit 1; fi
# Scope macOS system proxies to this installer. Explicit user variables win.
proxy_state=$(/usr/sbin/scutil --proxy)
proxy_value() { /usr/bin/awk -v key="$1" '$1==key && $2==":" {print $3; exit}' <<< "$proxy_state"; }
if [ -z "${HTTPS_PROXY:-}${https_proxy:-}" ] && [ "$(proxy_value HTTPSEnable)" = 1 ]; then export HTTPS_PROXY="http://$(proxy_value HTTPSProxy):$(proxy_value HTTPSPort)"; fi
if [ -z "${HTTP_PROXY:-}${http_proxy:-}" ] && [ "$(proxy_value HTTPEnable)" = 1 ]; then export HTTP_PROXY="http://$(proxy_value HTTPProxy):$(proxy_value HTTPPort)"; fi
for directory in cache cache/bootstrap; do
  if [ -L "$ROOT/$directory" ]; then echo "拒绝使用符号链接安装缓存：$directory"; exit 1; fi
done
BOOT="$ROOT/cache/bootstrap"
mkdir -p "$BOOT"
archive="$BOOT/uv-aarch64-apple-darwin.tar.gz"
expected=d0fb047593122746c7529960f8efd5d7d10d2cb230302f71158e9765ad37727b
if [ ! -f "$archive" ]; then
  /usr/bin/curl --fail --location --retry 3 --connect-timeout 30 'https://github.com/astral-sh/uv/releases/download/0.6.6/uv-aarch64-apple-darwin.tar.gz' -o "$archive.part"
  mv "$archive.part" "$archive"
fi
actual=$(LC_ALL=C /usr/bin/shasum -a 256 "$archive"); actual=${actual%% *}
if [ "$actual" != "$expected" ]; then echo 'uv 下载校验失败，请删除 cache/bootstrap 中的 uv 压缩包后重试。'; exit 1; fi
LC_ALL=C /usr/bin/tar -xzf "$archive" -C "$BOOT"
export UV_PYTHON_INSTALL_DIR="$BOOT/python" UV_CACHE_DIR="$ROOT/cache/uv" UV_NO_CONFIG=1
"$BOOT/uv-aarch64-apple-darwin/uv" run --no-project --python-preference only-managed --python cpython-3.12.9-macos-aarch64-none "$ROOT/scripts/setup-runtime.py" --uv "$BOOT/uv-aarch64-apple-darwin/uv" "$@"
