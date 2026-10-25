#!/usr/bin/env bash
# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
#
# Download the detection model into src/data/models/omz/ (skipped when already present and valid).
#   ./download_models.sh
#
# person-detection-retail-0013 (FP32) from Open Model Zoo, Apache-2.0. The URL is pinned to a release
# and every file is checked against a SHA-256, so a changed or truncated download is rejected.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
NAME=person-detection-retail-0013
BASE=${MODEL_BASE_URL:-https://storage.openvinotoolkit.org/repositories/open_model_zoo/2023.0/models_bin/1}
DEST=$HERE/models/omz/$NAME/FP32

declare -A SHA256=(
  [$NAME.xml]=33acc96a73898256a127a53af71b6bfb169df83bd514984b01beacbcf7b2cc04
  [$NAME.bin]=f3731a76de6a26ef7f380a08831bc13d74fc1e6ae774fd9ea30267a487084f2c
)

valid() { [ -f "$1" ] && [ "$(sha256sum "$1" | cut -d' ' -f1)" = "$2" ]; }

mkdir -p "$DEST"
for f in "${!SHA256[@]}"; do
  if valid "$DEST/$f" "${SHA256[$f]}"; then
    continue
  fi
  echo "downloading $f"
  curl -fsSL --retry 3 --connect-timeout 15 -o "$DEST/$f.part" "$BASE/$NAME/FP32/$f" \
    || { rm -f "$DEST/$f.part"; echo "error: cannot download $BASE/$NAME/FP32/$f" >&2; exit 1; }
  if ! valid "$DEST/$f.part" "${SHA256[$f]}"; then
    rm -f "$DEST/$f.part"
    echo "error: $f does not match the expected SHA-256" >&2
    exit 1
  fi
  mv "$DEST/$f.part" "$DEST/$f"
done
echo "models ready: $DEST"
