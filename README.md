# ITLingoCloud

This repository contains the ITLingoCloud application for Odoo 19. It includes the custom modules, Docker image definition, configuration examples, and deployment scripts.

The custom modules are ordinary directories in this repository. You do not need a separate clone or Git submodules. The Docker image uses upstream Odoo as its base; this repository does not contain Odoo source.

ITOI and ITLingo-Chatbot remain separate applications. The modules that connect to those applications belong here; their application source does not.

## Contents

| Path | Purpose |
| --- | --- |
| `custom-addons/` | The six ITLingoCloud modules and their tests |
| `Dockerfile` | The application image, with Python and Node.js dependencies |
| `docker-compose.local.yml` | A local application and PostgreSQL 16 database |
| `docker-compose.yml` | The existing production configuration for the droplet |
| `config/` | Examples for local Docker and source installations |
| `odoo.docker.conf.example` | The production Odoo configuration example |
| `deploy.sh`, `Makefile.droplet` | The existing production deployment commands |
| `odoo/Makefile` | Optional commands for a separate upstream Odoo checkout |
| `scripts/` | Docker image retention tools and service definitions |

## Get the source

```sh
git clone https://github.com/vasco4marques/itlingocloud.git
cd itlingocloud
```

## Run locally with Docker

Install Docker Engine and Docker Compose. Run all commands from this repository root.

1. Create the local configuration files.

   ```sh
   cp .env.example .env
   cp config/odoo.local.conf.example config/odoo.local.conf
   ```

2. Replace `DB_PASSWORD` in `.env` with a private password.
3. Replace `admin_passwd` in `config/odoo.local.conf` with a different private password.

   The database password connects Odoo to PostgreSQL. The master password protects Odoo database management; it is not the application login password.

4. Build the application image.

   ```sh
   docker compose -f docker-compose.local.yml build
   ```

5. Start the application and database.

   ```sh
   docker compose -f docker-compose.local.yml up -d
   ```

6. Open <http://localhost:8069/web/database/manager>.
7. Create a database named `itlingo` with your master password and a private administrator login.
8. Stop Odoo before you install the custom modules.

   ```sh
   docker compose -f docker-compose.local.yml stop odoo
   ```

9. Install the modules into the new database.

   ```sh
   docker compose -f docker-compose.local.yml run --rm odoo \
     -d itlingo \
     -i itlingo_core,itlingo_dsl,itlingo_integration,itlingo_website_portal,itlingo_chatbot_integration,itlingo_templating \
     --without-demo=all --stop-after-init --no-http
   ```

10. Start Odoo again.

    ```sh
    docker compose -f docker-compose.local.yml up -d
    ```

11. Open <http://localhost:8069/web/login> and use the administrator login that you created.

If port 8069 is occupied, set `LOCAL_ODOO_PORT` in `.env` and use that port in the URLs.

The local configuration uses named volumes for PostgreSQL and the Odoo filestore. It does not publish the database port. Docker Compose keeps these volumes after `down`.

Do not use `down -v` unless you intend to delete the local database and filestore.

### Logs and module updates

```sh
docker compose -f docker-compose.local.yml logs -f odoo
```

After a source change, build the image again. If the change requires a module update, stop Odoo and update the affected module before restart.

```sh
docker compose -f docker-compose.local.yml build
docker compose -f docker-compose.local.yml stop odoo
docker compose -f docker-compose.local.yml run --rm odoo \
  -d itlingo -u itlingo_core,itlingo_dsl,itlingo_integration,itlingo_website_portal,itlingo_chatbot_integration,itlingo_templating \
  --pre-upgrade-scripts=/mnt/extra-addons/itlingo_core/upgrade.py \
  --stop-after-init --no-http
docker compose -f docker-compose.local.yml up -d --renew-anon-volumes
```

The upstream image declares an anonymous volume for the addons directory. Use `--renew-anon-volumes` after an image rebuild to prevent reuse of old module files.

### Upgrade the former module layout

Back up the database and filestore before the first upgrade to `itlingo_core`. Do not uninstall the former organization, workspace, document, or notification modules. An uninstall can delete their records.

