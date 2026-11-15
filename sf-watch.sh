#!/bin/bash
# Watcher: exit 0 (notify agent) saat challenge menunggu pts.txt, atau timeout 25 menit.
cd /data/data/com.termux/files/home/python-scripts
START=$(date +%s)
while true; do
  if [ -f c-ready ] && [ $(( $(date +%s) - $(stat -c %Y c-ready) )) -lt 85 ]; then
    echo "CHALLENGE MENUNGGU: $(cat c-ready | head -c 20)"
    exit 0
  fi
  if [ $(( $(date +%s) - START )) -gt 1500 ]; then
    echo "TIMEOUT watcher 25 menit"
    exit 0
  fi
  sleep 3
done
