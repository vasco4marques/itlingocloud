# Manual host setup

This guide is for the next operator of the production host. It records the configuration that an operator made by hand. Git does not contain this configuration.

`deploy.sh` does not prepare a host. It only installs `docker-compose.yml` and the `Makefile` in `/opt/odoo`, sets `ODOO_TAG`, pulls the image, and updates the modules. Refer to [deployment.md](deployment.md). Before the first deployment on a new host, do the manual steps in this guide.

Mail has a separate guide. Refer to [email.md](email.md) for the SMTP relay, the sender address, the mail queue, and the mail DNS records.

## How to read this guide

- The statements about the current host come from read-only commands and queries on production on 2026-10-30, unless the text says "not verified".
- "Not verified" means that the value needs root access or the provider console.
- This guide does not contain passwords, keys, or tokens. It gives only the location of each secret.

## Current host

- The host is a DigitalOcean droplet with Ubuntu 24.04 at `46.101.130.155`. The SSH user `vmarques` is in the `sudo` and `docker` groups. `sudo` asks for a password.
- Cloud runs in the container `itlingo-odoo` from `/opt/odoo`.
- ITOI runs in the containers `itoi-api` and `itoi-db` from `/opt/microservices/itlingo-itoi`.
- The chatbot runs in the containers `itlingo-chatbot` and `langium-ai-service` from `/opt/microservices/itlingo-chatbot`. The container `itlingo-chatbot-guard` runs from `/opt/microservices/itlingo-chatbot/guard`.
- PostgreSQL 16 runs on the host, not in Docker. It holds the Cloud database `itlingo_dev` and the chatbot tables.
- The old systemd service `odoo` is disabled and inactive. `deploy.sh` stops if this service is active.

## 1. DNS

- `cloud.itlingo.pt`, `itoi.itlingo.pt`, and `chatbot.itlingo.pt` are A records to `46.101.130.155`.
- The nginx sites also contain the old names `itlingo.duckdns.org` and `itlingo-itoi.duckdns.org`. Their port 80 blocks only return 404 or a redirect.
- Not verified: the DNS account for `itlingo.pt`. Get access from the domain owner.

For a new host, change the three A records to the new address. Do this before you request the certificates.

## 2. Firewall

- The `ufw` service is enabled. The default input policy in `/etc/default/ufw` is `DROP`.
- From outside, the ports 22, 80, and 443 are open. The application ports 3000, 5432, 8000, 8001, and 8069 are not reachable.
- The application ports listen only on `127.0.0.1`. PostgreSQL also listens on `172.17.0.1`, the Docker bridge address.
- Not verified: the exact `ufw` rules. Only root can read `/etc/ufw/user.rules`. Read the rules with `sudo ufw status verbose`.

On a new host, allow only SSH, HTTP, and HTTPS from outside.

## 3. nginx and TLS

The host nginx gives public access. Docker does not manage it. The sites are in `/etc/nginx/sites-available/` and have links in `/etc/nginx/sites-enabled/`.

