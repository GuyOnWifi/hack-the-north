#!/bin/bash
# Run this after you've taken the photos. Tells you what's usable.
cd "$(dirname "$0")/.."
export SAM2_CHECKPOINT="$PWD/data/models/sam2.1_hiera_small.pt"
export SAM2_CONFIG=configs/sam2.1/sam2.1_hiera_s.yaml
echo "=== photo quality ==="
.venv/bin/python scripts/check_photos.py data/real/
echo
echo "=== running the pipeline on your spread photos ==="
.venv/bin/python -m vision.pipeline data/real/spread/ -o data/real/inventory.json --debug data/real/debug
echo
echo "Look at the overlays:  open data/real/debug/"
