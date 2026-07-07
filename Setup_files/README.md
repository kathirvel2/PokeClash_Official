# PokeClash — Setup files

Helper files for running PokeClash on your own machine or server. This folder is
aimed at a **local / self-hosted** deployment using a **local PostgreSQL**
database (no managed cloud DB, no `ca.pem` required).

> Read the repo root [`README.md`](../README.md) first for the full install
> steps (Python venv, `npm run build` for Showdown, PostgreSQL, and the
> `.env` configuration). This folder only covers running the bot as a
> background service.

## Contents

| File | Purpose |
| --- | --- |
| `pokeclash.service` | systemd unit to run the bot 24/7. |
| `cloudflared.service` | *(optional)* systemd unit to expose the web app via a Cloudflare quick tunnel. |
| `servicefiles.txt` | Legacy plain-text copy of the unit contents (kept for reference). |

## Quick start (systemd, Linux)

1. Install the bot under a real path, e.g. `/opt/PokeClash`, and create the
   virtualenv there (`python3 -m venv venv && venv/bin/pip install -r requirements.txt`).

2. Edit `pokeclash.service`:
   - set `WorkingDirectory=` and `ExecStart=` to your install path;
   - set `User=` to a non-root user that owns the install (recommended);
   - **either** fill in the `Environment="DB_*"` lines for your local Postgres,
     **or** delete them and let the service read `.env` from the working
     directory (the default, since `ENV_MODE` is unset here).

3. Copy the unit(s) into place and start:

   ```bash
   sudo cp Setup_files/pokeclash.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now pokeclash.service
   sudo systemctl status pokeclash.service
   journalctl -u pokeclash.service -f      # live logs
   ```

## Notes

- **Credentials never belong in git.** Prefer a git-ignored `.env` file (loaded
  automatically from `WorkingDirectory`) over hard-coding secrets in the unit.
  If you do put secrets in the unit, `chmod 600` it and keep it off any repo.
- **Local DB = no SSL cert.** With a local PostgreSQL, use `DB_SSLMODE=disable`
  and do **not** set `DB_SSLCERT`. `ca.pem` is only needed for a managed cloud
  DB that requires TLS (e.g. Aiven).
- The bot serves its web mini-app on `PORT` (default `8080`). The
  `cloudflared.service` template tunnels `http://localhost:8080` to a public
  `*.trycloudflare.com` URL — set that URL as `WEB_APP_HOST_URL` in your env.
