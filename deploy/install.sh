#!/usr/bin/env bash
# Run on the Raspberry Pi from the repo directory:  ./deploy/install.sh
set -euo pipefail
cd "$(dirname "$0")/.."
DIR="$PWD"; USER_NAME="$(id -un)"

python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
[ -f config.yaml ] || { cp config.example.yaml config.yaml; echo ">> Created config.yaml - edit your details in it."; }

for f in jobhunter-web.service jobhunter-scrape.service jobhunter-scrape.timer; do
  sed "s#__DIR__#$DIR#g; s#__USER__#$USER_NAME#g" "deploy/$f" | sudo tee "/etc/systemd/system/$f" >/dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable --now jobhunter-web.service jobhunter-scrape.timer
PORT="$(.venv/bin/python -c 'from jobhunter.config import load_config as l; print(l()["web"]["port"])')"
if ss -ltn 2>/dev/null | grep -q ":$PORT "; then echo ">> NOTE: port $PORT looks busy; change web.port in config.yaml, then: sudo systemctl restart jobhunter-web"; fi
echo ">> Done. UI: http://$(hostname).local:$PORT   (first scrape runs in ~2 min; or: .venv/bin/python -m jobhunter check)"