- `odoo`: `cloud.itlingo.pt` to `127.0.0.1:8069`. It sends `Host`, `X-Forwarded-Host`, `X-Forwarded-For`, `X-Forwarded-Proto`, and `X-Real-IP`. It sets `client_max_body_size 200M` and timeouts of 720 seconds. Odoo needs these headers because `proxy_mode = True`.
- `itlingo-itoi`: `itoi.itlingo.pt` to `127.0.0.1:3000`. It forwards WebSocket upgrades, turns off buffering, and sets timeouts of 3600 seconds. ITOI needs the WebSocket connection.
- `itlingo-chatbot`: `chatbot.itlingo.pt` to `127.0.0.1:8000`. Port 8000 is the chatbot guard, not the chatbot. Refer to [Chatbot guard](#chatbot-guard).
- The sites do not set `Content-Security-Policy` or `X-Frame-Options`. The Cloud chatbot page shows `chatbot.itlingo.pt` in an iframe. If you add one of these headers, make sure that the iframe continues to load.
- `http://chatbot.itlingo.pt/` redirects to HTTPS. `http://cloud.itlingo.pt/` and `http://itoi.itlingo.pt/` return 404 and do not redirect.

Certbot manages the certificates with the nginx plugin, and `certbot.timer` renews them. One certificate covers `cloud.itlingo.pt` and `itoi.itlingo.pt`. A second certificate covers `chatbot.itlingo.pt`. To see the names and the expiry dates, run `sudo certbot certificates`.

On a new host:

1. Install nginx and Certbot with its nginx plugin.
2. Make one temporary HTTP site on port 80 for the three names. Run `sudo nginx -t`, then reload nginx.
3. Request the certificates with `sudo certbot --nginx -d cloud.itlingo.pt -d itoi.itlingo.pt` and `sudo certbot --nginx -d chatbot.itlingo.pt`.
4. Copy the three site files from the old host. Make sure that the `ssl_certificate` paths point to the new certificates in `/etc/letsencrypt/live/`.
5. Remove the temporary site. Enable the three sites.
6. Run `sudo nginx -t`, then reload nginx.
7. Make sure that `certbot.timer` is enabled.

Do not copy the HTTPS sites before step 3. If a certificate file does not exist, `nginx -t` fails.

## 4. Host PostgreSQL

- PostgreSQL 16 from Ubuntu. The service `postgresql` is enabled.
- `listen_addresses = localhost,172.17.0.1`, port 5432, SSL on.
- Login roles: `postgres` (superuser), `odoo`, `itlingo_itoi`, and `vmarques`.
- The role `odoo` is not a superuser. It can create databases. It owns `itlingo_dev`. Odoo refuses to connect as `postgres`.
- The chatbot connects to `itlingo_dev` as `odoo` through `host.docker.internal`. Docker maps this name to the bridge address `172.17.0.1`.
- The database `itlingo` is owned by `itlingo_itoi`. The current ITOI does not use it, because ITOI uses its own `itoi-db` container. Its purpose is not verified. Do not delete it.
- Not verified: `pg_hba.conf`, because only root can read it. It must accept password logins for `odoo` from `127.0.0.1` and from the Docker networks. Without the Docker rule, the chatbot cannot connect.

On a new host:

1. Install PostgreSQL 16.
2. Set `listen_addresses = 'localhost,172.17.0.1'` in `postgresql.conf`. Do not listen on the public address.
3. Create the role `odoo` with a password, with `CREATEDB`, and without `SUPERUSER`.
4. Add `pg_hba.conf` rules for `odoo` from `127.0.0.1/32` and the Docker networks. Use `scram-sha-256`.
5. Restore the database. Refer to [Backups and retention](#8-backups-and-retention).

## 5. Odoo user, filestore, and `/opt/odoo`

- The host user `odoo` has UID 110 and GID 114, with home `/opt/odoo` and no login shell.
- The container runs as `110:114` (`user:` in `docker-compose.yml`).
- `/var/lib/odoo` is owned by `odoo:odoo` with mode `700`. The filestore of `itlingo_dev` is `/var/lib/odoo/filestore/itlingo_dev`.
- `/opt/odoo` is owned by `odoo:odoo`.
- `/opt/odoo/.env` has owner `vmarques`, group `odoo`, and mode `640`. It contains `ODOO_TAG`, `DB_USER`, and `DB_PASSWORD`.
- `/opt/odoo/odoo.docker.conf` has owner `root`, group `odoo`, and mode `640`. Compose mounts it read-only in the container. It contains `addons_path`, `data_dir`, `admin_passwd`, `proxy_mode = True`, `http_interface = 127.0.0.1`, `email_from`, and `max_cron_threads = 0`.

Do not print these two files, because they contain secrets. To examine one option, use a filtered command, for example `docker exec itlingo-odoo grep -E '^(proxy_mode|max_cron_threads)' /etc/odoo/odoo.conf`.

On a new host:

1. Create the user and group `odoo` with UID 110 and GID 114. If you use other IDs, change `user:` in `docker-compose.yml`.
2. Create `/var/lib/odoo` with owner `odoo:odoo` and mode `700`.
3. Create `/opt/odoo` with owner `odoo:odoo`.
4. Make `.env` from `.env.example`. Set new values for `DB_USER` and `DB_PASSWORD`.
5. Make `odoo.docker.conf` from `odoo.docker.conf.example`. Add `max_cron_threads = 0` before the first start. Refer to [email.md](email.md#queue-and-scheduler).
6. Set the owners and modes of `.env` and `odoo.docker.conf` as on the current host.
7. Install Docker Engine and the Compose plugin. Make sure that `docker.service` is enabled.
8. Run `deploy.sh`. It installs `docker-compose.yml` and the `Makefile`.

## 6. ITOI and chatbot host files

These files are in other repositories. This repository does not deploy them.

- `/opt/microservices/itlingo-itoi/docker-compose.yml` and `.env`. The Compose project name is `itlingo-itoi-clean-20260805`. The database volume is `itlingo-itoi-clean-20260805_db-data`.
- `/opt/microservices/itlingo-chatbot/docker-compose.yml` and `.env`. The chatbot publishes `127.0.0.1:8001`, because `.env` sets `CHATBOT_HOST_PORT=8001`.
- `/opt/microservices/itlingo-chatbot/guard/compose.yml` and `chatbot-guard.conf`.

### Chatbot guard

The guard is an nginx container with host networking. It listens on `127.0.0.1:8000` and forwards to the chatbot on `127.0.0.1:8001`. Its configuration is `chatbot-guard.conf`.

- It returns 403 for `/ops` and `/admin`.
- It forwards `/static/` without a check.
- It forwards other paths only if the query has exactly one `token`, one `workspace_key`, and one `workspace_id`.
- It checks only the format of these values. `token` must have three dot-separated base64url parts, `workspace_key` must be a UUID, and `workspace_id` must be a number. The guard does not verify the token signature. The chatbot verifies it.
- It refuses a query with `workspace_session_id`, or with `%` or `+` in a parameter name.
- Its log does not record the query string.

Keep the guard on port 8000 and the chatbot on port 8001. If the chatbot uses port 8000, the public site bypasses the guard.

## 7. Automatic start after a reboot

- `docker`, `nginx`, `postgresql`, `ufw`, and `certbot.timer` are enabled.
- `itlingo-odoo`, `itoi-api`, `itlingo-chatbot`, `langium-ai-service`, and `itlingo-chatbot-guard` use `restart: unless-stopped`.
- `itoi-db` has no restart policy, because the ITOI Compose file does not set one. After a reboot, `itoi-db` does not start, so ITOI cannot start.

After a reboot, run `docker compose up -d` in `/opt/microservices/itlingo-itoi`. Then do the checks in [Verify the host without changes](#verify-the-host-without-changes).

## 8. Backups and retention

- No backup job for the databases or the filestore was found. The inspected locations were the systemd timers, `/etc/cron.d`, and the crontab of `vmarques`.
- Not verified: the root crontab and `/opt/incident-recovery`, because only root can read them. Also not verified: DigitalOcean droplet backups and snapshots. Examine the droplet in the DigitalOcean console.
- `docker-image-retention.timer` runs every night. It keeps the newest tags of each image repository. It never removes an image that a container uses, and it never removes volumes. Refer to [DOCKER_RETENTION.md](../scripts/DOCKER_RETENTION.md).
- Stopped containers with names `rollback-pin-*` keep earlier images for a rollback. Do not remove these containers. To list them, run `docker ps -a --filter name=rollback-pin`.
- Docker has unused volumes, for example the old ITOI volumes `itlingo-itoi_db-data` and `itlingo-itoi_db-recovery-20260805`. To list the volumes, run `docker volume ls`.

Do not run `docker volume prune` or `docker system prune --volumes`. The purpose of the unused volumes is not verified, and they can contain the only copy of old data.

Before each update, back up `itlingo_dev` and its filestore. Refer to [deployment.md](deployment.md#backups). The backup also contains the chatbot tables and the secrets that the database stores. Keep the backup files private. Back up the ITOI database separately from the `itoi-db` container with `pg_dump`.

## 9. Secrets and their locations

- `/opt/odoo/.env`: `DB_PASSWORD`.
- `/opt/odoo/odoo.docker.conf`: `admin_passwd`.
- `/opt/microservices/itlingo-itoi/.env`: `POSTGRES_PASSWORD`, `DATABASE_URL`, `COM_KEY`, and `COOKIE_KEY`.
- `/opt/microservices/itlingo-chatbot/.env`: `DATABASE_URL`, `SECRET_KEY`, and the provider keys `OPENAI_API_KEY`, `COHERE_API_KEY`, `GROQ_API_KEY`, and `GEMINI_API_KEY`.
- The `itlingo_dev` database: the Shared AES Key, the chatbot secret, the model provider keys, and the SMTP password. Refer to [email.md](email.md) for the SMTP password.

The ITOI directory also contains old copies of `.env` (`.env.bak-*`, `.env.pre-*`). They contain secrets. Do not copy them to other places.

To move secrets to a new host:

1. Get each value from the owner, for example through a password manager.
2. Write the value directly into the file on the new host. Give the file the same owner, group, and mode as on the current host.
3. Do not put a secret in Git, in a document, in a chat message, or in a ticket.

If you restore the database, the secrets in the database come with it. If you make a new database, enter them again in the Odoo settings.

## 10. Cloud, ITOI, and chatbot settings

Cloud stores these settings in the database. [configuration.md](configuration.md#cloud-settings) explains each field. A restore of `itlingo_dev` keeps them.

ITLingo > Integration > Settings:

- ITOI URL: `https://itoi.itlingo.pt/`.
- API Base URL: empty.
- Token Expiry (hours): 10000. The default is 24.
- Shared AES Key: set. It is equal to `COM_KEY` in the ITOI `.env`. A hash comparison verified this without a display of the key.

ITOI sets `ITLINGO_CLOUD_URL=https://cloud.itlingo.pt/`.

ITLingo > Chatbot Settings > Running Settings:

- Chatbot URL: `https://chatbot.itlingo.pt`.
- Langium AI Service URL: `http://langium-ai-service:3000`. The chatbot uses this name inside its Docker network.
- Chatbot Secret Key: set. The chatbot container does not set `ITLINGO_CHATBOT_SECRET`, so the chatbot reads the same value from `itlingo_dev`. If you set this variable, set the same value in Odoo and in the chatbot.

The chatbot sets `ODOO_BASE_URL=https://cloud.itlingo.pt` and `CSRF_TRUSTED_ORIGINS=https://chatbot.itlingo.pt`. Its `ALLOWED_HOSTS` contains `chatbot.itlingo.pt`.

If you change a public name, change it in all these places:

- The DNS record, the nginx site, and the certificate.
- The ITOI URL in Cloud, or `ITLINGO_CLOUD_URL` in ITOI.
- The Chatbot URL in Cloud, or `ODOO_BASE_URL`, `ALLOWED_HOSTS`, and `CSRF_TRUSTED_ORIGINS` in the chatbot.
- `web.base.url`. Refer to [email.md](email.md).

If you change the Shared AES Key, change `COM_KEY` in ITOI at the same time. Then restart `itoi-api`.

### Chatbot tables

The chatbot Django migrations create the chatbot tables in `itlingo_dev`. Odoo does not create them. The chatbot container runs `python manage.py migrate` each time that it starts. The current database contains the migrations of the `chatbot` app up to `0039_session_settings_ui_display_fields`.

On a new database, start the chatbot after Odoo creates the database. Then examine `docker logs itlingo-chatbot` for migration errors. Do not open the chatbot pages in Cloud before the migrations complete.

### Model provider catalog

The provider catalog is in the database. An administrator enters it in ITLingo > Chatbot Settings > LLM Settings. An Org Manager enters the providers of an organization on the LLM Settings page of that organization. Cloud copies the values to the chatbot configuration table.

- Platform providers: Cohere, Groq, Gemini, IAEdu, and DeepSeek.
- Organization providers: DeepSeek, Open AI, and OpenAI. Some names have more than one record.
- Each model option has an API key value. Some options are disabled.

On a new database without a restore:

1. Get the API key of each provider from the owner of the provider account.
2. Add each provider and its models in LLM Settings.
3. Enter each API key in the model option.
4. Open a workspace chatbot and send one test question. This step sends a request to the provider and can cost money.

## Verify the host without changes

Run these read-only commands on the host:

1. `docker ps --format '{{.Names}} {{.Status}}'`. Make sure that `itlingo-odoo`, `itoi-api`, `itoi-db`, `itlingo-chatbot`, `langium-ai-service`, and `itlingo-chatbot-guard` run.
2. `systemctl is-enabled docker nginx postgresql certbot.timer docker-image-retention.timer`.
3. `systemctl is-active odoo`. The result must be `inactive`.
4. `ss -ltn`. Make sure that only ports 22, 80, and 443 listen on all addresses.
5. `docker exec itlingo-odoo grep -E '^(proxy_mode|max_cron_threads)' /etc/odoo/odoo.conf`. The values must be `True` and `0`.

Then open `https://cloud.itlingo.pt`, sign in, and launch ITOI from a workspace. Do not send invitations or test mail. Refer to [email.md](email.md#verify-without-sending).
