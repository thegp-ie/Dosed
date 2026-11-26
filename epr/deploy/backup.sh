#!/usr/bin/env bash
# Nightly encrypted backup of the EPR database and Healthlink folders.
# - Encrypted with the practice's public age key before it leaves the server.
# - Copy to EU-located storage only (e.g. a second Irish/EU site or EU object storage).
# - Test a restore at least quarterly (GPIT IN.1.10; ICGP "No Data No Business").
# Usage (cron, 01:30):  30 1 * * * /opt/epr/deploy/backup.sh
set -euo pipefail
cd "$(dirname "$0")/.."
: "${AGE_RECIPIENT:?set AGE_RECIPIENT to the practice backup public key (age1...)}"
DEST="${BACKUP_DIR:-/var/backups/epr}"
KEEP_DAYS="${KEEP_DAYS:-35}"
STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$DEST"
docker compose exec -T db pg_dump -U epr -Fc epr | age -r "$AGE_RECIPIENT" > "$DEST/epr-db-$STAMP.dump.age"
docker compose run --rm -T --no-deps app sh -c 'tar -C /data -cz healthlink' \
  | age -r "$AGE_RECIPIENT" > "$DEST/epr-healthlink-$STAMP.tgz.age"
find "$DEST" -name 'epr-*.age' -mtime +"$KEEP_DAYS" -delete
# Off-site copy (uncomment one):
# rclone copy "$DEST" eu-backup:epr-backups --max-age 2d
# rsync -a "$DEST/" backup@second-site.example.ie:/srv/epr-backups/
echo "Backup complete: $STAMP"
