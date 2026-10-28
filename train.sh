#!/bin/sh
# Train, evaluate and promote a model with the bucket credentials from .env:
#   ./train.sh <model_id> [train.train options, e.g. --epochs 4 --local --limit 1000]
cd "$(dirname "$0")" && exec uv run --env-file .env --project train python -m train.pipeline "$@"