Use the update command above with `--pre-upgrade-scripts`. The script transfers module metadata before Odoo loads the new module graph. The retained models keep their tables, record IDs, and workspace keys.

Use the same command for later updates. The script does not repeat a completed consolidation.

### Remove retired features

Back up the database and filestore before this upgrade. Core version `19.0.3.1.0` deletes the retired report/backlog schema, document library grouping, and obsolete fields.

The removed fields include organization type and workspace methodology, planned cost, and current cost. The migration discards their stored values. It also removes the old sprint/backlog fields from upstream tasks, but keeps those task records.

The migration keeps documents and attachments. It reclassifies documents with retired library, language-specific, report, or template types under the corresponding current document types.

The document review workflow no longer requires a library. Submit for Review changes a draft to In Review; Approve and Publish keep their existing behavior.

The projects API no longer returns `methodology`. Current ITOI and chatbot code do not read that field. The one-time Django importer and its commands are removed.

### Tests

Use a separate database for module tests. Do not run tests against your application database.

```sh
docker compose -f docker-compose.local.yml run --rm odoo \
  -d itlingo_test -i itlingo_templating \
  --test-enable --test-tags /itlingo_templating \
  --without-demo=all --stop-after-init --no-http
```

The portal tests include a browser test that requires Chrome or Chromium inside the test container. The current application image does not contain either browser. Odoo skips that test when it cannot find a browser, so this command does not provide full browser coverage with the application image alone.

The JavaScript components have their own `package.json` files and tests. Their README files describe their build commands.

## Production

`docker-compose.yml` retains the existing droplet configuration. It uses host PostgreSQL, host networking, the host filestore, and UID/GID `110:114`. It is not the local installation configuration.

The production host requires `.env` and `odoo.docker.conf`, based on the examples in this repository. Replace all example passwords. The configuration binds Odoo to loopback; the existing reverse proxy provides public access.

`deploy.sh` builds and publishes the image, then updates the existing droplet. The script contains the current image name, server address, and SSH key path. Examine those values before use. It requires a Git commit for the image tag.

The script installs both `docker-compose.yml` and `Makefile.droplet` on the server. The Makefile invokes the consolidation script before a module update. Back up the database and filestore before the first deployment of the six-module layout.

Do not run `deploy.sh` to test a local installation. It changes the production server.

## Optional source installation

Clone upstream Odoo 19 outside this repository. Copy its checkout contents into `odoo/`, but retain this repository's `odoo/Makefile`.

Install the upstream Python requirements and the additional Python packages from `Dockerfile`. Use Node.js 22 and install the runtime dependencies with `npm ci --omit=dev` in these directories:

- `custom-addons/itlingo_dsl/services_compiler/`
- `custom-addons/itlingo_templating/parser/`

Copy `config/odoo.config.example` to `config/odoo.config`. Set the database credentials, master password, and absolute addons path. The source Makefile uses database `itlingo_dev`.

```sh
make -C odoo run
```

Docker is the recommended handover path because it installs these dependencies together.

## DSL services runtime

Author-supplied DSL services run with the permissions of the application process inside its container. Only trusted authors should publish services code.

## External integrations

Configure ITOI and ITLingo-Chatbot separately. Their connection settings and matching secrets depend on the target installation. This repository includes the Odoo integration modules, not those external services.

### Shared chatbot tables

The current chatbot integration reads tables in the same PostgreSQL database as Odoo. The chatbot's Django migrations own these tables. Odoo deliberately does not create them.

Before you use chatbot features, have the chatbot maintainer apply its migrations to the target database. Configure database access and the external service connections with that maintainer.

Without those migrations, a fresh Odoo installation reports `Model ... has no table` for the chatbot models. The modules can install and the login page can load, but chatbot features are not ready for use. The local Compose configuration does not start the chatbot or apply its migrations.

Do not create substitute tables in Odoo. The chatbot owns their schema.

## Files excluded from delivery

Git excludes local secrets, database exports, virtual environments, Node.js dependencies, Python caches, and upstream Odoo source. The repository includes the existing compiled browser assets and Node.js bundles that Odoo requires at runtime.

