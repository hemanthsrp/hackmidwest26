#!/usr/bin/env sh
set -eu

symbol=${1:-}
symbol=$(printf '%s' "$symbol" | tr '[:lower:]' '[:upper:]')
case "$symbol" in
  ''|*[!A-Z]*) valid=false ;;
  *) valid=true ;;
esac
if [ "$valid" != true ] || [ "${#symbol}" -gt 5 ]; then
  printf '%s\n' "Usage: $0 SYMBOL (one to five letters)" >&2
  exit 2
fi

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"
docker compose -f compose.frontend.yml exec -T scraper-analysis python -c '
import json, sys, urllib.parse, urllib.request
symbol = sys.argv[1]
query = urllib.parse.urlencode({
    "symbol": symbol,
    "live": "true",
    "fallback": "false",
    "tag": "false",
    "judge": "false",
})
request = urllib.request.Request(
    f"http://127.0.0.1:8001/ingest/run?{query}", data=b"", method="POST"
)
with urllib.request.urlopen(request, timeout=240) as response:
    result = json.load(response)
print(json.dumps({key: result.get(key) for key in ("symbol", "count", "sources", "warnings")}, indent=2))
' "$symbol"
