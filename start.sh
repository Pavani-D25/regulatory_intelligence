#!/usr/bin/env bash
# RegTrack India - one command to set up and start everything (macOS, Linux, Git Bash on Windows).
#
#   ./start.sh                          first run: sets everything up, asks where the data should come from, starts it all
#   ./start.sh --snapshot FILE.dump     load a database snapshot from a teammate, then start
#   ./start.sh --files FILE.zip         also add the stored PDFs from a teammate's files zip
#   ./start.sh --data seed|crawl|skip   choose the data source without being asked
#   ./start.sh --no-schedule            do not start the 6-hour auto-sync
#   ./start.sh --stop                   stop the API, auto-sync and portal (the database keeps running)
#
# Needs: Python 3.11+, Docker, Node.js 18+. Logs: data/logs/*.log
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"
RUN="$ROOT/data/run"; LOGS="$ROOT/data/logs"
SNAPSHOT=""; FILES=""; DATA=""; SCHEDULE=1; OPEN=1

step() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }
ok()   { printf '    \033[32m%s\033[0m\n' "$1"; }
info() { printf '    %s\n' "$1"; }
fail() { printf '\n  \033[31m! %s\033[0m\n\n' "$1"; exit 1; }

stop_all() {
  local any=0
  for f in "$RUN"/*.pid; do
    [ -e "$f" ] || continue
    pid="$(cat "$f")"
    if kill -0 "$pid" 2>/dev/null; then kill "$pid" 2>/dev/null || true; info "stopped $(basename "$f" .pid) ($pid)"; any=1; fi
    rm -f "$f"
  done
  # anything started another way (or a child left behind)
  case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*)  # Git Bash ids are not Windows process ids: let start.ps1 find them by command line
      powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(cygpath -w "$ROOT/start.ps1")" -Stop >/dev/null 2>&1 || true ;;
  esac
  if command -v pkill >/dev/null 2>&1; then
    pkill -f "regtrack.cli (api|schedule)" 2>/dev/null && any=1 || true
    pkill -f "$ROOT/dashboard/node_modules" 2>/dev/null && any=1 || true
  fi
  [ "$any" = 1 ] || info "nothing was running"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --snapshot) SNAPSHOT="$2"; shift 2 ;;
    --files) FILES="$2"; shift 2 ;;
    --data) DATA="$2"; shift 2 ;;
    --no-schedule) SCHEDULE=0; shift ;;
    --no-browser) OPEN=0; shift ;;
    --stop) step "Stopping RegTrack"; stop_all; exit 0 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) fail "unknown option $1 (see ./start.sh --help)" ;;
  esac
done

printf '\n  RegTrack India - setup and start\n  %s\n' "$ROOT"

# ---------------------------------------------------------------- 1. tools
step "Checking tools"
SYSPY=""
for c in python3.13 python3.12 python3.11 python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then SYSPY="$c"; break; fi
done
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; elif [ -x .venv/Scripts/python.exe ]; then PY=.venv/Scripts/python.exe; else PY=""; fi
[ -n "$SYSPY" ] || [ -n "$PY" ] || fail "Python 3.11 or newer is needed: https://www.python.org/downloads/"
command -v docker >/dev/null || fail "Docker is needed: https://www.docker.com/products/docker-desktop/"
command -v npm >/dev/null || fail "Node.js 18 or newer is needed: https://nodejs.org/"
ok "Python, Docker and Node.js found"
if ! docker info >/dev/null 2>&1; then
  info "Docker is not running - trying to start it"
  if [ "$(uname)" = "Darwin" ]; then open -a Docker || true; else docker desktop start >/dev/null 2>&1 || true; fi
  for _ in $(seq 1 60); do sleep 3; docker info >/dev/null 2>&1 && break; done
  docker info >/dev/null 2>&1 || fail "Docker did not start. Start Docker, wait until it is running, then run this again."
fi
ok "Docker engine running"

# ---------------------------------------------------------------- 2. settings
step "Settings (.env)"
if [ ! -f .env ]; then cp .env.example .env; ok "created .env from .env.example"
  info "AI features stay off until LLM_BASE_URL and EMBED_MODEL are set in .env (LM Studio address)."
else ok ".env exists"; fi
[ -f dashboard/.env ] || { cp dashboard/.env.example dashboard/.env; ok "created dashboard/.env"; }

# ---------------------------------------------------------------- 3. Python environment
step "Python environment"
if [ -z "$PY" ]; then
  info "creating .venv"; "$SYSPY" -m venv .venv
  if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=.venv/Scripts/python.exe; fi
fi
if [ ! -f .venv/.installed ] || [ pyproject.toml -nt .venv/.installed ]; then
  info "installing Python packages (first time: a few minutes)"
  "$PY" -m pip install --upgrade pip --quiet
  "$PY" -m pip install -e ".[dev]" --quiet || fail "pip install failed"
  case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) ;;  # Windows: the crawlers use the installed Edge or Chrome
    *) if ! command -v google-chrome >/dev/null 2>&1 && [ ! -d "/Applications/Google Chrome.app" ]; then
         info "installing a headless browser for the ARAI and e-Gazette crawlers"
         "$PY" -m playwright install chromium >/dev/null 2>&1 || info "(browser install failed - crawling ARAI/e-Gazette will need Chrome)"
       fi ;;
  esac
  date > .venv/.installed; ok "packages installed"
else ok "packages up to date"; fi

# ---------------------------------------------------------------- 4. database
step "Database (PostgreSQL 16 + pgvector in Docker)"
if [ -n "$(docker ps -a --filter 'name=^regtrack-db$' --format '{{.Names}}')" ]; then docker start regtrack-db >/dev/null
else docker compose up -d db || fail "could not start the database container"; fi
for _ in $(seq 1 40); do
  [ "$(docker inspect -f '{{.State.Health.Status}}' regtrack-db 2>/dev/null)" = "healthy" ] && break; sleep 2
done
[ "$(docker inspect -f '{{.State.Health.Status}}' regtrack-db 2>/dev/null)" = "healthy" ] || fail "the database did not become ready (docker logs regtrack-db)"
ok "database ready on localhost:5432"
if [ -n "$SNAPSHOT" ]; then
  [ -f "$SNAPSHOT" ] || fail "snapshot not found: $SNAPSHOT"
  "$PY" -m regtrack.cli snapshot-import "$SNAPSHOT" --yes || fail "snapshot import failed"
fi
"$PY" -m regtrack.cli migrate || fail "database migration failed"
if [ -n "$FILES" ]; then [ -f "$FILES" ] || fail "files zip not found: $FILES"; "$PY" -m regtrack.cli snapshot-import "$FILES"; fi

# ---------------------------------------------------------------- 5. data
step "Data"
DOCS="$(docker exec regtrack-db psql -U regtrack -d regtrack -tAc 'select count(*) from document' 2>/dev/null | tr -d '[:space:]')"
if [ "${DOCS:-0}" -gt 0 ] 2>/dev/null; then ok "$DOCS documents in the database"
else
  SEED="$("$PY" -c 'from regtrack.config import get_settings; print(get_settings().seed_corpus_dir)')"
  CHOICE="$DATA"
  if [ -z "$CHOICE" ]; then
    printf '\n    \033[33mThe database is empty. Where should the data come from?\033[0m\n'
    echo "      1  A snapshot file from a teammate (fastest: about a minute)"
    echo "      2  The seed corpus folder $SEED (about 45 minutes)"
    echo "      3  Download live from MoRTH, ARAI, e-Gazette and India Code (about an hour)"
    echo "      4  Skip for now"
    read -r -p "    Choose 1-4: " ans
    case "$ans" in 1) CHOICE=snapshot ;; 2) CHOICE=seed ;; 3) CHOICE=crawl ;; *) CHOICE=skip ;; esac
  fi
  case "$CHOICE" in
    snapshot) read -r -p "    Path to the .dump file: " f; [ -f "$f" ] || fail "not found: $f"
              "$PY" -m regtrack.cli snapshot-import "$f" --yes; "$PY" -m regtrack.cli migrate ;;
    seed)     [ -d "$SEED" ] || fail "seed corpus folder not found: $SEED (set SEED_CORPUS_DIR in .env)"
              "$PY" -m regtrack.cli import-seed; "$PY" -m regtrack.cli run ;;
    crawl)    info "downloading from the four sources and processing - leave this open"; "$PY" -m regtrack.cli crawl ;;
    *)        info "skipped - the portal will be empty until data is loaded" ;;
  esac
fi

# ---------------------------------------------------------------- 6. portal packages
step "Portal (React + Vite)"
if [ ! -d dashboard/node_modules ] || [ dashboard/package.json -nt dashboard/node_modules ]; then
  info "installing portal packages (first time: a minute)"
  (cd dashboard && npm install --no-fund --no-audit) || fail "npm install failed"
fi
ok "portal packages ready"

# ---------------------------------------------------------------- 7. start
step "Starting"
mkdir -p "$RUN" "$LOGS"
stop_all >/dev/null
nohup "$PY" -m regtrack.cli api < /dev/null > "$LOGS/api.log" 2>&1 & echo $! > "$RUN/api.pid"
if [ "$SCHEDULE" = 1 ]; then nohup "$PY" -m regtrack.cli schedule < /dev/null > "$LOGS/scheduler.log" 2>&1 & echo $! > "$RUN/scheduler.pid"; fi
(cd dashboard && nohup node "$ROOT/dashboard/node_modules/vite/bin/vite.js" < /dev/null > "$LOGS/portal.log" 2>&1 & echo $! > "$RUN/portal.pid")
for _ in $(seq 1 30); do sleep 2; curl -fs http://127.0.0.1:8000/health >/dev/null 2>&1 && break; done
curl -fs http://127.0.0.1:8000/health >/dev/null 2>&1 && ok "API      http://127.0.0.1:8000/docs" || info "API is still starting - see data/logs/api.log"
for _ in $(seq 1 30); do sleep 1; curl -fs http://localhost:5173/ >/dev/null 2>&1 && break; done
curl -fs http://localhost:5173/ >/dev/null 2>&1 && ok "Portal   http://localhost:5173" || info "Portal is still starting - see data/logs/portal.log"
[ "$SCHEDULE" = 1 ] && ok "Auto-sync every 6 hours (data/logs/scheduler.log)"
printf '\n  \033[32mRegTrack is running. Stop it with:  ./start.sh --stop\033[0m\n\n'
if [ "$OPEN" = 1 ]; then
  if command -v open >/dev/null; then open http://localhost:5173 >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null; then xdg-open http://localhost:5173 >/dev/null 2>&1 || true; fi
fi
