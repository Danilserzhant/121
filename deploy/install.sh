#!/usr/bin/env bash
# One-shot installer for a fresh Ubuntu/Debian VPS.
#   curl -fsSL https://raw.githubusercontent.com/Danilserzhant/121/claude/telegram-bot-atr-coins-9vmlq7/deploy/install.sh \
#     | bash -s -- <BOT_TOKEN> [OWNER_ID] [STORE_BASE64]
# Re-running updates the code and restarts the bot; the existing .env and data/ are kept.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Danilserzhant/121}"
BRANCH="${BRANCH:-claude/telegram-bot-atr-coins-9vmlq7}"
APP_DIR="${APP_DIR:-/opt/atr-bot}"
BOT_TOKEN="${1:-${BOT_TOKEN:-}}"
OWNER_ID="${2:-${OWNER_ID:-}}"
STORE_B64="${3:-}"

log() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }

if [ -z "$BOT_TOKEN" ] && [ ! -f "$APP_DIR/.env" ]; then
  echo "Usage: install.sh <BOT_TOKEN> [OWNER_ID] [STORE_BASE64]" >&2
  exit 1
fi

log "Packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git curl ca-certificates >/dev/null

if ! command -v docker >/dev/null 2>&1; then
  log "Docker"
  curl -fsSL https://get.docker.com | sh >/dev/null
fi
if ! docker compose version >/dev/null 2>&1; then
  apt-get install -y -qq docker-compose-plugin >/dev/null
fi
systemctl enable --now docker >/dev/null 2>&1 || true

log "Code -> $APP_DIR ($BRANCH)"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch -q origin "$BRANCH"
  git -C "$APP_DIR" checkout -q "$BRANCH"
  git -C "$APP_DIR" reset -q --hard "origin/$BRANCH"
else
  git clone -q --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"
mkdir -p data

if [ ! -f .env ]; then
  log ".env"
  cp .env.example .env
  sed -i "s|^BOT_TOKEN=.*|BOT_TOKEN=$BOT_TOKEN|" .env
  [ -n "$OWNER_ID" ] && sed -i "s|^OWNER_ID=.*|OWNER_ID=$OWNER_ID|" .env
  sed -i "s|^EXCHANGE=.*|EXCHANGE=binance_futures|" .env
  chmod 600 .env
else
  log ".env already exists, keeping it"
fi

if [ -n "$STORE_B64" ] && [ ! -f data/store.json ]; then
  log "Restoring users / roles / subscriptions"
  echo "$STORE_B64" | base64 -d > data/store.json
fi

log "Timezone check (candles are UTC, this only affects logs)"
timedatectl set-timezone UTC >/dev/null 2>&1 || true

log "Build & start"
docker compose up -d --build --remove-orphans

log "Waiting for the bot"
sleep 8
docker compose logs --tail=15 atr-bot

cat <<MSG

Done. Useful commands (run in $APP_DIR):
  docker compose logs -f --tail=100 atr-bot   # live log
  docker compose restart atr-bot              # restart
  bash deploy/install.sh                      # update to the latest code
MSG
