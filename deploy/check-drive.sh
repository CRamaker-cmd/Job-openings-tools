#!/usr/bin/env bash
# Checks that a folder is a good place for Job Hunter's data BEFORE you start the container.
#   ./deploy/check-drive.sh /mnt/ssd/jobhunter
# (with no argument it uses JOBHUNTER_DATA from your environment or .env)
set -u
p="${1:-${JOBHUNTER_DATA:-}}"
if [ -z "$p" ] && [ -f .env ]; then p="$(grep -E '^JOBHUNTER_DATA=' .env | tail -1 | cut -d= -f2-)"; fi
[ -z "$p" ] && { echo "usage: $0 /path/on/your/drive/jobhunter"; exit 2; }

bad=0; warn=0
say_ok()   { echo "  ✓ $*"; }
say_bad()  { echo "  ✗ $*"; bad=1; }
say_warn() { echo "  ! $*"; warn=1; }

echo "Checking: $p"

if [ ! -d "$p" ]; then
  say_bad "the folder does not exist."
  parent="$(dirname "$p")"
  if [ -d "$parent" ]; then
    echo "    $parent exists. Is that really your DRIVE? Check below; if yes, create the folder:"
    echo "      sudo mkdir -p '$p' && sudo chown 1000:1000 '$p'"
  else
    echo "    $parent does not exist either, so your drive is probably mounted somewhere else."
  fi
  echo
  echo "  Drives/partitions that are currently mounted (look for yours, note its MOUNTPOINT):"
  lsblk -o NAME,SIZE,FSTYPE,LABEL,MOUNTPOINTS 2>/dev/null | grep -vE 'loop|zram' | sed 's/^/    /'
  echo "  Then use that mount point in .env, e.g.  JOBHUNTER_DATA=<MOUNTPOINT>/jobhunter"
  exit 1
fi
say_ok "the folder exists"

# Is it on a different filesystem than the SD card (/)? If not, the drive is NOT mounted there.
if [ "$(stat -c %d "$p")" = "$(stat -c %d /)" ]; then
  say_bad "this folder is on the SAME filesystem as the system (SD card), so the drive is NOT mounted at this location."
  echo "    Writing here would fill the SD card. Find where your drive really is:  lsblk -f"
else
  say_ok "it is on a different disk than the system (mount: $(findmnt -T "$p" -no TARGET | tail -1), source: $(findmnt -T "$p" -no SOURCE | tail -1))"
fi

fs="$(findmnt -T "$p" -no FSTYPE | tail -1)"
case "$fs" in
  ext4|ext3|xfs|btrfs|f2fs) say_ok "filesystem is $fs (good for a database)";;
  ntfs|ntfs3|fuseblk|exfat|vfat|msdos)
    say_bad "filesystem is $fs: no Linux permissions and unreliable for databases. Use 'Option N' in docs/SETUP_PI.md (an ext4 image stored on the drive).";;
  *) say_warn "filesystem is '$fs'; ext4 is recommended.";;
esac

opts="$(findmnt -T "$p" -no OPTIONS | tail -1)"
case ",$opts," in *,rw,*) say_ok "mounted read-write";; *) say_bad "not mounted read-write (options: $opts)";; esac

owner="$(stat -c %u "$p")"
if [ "$owner" = "1000" ]; then say_ok "owned by user id 1000 (what the container runs as)"
else say_bad "owned by user id $owner; the container needs 1000.  Fix:  sudo chown 1000:1000 '$p'"; fi

avail="$(df -h --output=avail "$p" | tail -1 | tr -d ' ')"
say_ok "free space: $avail"

echo
if [ $bad -eq 0 ]; then echo "All good. Start it with:  docker compose up -d"; exit 0
else echo "Fix the ✗ items above, then run this check again."; exit 1; fi
