# Running with Docker (recommended for a Raspberry Pi)

> Setting this up on a Pi with an external drive? Follow the numbered walk-through in [SETUP_PI.md](SETUP_PI.md). This page is the reference.

Docker keeps everything in one removable bubble: nothing is installed on the Pi itself, the same image runs on a Pi
(arm64) or any PC/server (amd64), and removing it leaves nothing behind.

## Install and start

```bash
# once, if Docker isn't installed yet (Raspberry Pi OS / Debian / Ubuntu):
curl -fsSL https://get.docker.com | sh && sudo usermod -aG docker $USER      # then log out and back in

git clone https://github.com/CRamaker-cmd/Job-openings-tools && cd Job-openings-tools
docker compose up -d --build        # first build takes a few minutes on a Pi
```
Open `http://<pi-hostname>.local:8585` and follow the **Getting started** checklist. It restarts by itself after a reboot.

## Everyday commands

| | |
|---|---|
| Logs | `docker compose logs -f` |
| Stop / start | `docker compose stop` / `docker compose start` |
| Update to a new version | `git pull && docker compose up -d --build` (your data is kept) |
| Status and resource use | `docker compose ps` · `docker stats jobhunter` |
| Change the port | edit the **left** number in `ports:` of `compose.yaml` (e.g. `"8899:8585"`), then `docker compose up -d` |
| Data on an external drive | see [Use an external drive](#use-an-external-drive) |
| Own config (manual links, db location) | uncomment the `./config.yaml:/app/config.yaml:ro` line in `compose.yaml` |

## Your data

Jobs, notes, and every setting changed in the dashboard live in the Docker volume `jobhunter-data` (or on your external drive: see below).

```bash
# back up
docker run --rm -v jobhunter-data:/d -v "$PWD":/b busybox tar czf /b/jobhunter-backup.tgz -C /d .
# restore (into an empty volume)
docker run --rm -v jobhunter-data:/d -v "$PWD":/b busybox tar xzf /b/jobhunter-backup.tgz -C /d
```

## Use an external drive

**What runs where:** the Pi's own CPU and RAM always run the app (a drive only stores things), but *everything it writes* can
live on your external drive: the app's data, the Docker image and containers, the build cache and the logs. Only the operating
system, the Docker engine program and the (tiny) project folder stay on the SD card.

### 1. Prepare the drive (once)
- Use a Linux filesystem, **ext4**. NTFS/exFAT/FAT drives don't keep Linux file permissions and are unreliable for databases
  (SQLite). If the drive also holds your media in NTFS, make a small ext4 partition for this instead of reformatting everything.
- Mount it permanently. Find it with `lsblk -f`, then add a line to `/etc/fstab` (use your drive's UUID):
  ```
  UUID=1234-ABCD  /mnt/ssd  ext4  defaults,nofail  0  2
  ```
  `sudo mkdir -p /mnt/ssd && sudo mount -a` and check `df -h /mnt/ssd`.
- Give the app a folder it may write to (the container runs as user id 1000):
  `sudo mkdir -p /mnt/ssd/jobhunter && sudo chown 1000:1000 /mnt/ssd/jobhunter`

### 2. Option A: keep the app's data (jobs, notes, settings) on the drive
```bash
JOBHUNTER_DATA=/mnt/ssd/jobhunter docker compose -f compose.yaml -f compose.external-drive.yaml up -d --build
```
To make plain `docker compose up -d` do this, copy `.env.example` to `.env` and uncomment its two lines.
If the drive isn't mounted, the container **refuses to start** instead of silently writing to the SD card.
If the folder has the wrong owner you get a clear message in `docker compose logs` telling you which `chown` to run.

### 3. Option B: also move Docker's own storage (images, containers, build cache, logs) to the drive
This keeps the SD card almost write-free. It moves **all** Docker data on this Pi, not just this app:
```bash
sudo systemctl stop docker docker.socket
sudo mkdir -p /mnt/ssd/docker && sudo rsync -aH /var/lib/docker/ /mnt/ssd/docker/      # keeps anything already there
echo '{ "data-root": "/mnt/ssd/docker" }' | sudo tee /etc/docker/daemon.json          # merge by hand if the file already exists
sudo mkdir -p /etc/systemd/system/docker.service.d
printf '[Unit]\nRequiresMountsFor=/mnt/ssd\n' | sudo tee /etc/systemd/system/docker.service.d/wait-for-drive.conf
sudo systemctl daemon-reload && sudo systemctl start docker
docker info | grep "Docker Root Dir"          # should show /mnt/ssd/docker
```
The `RequiresMountsFor` line makes Docker wait for the drive at boot, so nothing starts before it is mounted.
Use A and B together for a fully drive-based setup.

### Without Docker
Set `db_path: /mnt/ssd/jobhunter/jobs.db` in `config.yaml` (the same ext4/owner rules apply) and restart.

### Good to know
- **Power:** a USB hard disk on a Pi 4 needs enough power. Use a self-powered enclosure or a powered USB hub; under-voltage
  can corrupt data. An SSD uses far less power than a spinning disk.
- **Spin-down:** the app writes a little roughly once an hour, so a spinning disk wakes up about that often. Let it sleep
  between with e.g. `sudo hdparm -S 241 /dev/sdX` (30 minutes) if you like; the app doesn't mind a slow first write.
- **Backups** are just files: stop the container (`docker compose stop`), copy the folder (`jobs.db` and its `-wal`/`-shm`
  files together), start again.
- **Moving later:** stop the container, copy the folder to the new place, point `JOBHUNTER_DATA` at it.

**Tested:** the bind-mount setup above in a Linux container environment: data is written to and read back from the mounted
folder across container re-creation, a missing folder aborts startup without creating anything, and the wrong-owner case
gives the clear message. Not tested on a real Pi / USB drive / reboot ordering (the fstab and `data-root` steps are standard Docker and
Linux practice but unverified here).

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
| **Memory cap** | `mem_limit: 1g`; idle use is small (measured **~60 MB RAM, ~0.01 % CPU** idle in the slim image). Chromium adds a few hundred MB only while it loads a Google/Meta/Apple/Microsoft page, one at a time, with images/video/fonts blocked |
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
