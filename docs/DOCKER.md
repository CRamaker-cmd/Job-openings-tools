# Running with Docker (recommended for a Raspberry Pi)

Docker keeps everything in one removable bubble: nothing is installed on the Pi itself, the same image runs on a Pi
(arm64) or any PC/server (amd64), and removing it leaves nothing behind.

## Install and start

```bash
# once, if Docker isn't installed yet (Raspberry Pi OS / Debian / Ubuntu):
curl -fsSL https://get.docker.com | sh && sudo usermod -aG docker $USER      # then log out and back in

git clone https://github.com/CRamaker-cmd/Job-openings-tools && cd Job-openings-tools
docker compose up -d --build        # first build takes a few minutes on a Pi
```
Open `http://<pi-hostname>.local:8787` and follow the **Getting started** checklist. It restarts by itself after a reboot.

## Everyday commands

| | |
|---|---|
| Logs | `docker compose logs -f` |
| Stop / start | `docker compose stop` / `docker compose start` |
| Update to a new version | `git pull && docker compose up -d --build` (your data is kept) |
| Status and resource use | `docker compose ps` · `docker stats jobhunter` |
| Change the port | edit the **left** number in `ports:` of `compose.yaml` (e.g. `"8899:8787"`), then `docker compose up -d` |
| Own config (manual links, db location) | uncomment the `./config.yaml:/app/config.yaml:ro` line in `compose.yaml` |

## Your data

Jobs, notes, and every setting changed in the dashboard live in the Docker volume `jobhunter-data`.

```bash
# back up
docker run --rm -v jobhunter-data:/d -v "$PWD":/b busybox tar czf /b/jobhunter-backup.tgz -C /d .
# restore (into an empty volume)
docker run --rm -v jobhunter-data:/d -v "$PWD":/b busybox tar xzf /b/jobhunter-backup.tgz -C /d
```

## Clean up completely

```bash
docker compose down            # stop and remove the container (data kept)
docker compose down -v --rmi local   # ALSO delete the data volume and the image: nothing is left behind
```

## Slim image (no browser)

The default image includes Chromium so Google / Meta / Apple / Microsoft can be scraped (about 600 MB). Without it the
image is about 220 MB and those four are skipped; everything else works the same:

```bash
docker compose build --build-arg WITH_BROWSER=0 && docker compose up -d
```
(or set `WITH_BROWSER: "0"` under `build.args` in `compose.yaml`).

## Made for a shared Pi

The app is built to stay out of the way of a media server and Pi-hole:

| What | How |
|---|---|
| **One refresh a day** | every company is refreshed once per 24 h (setting), **one company at a time**, evenly spread (about one every hour) |
| **Only new jobs cost anything** | a job already saved, or already looked at and rejected, is only marked "still listed": no detail page, no pay lookup, no scoring |
| **Lowest CPU priority** | scraping runs at nice 19 inside the container, and the container itself has a small CPU weight (`cpu_shares: 128`) and a one-core cap (`cpus: 1.0`) |
| **Memory cap** | `mem_limit: 1g`; idle use is small (measured **~34 MB RAM, ~0.02 % CPU** idle in the slim image). Chromium adds a few hundred MB only while it loads a Google/Meta/Apple/Microsoft page, one at a time, with images/video/fonts blocked |
| **First in line to be stopped** | `oom_score_adj: 500`: if the Pi ever runs out of memory, the kernel stops this container before the media server or Pi-hole |
| **Gentle on the network** | pauses between requests and between companies (Settings → Schedule), Greenhouse job lists are fetched without descriptions |
| **Gentle on the SD card** | small, rotated logs; a single SQLite file; no constant writes while idle |

If you have an SSD attached to the Pi, point the volume there (`volumes:` bind mount) to spare the SD card entirely.

**What was and wasn't tested:** the slim image was built and run in a Linux (amd64) test environment with these limits:
non-root user, dashboard, health check, data kept across container re-creation, small footprint. The Chromium layer
(`apt install chromium`) and a native arm64 build could not be tested there; both rely on Debian's own arm64/amd64
packages, and the first `docker compose up --build` on the Pi is the real test. Memory numbers for Chromium are estimates.

## Troubleshooting

- **Port already in use** → change the left number of `ports:` (see above).
- **Container restarts in a loop** → `docker compose logs`. A common cause is a mounted `config.yaml` with a typo.
- **"Cannot connect to the Docker daemon"** → `sudo systemctl start docker`, and make sure your user is in the `docker` group.
- **Google/Meta/Apple/Microsoft skipped** → you built the slim image; rebuild without `WITH_BROWSER=0`.
