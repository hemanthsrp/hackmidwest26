#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
env_file="$repo_root/.env"

if [ -e "$env_file" ]; then
  printf '%s\n' "Refusing to overwrite $env_file. Keep the existing local configuration." >&2
  exit 1
fi

umask 077
auth_secret=$(openssl rand -base64 32 | tr -d '\n')
service_secret=$(openssl rand -base64 32 | tr -d '\n')
broker_key=$(openssl rand -base64 32 | tr -d '\n')
cat > "$env_file" <<EOF
AUTH_SECRET=$auth_secret
SERVICE_ASSERTION_SECRET=$service_secret
BROKER_ENCRYPTION_KEY=$broker_key
AUTH_URL=http://localhost:3100
ROBINHOOD_REDIRECT_URI=http://localhost:3100/api/broker/robinhood/callback
ROBINHOOD_MCP_ENABLED=true
LOCAL_ACCOUNT_AUTH=true
HOST_PORT=3100
RESEARCH_API_PORT=8100
DATABASE_PORT=5433
ALLOW_REGISTRATION=false
PUBLIC_LIVE_RESEARCH=true
EOF
chmod 600 "$env_file"

printf '%s\n' "Created a private, ignored local .env with fresh secrets." \
  "Start the local beta topology with:" \
  "  docker compose -f compose.frontend.yml up --build -d" \
  "Then ingest a symbol with ./scripts/ingest-local-live.sh AAPL and open http://localhost:3100/stocks/AAPL." \
  "Registration stays closed until email delivery is configured."
