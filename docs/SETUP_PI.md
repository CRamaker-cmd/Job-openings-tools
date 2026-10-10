# Step-by-step: Job Hunter on a Raspberry Pi with an external drive

For: a Raspberry Pi 4 (Raspberry Pi OS, ideally 64-bit) that already has an external drive **mounted**, and wants everything the
app writes (data, and optionally Docker's own images/containers) kept on that drive. Open a terminal on the Pi (directly or over
`ssh`) and follow the steps in order. Each step says what you should see. If something looks different, stop and compare with
"If it doesn't match" or send the output to whoever is helping you.

Throughout, `/mnt/ssd` is used as the drive's mount point. **Replace it with your own** (step 2 finds it).

---

## Step 0: What are we working with? (1 minute)

```bash
uname -m                 # aarch64 = 64-bit OS (recommended).  armv7l = 32-bit OS (works, but use the slim image: see step 9)
cat /etc/os-release | head -2
free -h                  # total RAM; the app itself needs very little (see docs/DOCKER.md)
df -h /                  # free space on the SD card
```

## Step 1: Find your drive and its filesystem type (the important check)

```bash
lsblk -f
```
Example output (yours will differ):
```
NAME   FSTYPE FSVER LABEL   UUID                                 FSAVAIL FSUSE% MOUNTPOINTS
sda
└─sda1 ext4   1.0   media   3f7a1c0e-....                            1.2T    38% /mnt/ssd
mmcblk0
├─mmcblk0p1 vfat  ...                                                          /boot/firmware
└─mmcblk0p2 ext4  ...                                                          /
```
Find the line whose **MOUNTPOINTS** is your drive. Write down:

- **FSTYPE** (the filesystem), **UUID**, and the **mount point** (e.g. `/mnt/ssd` or `/media/pi/MyDrive`).

Then confirm how it is mounted:
```bash
findmnt -T /mnt/ssd -o TARGET,SOURCE,FSTYPE,OPTIONS        # use your mount point
```
You want to see `rw` in OPTIONS. (NTFS shows up here as `fuseblk` or `ntfs3`; that is normal.)

### What your filesystem type means

| FSTYPE | Can it hold the app's database and Docker data? | What to do |
|---|---|---|
| **ext4** | Yes, ideal | Go to step 2. |
| **xfs**, **btrfs**, **f2fs** | Yes | Go to step 2 (everything below works the same). |
| **ntfs** (`fuseblk`/`ntfs3`) | **Not directly.** NTFS has no Linux permissions and is unreliable for databases; Docker's storage can't use it at all | Use **Option N** in step 2b: a small ext4 "disk image" stored *on* the NTFS drive. Your files and media stay untouched. |
| **exfat**, **vfat** (FAT32) | **Not directly**, same reasons | Same: **Option N** in step 2b. |
| (nothing, "unformatted" / no FSTYPE) | Not yet usable | Only if the drive is empty or fully backed up: step 2c (formats it, **erases everything**). |

> Is the drive also used by your media server? Then do **not** reformat it. If it is ext4 you can simply share it (the app only
> uses its own folder). If it is NTFS/exFAT use Option N.

## Step 2: Make the mount permanent and boot-safe

A drive mounted by the desktop (under `/media/<user>/...`) appears only when someone logs in, so a background service can't rely on
it. Check how yours is mounted:
```bash
findmnt -no TARGET /mnt/ssd; grep -v '^#' /etc/fstab
```
- If your drive's mount point **starts with `/media/`** or there is **no line for it in `/etc/fstab`**, it's an automount: do 2a.
- If `/etc/fstab` already has a line for it that includes `nofail`, skip to step 3.
- If `/etc/fstab` has a line **without `nofail`**, add `,nofail` to its options (a missing drive must never stop the Pi from booting).

### 2a. ext4/xfs/btrfs drive: mount it via /etc/fstab (e.g. at `/mnt/ssd`)
```bash
lsblk -f                                   # copy the UUID of your partition, e.g. 3f7a1c0e-....
sudo mkdir -p /mnt/ssd
sudo umount /media/$USER/YOURLABEL 2>/dev/null || true        # only if it was auto-mounted
sudo cp /etc/fstab /etc/fstab.bak                              # safety copy
echo 'UUID=PASTE-YOUR-UUID-HERE  /mnt/ssd  ext4  defaults,nofail  0  2' | sudo tee -a /etc/fstab   # change ext4 to your FSTYPE
sudo systemctl daemon-reload
sudo mount -a
findmnt -T /mnt/ssd -o TARGET,SOURCE,FSTYPE,OPTIONS            # expect TARGET /mnt/ssd, rw
```
If `mount -a` prints an error, **fix `/etc/fstab` before rebooting** (restore with `sudo cp /etc/fstab.bak /etc/fstab`).

