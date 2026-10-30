# Local development

This guide runs ITLingoCloud with `docker-compose.local.yml`. That file starts Odoo 19 from the local `Dockerfile` and a PostgreSQL 16 container. Odoo listens only on the loopback address of your computer. The database port is not published.

Run all commands from the repository root. Always use `-f docker-compose.local.yml`. Without it, Docker Compose reads `docker-compose.yml`, which is the production file.

Most commands use this list of the six modules:

```sh
MODULES=itlingo_core,itlingo_dsl,itlingo_templating,itlingo_website_portal,itlingo_integration,itlingo_chatbot_integration
```

## First installation

1. Create the local configuration files. The `-n` option does not overwrite files that already exist.

   ```sh
   cp -n .env.example .env
   cp -n config/odoo.local.conf.example config/odoo.local.conf
   ```

2. In `.env`, replace `DB_PASSWORD` with a private password.
3. In `config/odoo.local.conf`, replace `admin_passwd` with a different private password. Refer to [configuration.md](configuration.md) for the purpose of each password.
4. Build the image.

   ```sh
   docker compose -f docker-compose.local.yml build
   ```

5. Create the database `itlingo` and install the modules.

   ```sh
   docker compose -f docker-compose.local.yml run --rm odoo \
     -d itlingo -i "$MODULES" --stop-after-init --no-http
   ```

   Odoo creates the database if it does not exist. It installs `base`, the six modules, and their dependencies. Odoo 19 does not load demo data by default. Do not add `--with-demo`.

6. Start Odoo.

   ```sh
   docker compose -f docker-compose.local.yml up -d
   ```

7. Open <http://localhost:8069/web/login>. If you set `LOCAL_ODOO_PORT` in `.env`, use that port.

You must create the configuration files before the first `run` or `up`. If `config/odoo.local.conf` does not exist, Docker creates a directory with that name, and Odoo does not start. In that case, stop the containers, remove the empty directory, and do step 1 again.

## Accounts and access

