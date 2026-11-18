#!/usr/bin/env bash
# setup_video_cameras.sh
# Creates up to 5 v4l2loopback devices for per-call video echo.
# Run once with root: sudo bash setup_video_cameras.sh
set -euo pipefail

COUNT=${1:-5}
START=${2:-10}
LABEL="BotVideo"

if ! command -v modprobe >/dev/null 2>&1; then
  echo "modprobe not found"
  exit 1
fi

if ! lsmod | grep -q "^v4l2loopback"; then
  modprobe v4l2loopback devices="${COUNT}" video_nr="${START},$((${START}+1)),$((${START}+2)),$((${START}+3)),$((${START}+4))" card_label="${LABEL}" exclusive_caps=1
fi

for i in $(seq 0 $((COUNT-1))); do
  dev="/dev/video$((START+i))"
  if [ ! -e "$dev" ]; then
    echo "Expected device $dev not found"
    exit 1
  fi
  chmod 666 "$dev"
done

echo "v4l2loopback devices ready:"
ls -la /dev/video* | grep -E "video($(seq -s '|' $START $((START+COUNT-1)))|$)" || true
