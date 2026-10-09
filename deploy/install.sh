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
echo ">> Done. UI: http://$(hostname).local:8080   (first scrape runs in ~2 min; or: .venv/bin/python -m jobhunter check)"