### 2b. Option N: NTFS / exFAT / FAT drive: an ext4 image stored on the drive
Assumes the drive is mounted at `/mnt/drive` (make it permanent like 2a first, using `ntfs`/`exfat` as the type and
`defaults,nofail,uid=1000,gid=1000` as options). Then:
```bash
sudo truncate -s 12G /mnt/drive/jobhunter.img                  # 12 GB: app data + Docker images; use 2G if only the app's data
sudo mkfs.ext4 -L jobhunter -F /mnt/drive/jobhunter.img
sudo mkdir -p /mnt/ssd
echo '/mnt/drive/jobhunter.img  /mnt/ssd  ext4  loop,defaults,nofail,x-systemd.requires-mounts-for=/mnt/drive  0  0' | sudo tee -a /etc/fstab
sudo systemctl daemon-reload && sudo mount -a
findmnt -T /mnt/ssd -o TARGET,SOURCE,FSTYPE,OPTIONS            # expect FSTYPE ext4
```
From here on `/mnt/ssd` is a real ext4 filesystem. The image is a single file on your drive (don't move or delete it).

### 2c. Unformatted or empty drive you want to dedicate to this
> **This ERASES the whole partition.** Double-check the device name with `lsblk` first.
```bash
sudo mkfs.ext4 -L jobhunter /dev/sdX1        # sdX1 = your partition, e.g. sda1
```
Then do 2a.

## Step 3: Install Docker

```bash
sudo apt update && sudo apt install -y git curl
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
```
**Log out and back in** (or reboot) so the group change applies, then check:
```bash
docker run --rm hello-world           # expect: "Hello from Docker!"
docker compose version                # expect: Docker Compose version v2...
```

## Step 4 (optional but recommended): keep Docker's own storage on the drive too

This stops the SD card from filling up with images and wearing out. It needs the drive to be **ext4/xfs/btrfs** (step 2a, or
Option N from 2b with a 12 GB image). It moves **all** Docker data on this Pi. Do it **now**, while Docker is still empty:

```bash
sudo systemctl stop docker docker.socket
sudo mkdir -p /mnt/ssd/docker
echo '{ "data-root": "/mnt/ssd/docker" }' | sudo tee /etc/docker/daemon.json     # if the file already exists, add the key by hand
sudo mkdir -p /etc/systemd/system/docker.service.d
printf '[Unit]\nRequiresMountsFor=/mnt/ssd\n' | sudo tee /etc/systemd/system/docker.service.d/wait-for-drive.conf
sudo systemctl daemon-reload && sudo systemctl start docker
docker info | grep -E "Docker Root Dir|Storage Driver"
```
Expect `Docker Root Dir: /mnt/ssd/docker` and `Storage Driver: overlayfs` or `overlay2`.
(Docker already has images you want to keep? Copy them first: `sudo rsync -aH /var/lib/docker/ /mnt/ssd/docker/` before starting Docker.)
The `RequiresMountsFor` line makes Docker wait for the drive at boot.

## Step 5: Get the app

```bash
cd ~ && git clone https://github.com/CRamaker-cmd/Job-openings-tools && cd Job-openings-tools
git checkout claude/job-hunter-app        # needed only until the latest pull request is merged; afterwards stay on main
```

## Step 6: Create the data folder on the drive

> **Use your own mount point from step 1, not the example `/mnt/ssd`.** If you create `/mnt/ssd/jobhunter` while the drive is *not*
> actually mounted at `/mnt/ssd`, you just make a folder on the SD card.

The container runs as user id **1000**, so that user must own the folder:
```bash
sudo mkdir -p /mnt/ssd/jobhunter
sudo chown 1000:1000 /mnt/ssd/jobhunter
./deploy/check-drive.sh /mnt/ssd/jobhunter      # from the project folder: confirms it is really on the drive
```
Every line should start with ✓ (a "!" about an unusual filesystem is only a note). The script tells you what to fix if not, and lists
your mounted drives when the folder doesn't exist.

## Step 7: Tell Docker to use that folder

```bash
cp .env.example .env
nano .env
```
Make the file contain exactly these two lines (remove the `#`):
```
JOBHUNTER_DATA=/mnt/ssd/jobhunter
COMPOSE_FILE=compose.yaml:compose.external-drive.yaml
```
Save (`Ctrl+O`, Enter, `Ctrl+X`). Check it was understood:
```bash
docker compose config | grep -B1 -A4 "type: bind"       # expect source: /mnt/ssd/jobhunter  target: /app/data
sudo ss -ltnp | grep 8585 || echo "port 8585 is free"   # expect: port 8585 is free
./deploy/check-drive.sh                                  # reads JOBHUNTER_DATA from .env; every line should be ✓
```
Port 8585 is the app's default. (Taken? Change the **left** number in the `ports:` line of `compose.yaml`.)

## Step 8: Start it

```bash
docker compose up -d --build
```
The first build downloads and installs things: **expect 5-15 minutes on a Pi 4**, and it will make the Pi busy (your media server
may stutter meanwhile). Watch progress with `docker compose logs -f` once it says "Started" (`Ctrl+C` leaves the logs, the app keeps running).

## Step 9: If the build fails at "chromium"

The browser (for Google/Meta/Apple/Microsoft) is optional. Build without it:
```bash
WITH_BROWSER=0 docker compose up -d --build
```
Everything else works the same; those four companies are skipped (see the Help page in the app).

## Step 10: Check that it works

```bash
docker compose ps                                              # STATUS "Up ... (healthy)" after ~1 minute
curl -s -o /dev/null -w "dashboard HTTP %{http_code}\n" http://localhost:8585/      # expect 200
ls -la /mnt/ssd/jobhunter                                      # expect jobs.db (+ jobs.db-wal / -shm) after you open the dashboard once
docker exec jobhunter id                                       # expect uid=1000(app)
hostname -I                                                    # your Pi's IP address(es)
```
Now open **`http://<pi-ip>:8585`** (or `http://<hostname>.local:8585`) from your laptop or phone on the same network.
The dashboard has no login, so keep it on your home network and **never port-forward it**.

## Step 11: Set it up in the dashboard

1. **Settings → Profile**: name, email, pitch, skills.
2. **Companies**: press **Test** on each company. Anything that says it works is good; for ones that fail, press **Pause** (or Edit
   to fix the details). Some defaults may need correcting: that is expected, they could not be checked in advance.
3. Press **Scrape now** on the Jobs page, or just wait: it refreshes one company at a time, in the background, once a day.
4. Check the **Status** page after 20-30 minutes.

## Step 12: The reboot test (do not skip)

```bash
sudo reboot
```
After the Pi is back (give it 2 minutes):
```bash
findmnt -T /mnt/ssd -o TARGET,FSTYPE,OPTIONS       # the drive is mounted
docker compose -f ~/Job-openings-tools/compose.yaml ps   # or cd into the folder first: the app is Up
```
Open the dashboard again: your settings and jobs are still there.
**If the drive wasn't ready**, the container does not start (by design: it will not write to the SD card by mistake). Fix the mount,
then `cd ~/Job-openings-tools && docker compose up -d`.

---

## Day-to-day

| | |
|---|---|
| See what it's doing | `cd ~/Job-openings-tools && docker compose logs -f` |
| Stop / start | `docker compose stop` / `docker compose start` |
| Update the app | `git pull && docker compose up -d --build` (your data is kept) |
| Resource use | `docker stats --no-stream jobhunter` |
| Back up | `docker compose stop && cp -a /mnt/ssd/jobhunter ~/jobhunter-backup && docker compose start` |
| Remove everything | `docker compose down --rmi local` then `sudo rm -rf /mnt/ssd/jobhunter` |

## If it doesn't match

| Symptom | Cause and fix |
|---|---|
| `docker compose up` says `bind source path does not exist` | The folder in `.env` doesn't exist: the drive isn't mounted there, the mount point is different (you used the example `/mnt/ssd`), or step 6 was skipped. Run `./deploy/check-drive.sh` (it lists your drives), fix the path in `.env` / create the folder, then `docker compose up -d` again (no rebuild needed). |
| Container keeps restarting; logs say "data folder ... is not writable" | Wrong owner: `sudo chown 1000:1000 /mnt/ssd/jobhunter`, then `docker compose up -d`. |
| `required variable JOBHUNTER_DATA is missing` | `.env` is missing or misspelled (step 7). Run commands from inside the project folder. |
| `permission denied` talking to Docker | Log out/in after `usermod -aG docker` (step 3), or use `sudo`. |
| Port already in use | Change the left number in `ports:` of `compose.yaml` (e.g. `"8686:8585"`) and `docker compose up -d`. |
| Docker won't start after step 4 | `journalctl -u docker -n 30`. Usually a typo in `daemon.json` (must be valid JSON) or the drive isn't mounted. Remove `/etc/docker/daemon.json` to go back to the SD card. |
| `Storage Driver: vfs` after step 4 | The drive's filesystem isn't suitable (NTFS/exFAT?). Use Option N (2b) or skip step 4. |
| Build is killed / out of memory | `free -h`; add swap or stop other services during the build; or build the slim image (step 9). |
| Dashboard unreachable from other devices | Check `docker compose ps`, the Pi's firewall (`sudo ufw status`), and use the IP from `hostname -I`. |

## What to send if you need help

```bash
lsblk -f; findmnt -T /mnt/ssd; docker info | grep -E "Root Dir|Storage Driver"
cd ~/Job-openings-tools && docker compose ps && docker compose logs --tail 60
```