- A database that Odoo creates from the command line has the administrator login `admin` with the password `admin`. Sign in with it, and then change the password and the email address in the user preferences immediately.
- The `admin` user is in the `ITLingo Admin` group. Only active internal users in this group can open the backend at `/odoo` and use the generic RPC API.
- A new database does not allow public signup: `/web/signup` returns 404. To enable it, sign in as `admin` and set Website > Configuration > Settings > Customer Account to "Free sign up". This setting applies to one website. The `auth_signup.invitation_scope` parameter that `itlingo_core` sets does not control the website signup page.
- After you enable signup, other people register at `/web/signup` and accept the terms. New accounts are portal users with the `ITLingo Member` group. They use the portal pages, for example `/my/organizations`.
- To make another administrator, create an internal user in the backend and give it the ITLingo Admin access.
- Invitation mail requires an outgoing mail server. Odoo tries to send the invitation immediately. If the send fails, Odoo marks the mail as failed and does not try again automatically. Refer to [configuration.md](configuration.md#mail-and-public-url).

Refer to [configuration.md](configuration.md#cloud-settings) for the ITOI and chatbot connection settings. The local Compose file does not start ITOI or the chatbot.

## Logs

```sh
docker compose -f docker-compose.local.yml logs -f odoo
docker compose -f docker-compose.local.yml logs db
```

## Update after a source change

Back up the database and the filestore before you update a database that you need. Stop Odoo first, so that the database and the filestore agree. If the database comes from an older Cloud version, read [upgrades.md](upgrades.md) first.

```sh
docker compose -f docker-compose.local.yml stop odoo
BACKUP_DIR=../itlingocloud-backups/$(date +%Y%m%d-%H%M%S)
mkdir -p "$BACKUP_DIR"
docker compose -f docker-compose.local.yml exec -T db \
  sh -c 'pg_dump -U "$POSTGRES_USER" -Fc itlingo' > "$BACKUP_DIR/itlingo.dump"
docker compose -f docker-compose.local.yml cp \
  odoo:/var/lib/odoo/filestore/itlingo "$BACKUP_DIR/filestore-itlingo"
```

Rebuild the image, update the modules, and start Odoo again:

```sh
docker compose -f docker-compose.local.yml build
docker compose -f docker-compose.local.yml run --rm odoo \
  -d itlingo -u "$MODULES" \
  --pre-upgrade-scripts=/mnt/extra-addons/itlingo_core/upgrade.py \
  --stop-after-init --no-http
docker compose -f docker-compose.local.yml up -d --renew-anon-volumes
```

Always include `--pre-upgrade-scripts`. The script moves the metadata of the former modules before Odoo loads the module graph. It does nothing on a database that is already current.

Always include `--renew-anon-volumes` after a rebuild. The `odoo:19` image declares `/mnt/extra-addons` as a volume. Without this option, Docker Compose keeps the anonymous volume of the old container, and Odoo continues to use the old module files.

## Restore a backup

Restore into a new database name, for example `itlingo_restored`. Keep the original database and filestore until you examine the restored copy. Stop Odoo first, and set `BACKUP_DIR` to the backup directory:

```sh
docker compose -f docker-compose.local.yml stop odoo
docker compose -f docker-compose.local.yml exec -T db \
  sh -c 'createdb -U "$POSTGRES_USER" itlingo_restored && pg_restore -U "$POSTGRES_USER" -d itlingo_restored --no-owner' \
  < "$BACKUP_DIR/itlingo.dump"
docker compose -f docker-compose.local.yml cp \
  "$BACKUP_DIR/filestore-itlingo" odoo:/var/lib/odoo/filestore/itlingo_restored
docker compose -f docker-compose.local.yml run --rm --no-deps -u 0 --entrypoint chown odoo \
  -R odoo:odoo /var/lib/odoo/filestore/itlingo_restored
docker compose -f docker-compose.local.yml up -d
```

The copied files belong to your host user. The one-off `chown` container gives them to the `odoo` user before Odoo starts. With two databases, the login page shows a database selector. Select `itlingo_restored`.

## Volumes

Docker Compose prefixes the volume names with the project name. The default project name is the directory name, `itlingocloud`.

- `itlingocloud_postgres-data` contains the PostgreSQL data.
- `itlingocloud_odoo-data` contains the Odoo filestore and sessions.
- Anonymous volumes contain the module files of each image. `--renew-anon-volumes` replaces them.

`docker compose -f docker-compose.local.yml down` removes the containers and keeps the volumes. Do not add `-v` unless you want to delete the database and the filestore. `docker volume prune` removes only unused anonymous volumes. It does not remove the named volumes.

## Isolated validation

Use a separate Compose project to test a change without risk to your database. The project name `itlingocloud-validate` gives it separate containers and volumes.

```sh
docker compose -p itlingocloud-validate -f docker-compose.local.yml build
docker compose -p itlingocloud-validate -f docker-compose.local.yml run --rm odoo \
  -d itlingo -i "$MODULES" --stop-after-init --no-http
LOCAL_ODOO_PORT=18069 docker compose -p itlingocloud-validate -f docker-compose.local.yml up -d
```

The validation instance is at <http://localhost:18069/web/login>. Run the module tests in the same project, on a new database:

```sh
docker compose -p itlingocloud-validate -f docker-compose.local.yml run --rm odoo \
  -d itlingo_test -i "$MODULES" --test-enable \
  --test-tags /itlingo_core,/itlingo_dsl,/itlingo_templating,/itlingo_website_portal,/itlingo_integration,/itlingo_chatbot_integration \
  --stop-after-init --no-http
```

The portal tests include a browser test. The application image contains no Chrome or Chromium, so Odoo skips that test.

When you finish, delete the validation project and its volumes:

```sh
docker compose -p itlingocloud-validate -f docker-compose.local.yml down -v
```

Make sure that the command includes `-p itlingocloud-validate`. Without it, `down -v` deletes your main local database.

The Node.js components have their own tests. Refer to the README files in `custom-addons/itlingo_dsl/services_compiler/`, `custom-addons/itlingo_dsl/validator/`, `custom-addons/itlingo_templating/`, and `custom-addons/itlingo_website_portal/frontend/grammar-editor/`.

## Optional source installation

Docker is the recommended method because the image contains all dependencies. Use a source installation only if you need to debug Odoo itself.

1. Clone upstream Odoo 19 outside this repository. Copy the contents of the checkout into `odoo/`. Keep the `odoo/Makefile` of this repository.
2. Install the upstream Python requirements and the Python packages from `Dockerfile` (`docxtpl` and `openpyxl`).
3. Install Node.js 22. Run `npm ci --omit=dev` in `custom-addons/itlingo_dsl/services_compiler/` and in `custom-addons/itlingo_templating/parser/`.
4. Copy `config/odoo.config.example` to `config/odoo.config`. Set the database connection, the master password, and the absolute path of `custom-addons`.
5. Start Odoo. The Makefile uses the database `itlingo_dev`.

   ```sh
   make -C odoo run
   ```

The `upgrade_custom` target of `odoo/Makefile` updates the six modules with the pre-upgrade script. The `deploy` target runs `deploy.sh`, which changes the production host. Do not use it for local work.
