# Deployment

This guide is for the operator of the production server. For a local installation, see [local-development.md](local-development.md).

Do not run `deploy.sh` to test a local installation. It changes the production server.

## Production layout

- The server keeps the deployment in `/opt/odoo`: `docker-compose.yml`, `Makefile` (a copy of `Makefile.droplet`), `.env`, and `odoo.docker.conf`.
- The container uses the image `vasco4marques/itlingo-odoo:${ODOO_TAG}`. `ODOO_TAG` in `/opt/odoo/.env` is a Git commit hash.
- The container uses host networking. Odoo listens on `127.0.0.1:8069`. The existing nginx reverse proxy gives public access.
- PostgreSQL runs on the host at `127.0.0.1:5432`, not in Docker. The production database is `itlingo_dev`.
- The filestore is `/var/lib/odoo` on the host. The container runs as UID/GID `110:114`, the host `odoo` user, so that it can use this directory.

`docker-compose.local.yml` is not the production configuration. See [configuration.md](configuration.md) for `.env` and `odoo.docker.conf`. If you make these files from the examples, replace every example password.

## Scheduler and outgoing mail

Production runs without the Odoo scheduler and without outgoing mail. The mail queue contains old messages that Odoo did not send.

Do not enable the scheduler (`max_cron_threads` above 0) or an outgoing SMTP server on production. If you enable them, Odoo sends the old queued messages. Keep `max_cron_threads = 0` in the production `odoo.docker.conf`. The example file does not set this value, and the Odoo default starts the scheduler.

Odoo sends invitation emails immediately, without the scheduler. Without an outgoing mail server record, Odoo uses the `smtp_server` option of `odoo.docker.conf`, and the default is `localhost`. Because the container uses host networking, a mail server on the host can receive these messages. The owner of the server must decide about mail before users can invite members.

## Before a deployment

1. Commit the changes. The image tag is the short hash of `HEAD`. If `custom-addons/` has uncommitted changes, `deploy.sh` asks for confirmation.
2. Examine the values `IMAGE`, `SERVER`, and `SSH_KEY` at the top of `deploy.sh`.
3. Read [upgrades.md](upgrades.md) for steps that apply to the new version.
4. Make sure that the matching ITOI version is ready for deployment.
5. Back up the database and the filestore.

## Backups

The repository has no backup script. Make a backup on the server before each module update. Stop Odoo first, so that the database and the filestore agree. The `odoo` user owns `/opt/odoo`, so write the files to your home directory. `pg_dump` asks for `DB_PASSWORD` from `/opt/odoo/.env`:

```sh
cd /opt/odoo
make stop
pg_dump -Fc -h 127.0.0.1 -U <DB_USER> -d itlingo_dev -f ~/itlingo_dev-<date>.dump
sudo tar -C /var/lib/odoo -czf ~/filestore-itlingo_dev-<date>.tar.gz filestore/itlingo_dev
make run
```

Copy both files to a location outside the server. A backup of only one of them is not usable.

## Deploy

Run from the repository root on your computer:

```sh
./deploy.sh               # build, push, and deploy the image for HEAD
./deploy.sh --skip-build  # deploy an image for HEAD that is already pushed
```

The script does these steps:

1. It builds the image, then pushes the tags `<hash>` and `latest`.
2. It copies `docker-compose.yml` and `Makefile.droplet` to `/opt/odoo` on the server. It asks for the `sudo` password on the server.
3. It stops if the old systemd `odoo` service is active.
4. It sets `ODOO_TAG` in `/opt/odoo/.env` to the new hash.
5. It runs `make pull` and `make upgrade`.

`make upgrade` stops Odoo and updates all six modules in `itlingo_dev` with `--pre-upgrade-scripts=/mnt/extra-addons/itlingo_core/upgrade.py`. Then it starts Odoo with `--renew-anon-volumes`. This flag prevents the use of old module files from an earlier image. Odoo is not available during the update.

Other commands in `/opt/odoo`: `make ps`, `make logs`, `make stop`, and `make run`.

## Validation

1. Run `make ps` and make sure that `itlingo-odoo` is running.
2. Run `make logs`. Examine the module update output for errors and for messages from the migration scripts.
3. Open the login page through the public domain and sign in.
4. Open an organization, a workspace, and a document.
5. Use "Launch ITOI" on a workspace and make sure that ITOI opens.

## Rollback

If the update did not change the data, use the previous image:

1. Set `ODOO_TAG` in `/opt/odoo/.env` to the previous hash.
2. Run `make pull`, then `make run`.

Do not run `make upgrade` with an older image.

Module migrations change the database and cannot be reversed. If a migration ran, stop Odoo, then restore the database and the filestore from the backup. Then set the previous tag and run `make run`. [local-development.md](local-development.md#restore-a-backup) shows the restore commands for the local containers. Production uses the host PostgreSQL and `/var/lib/odoo`, so adapt the commands to the host.

## Image retention

The server can remove old Docker images with a nightly timer. It never removes volumes. See [DOCKER_RETENTION.md](../scripts/DOCKER_RETENTION.md). For a rollback, `make pull` gets the previous hash tag from the registry, because `deploy.sh` pushes each hash tag.
