#!/usr/bin/env bash
# =============================================================================
# record-demo.sh — Record a demo video of Alien Monitor
#
# Prerequisites:
#   - ffmpeg (for screen recording)
#   - A running Alien Monitor (./start.sh in another terminal)
#
# Output: docs/demo.mp4
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT="$ROOT/docs/demo.mp4"
DURATION="${1:-60}"  # 60 seconds default

if ! command -v ffmpeg &>/dev/null; then
  echo "ERROR: ffmpeg is required. Install: apt install ffmpeg"
  echo ""
  echo "Alternative: Use OBS Studio or your OS screen recorder to capture:"
  echo "  1. Open http://localhost:5173 in browser"
  echo "  2. Record the following sequence:"
  echo "     - Rotate 3D graph (click + drag)"
  echo "     - Zoom into hub (scroll)"
  echo "     - Click several nodes to inspect metrics"
  echo "     - Open AI Assistant and ask a question"
  echo "     - Toggle TEST/LIVE mode"
  echo "     - Change themes (CY/MG/GR)"
  echo "     - Watch transaction flow"
  echo "     - Adjust PULSE slider"
  echo "  3. Save video to docs/demo.mp4"
  exit 1
fi

echo "Recording ${DURATION}s demo video..."
echo "Make sure Alien Monitor is running at http://localhost:5173"
echo "Press Ctrl+C to stop early."

# Record screen using ffmpeg x11grab
ffmpeg -y \
  -f x11grab -video_size 1920x1080 -framerate 30 -i :0.0 \
  -t "$DURATION" \
  -c:v libx264 -preset fast -crf 23 \
  -pix_fmt yuv420p \
  "$OUTPUT" 2>&1

echo ""
echo "Demo video saved to: $OUTPUT"
echo "Upload this to your docs/README."
