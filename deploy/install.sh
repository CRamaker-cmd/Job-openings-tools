#!/usr/bin/env bash
# Run on the Raspberry Pi from the repo directory:  ./deploy/install.sh
set -euo pipefail
cd "$(dirname "$0")/.."
DIR="$PWD"; USER_NAME="$(id -un)"

python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
[ -f config.yaml ] || { cp config.example.yaml config.yaml; echo ">> Created config.yaml (only needed for the port / file locations; everything else is set in the web UI)."; }

# The web app scrapes on its own schedule (Settings -> Schedule); remove the old timer if an earlier version installed it.
sudo systemctl disable --now jobhunter-scrape.timer 2>/dev/null || true
sudo rm -f /etc/systemd/system/jobhunter-scrape.timer /etc/systemd/system/jobhunter-scrape.service
for f in jobhunter-web.service; do
  sed "s#__DIR__#$DIR#g; s#__USER__#$USER_NAME#g" "deploy/$f" | sudo tee "/etc/systemd/system/$f" >/dev/null
done
PORT="$(.venv/bin/python -c 'from jobhunter.config import load_config as l; print(l()["web"]["port"])')"
if ss -ltn 2>/dev/null | grep -q ":$PORT "; then echo ">> NOTE: port $PORT looks busy; change web.port in config.yaml, then: sudo systemctl restart jobhunter-web"; fi
sudo systemctl daemon-reload
sudo systemctl enable --now jobhunter-web.service
echo ">> Done. UI: http://$(hostname).local:$PORT   (first scrape starts within a minute; settings are on the Settings page)"
