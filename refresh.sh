#!/bin/sh
# Pull the latest Arena data and prices, then rebuild index.html.
# Needs uv (for pyarrow) and python3. Set OPENROUTER_API_KEY to include speed data.
set -e
cd "$(dirname "$0")"
uv run --with pyarrow python -I scripts/fetch_arena.py
# prices (models.dev + OpenRouter API); cached for 6h, falls back to the cache when offline
python3 -I scripts/fetch_prices.py || python3 -I scripts/fetch_prices.py --offline || echo "price fetch failed; building with the committed data/prices.json"
python3 -I scripts/build_page.py
echo "Open: $PWD/index.html"
