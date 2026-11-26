# Deployment (self-hosted)

## Server

- Linux server in Ireland or the EEA (on-premises, or an Irish/EU colocation or VPS under an Art. 28 DPA).
- Full-disk encryption (LUKS), automatic security updates, SSH key login only, firewall allowing 443 (and 80 for certificate renewal).
- Recommended: put the EPR behind the practice VPN and leave only `/v/*` (patient video links) public. See the comment in `deploy/Caddyfile`.

## Install

```bash
git clone <repo> /opt/dosed && cd /opt/dosed/epr
cp .env.example .env && chmod 600 .env
docker compose run --rm --no-deps app python -m app.cli gen-keys   # paste the output into .env
# edit .env: domain, practice details, Healthmail hosts, Jitsi URL/secret, POSTGRES_PASSWORD
docker compose up -d --build
docker compose exec app python -m app.cli create-user admin "Practice Admin" practice_manager
docker compose exec app python -m app.cli create-user drsmith "Dr Jane Smith" gp --mcrn 123456
```

Each user sets up two-factor authentication at first sign-in.

## Keys

- `EPR_DATA_KEY` encrypts clinical text and identifiers. **If you lose it, the encrypted data is lost.**
  Keep two offline copies (e.g. sealed envelopes in two locations, or a password manager with two custodians).
- Never store `.env` alongside database backups.
- Key rotation: add a re-encryption job before you rotate (to do: `cli rotate-key`).

## Backups

```bash
apt install age
age-keygen -o practice-backup.key        # keep the private key OFFLINE, off the server
export AGE_RECIPIENT=age1...             # public key
/opt/dosed/epr/deploy/backup.sh
```

Schedule it nightly with cron and copy off-site to EEA storage. **Test a restore every quarter:**

```bash
age -d -i practice-backup.key epr-db-YYYYMMDD.dump.age | docker compose exec -T db pg_restore -U epr -d epr_restore_test
```

## Healthlink file bridge

Inbound HL7 files go into the `healthlink` volume under `in/`. The app polls every
`EPR_HEALTHLINK_POLL_SECONDS`, writes ACKs and referrals to `out/`, and archives processed files
(bad files go to `archive/failed/`).

## Jitsi

Install the official docker-jitsi-meet stack on the same or a second EU server, and apply `deploy/jitsi.env.example`.

## Upgrades

`git pull && docker compose up -d --build`. The schema is created on first start. Before the first
schema change in production, add Alembic migrations (to do).

## Development

```bash
pip install -r requirements-dev.txt
EPR_COOKIE_SECURE=false EPR_REQUIRE_MFA=false python -m app.cli seed-demo
EPR_COOKIE_SECURE=false EPR_REQUIRE_MFA=false EPR_JITSI_APP_SECRET=dev uvicorn app.main:app --reload
python -m pytest -q
```

Demo users: `drmurphy`, `nurse.kelly`, `reception`, `manager`, all with password `demo-password-123`. All demo patients are fictional.
