# ITLingoCloud

ITLingoCloud is a set of Odoo 19 modules for ITLingo organizations, workspaces, documents, DSLs, and templates. This repository contains the six custom modules, the Docker image definition, the Compose files, configuration examples, and the production deployment tools.

The repository does not contain Odoo source. The Docker image uses the upstream `odoo:19` image as its base. ITOI and ITLingo-Chatbot are separate applications. This repository contains only the Odoo modules that connect to them.

## Documentation

- [Local development](docs/local-development.md): run Cloud with Docker, create the database, install and update modules, read logs, and run tests.
- [Configuration](docs/configuration.md): environment variables, Odoo configuration files, credentials, and the Cloud settings for ITOI, the chatbot, and mail.
- [Architecture](docs/architecture.md): the modules, their responsibilities, and the boundaries to ITOI and the chatbot.
- [Workflows](docs/workflows.md): the user operations in the portal and the backend.
- [Deployment](docs/deployment.md): the production host and the deployment procedure.
- [Manual host setup](docs/manual-setup.md): the host configuration that `deploy.sh` does not make, for example DNS, nginx, TLS, PostgreSQL, secrets, and the ITOI and chatbot settings.
- [Email](docs/email.md): the SMTP relay, the sender address, the mail queue, and the mail DNS records.
- [Upgrades](docs/upgrades.md): migration constraints and data-loss warnings for existing databases.

## Repository layout

- `custom-addons/`: the six ITLingoCloud modules and their tests.
- `Dockerfile`: the application image with the Python and Node.js dependencies.
- `docker-compose.local.yml`: local Odoo and PostgreSQL 16.
- `docker-compose.yml`: production only. It uses the host PostgreSQL and host networking.
- `.env.example`, `config/`, `odoo.docker.conf.example`: configuration examples.
- `deploy.sh`, `Makefile.droplet`: production deployment commands.
- `odoo/Makefile`: optional commands for an upstream Odoo source checkout.
- `scripts/`: the Docker image retention service for the production host.

## Quick start

Install Docker Engine and Docker Compose. Then follow [docs/local-development.md](docs/local-development.md).

## Essential warnings

- Do not use `docker-compose.yml` or `deploy.sh` for local work. They change the production host.
- Back up the database and the filestore before a module update on an existing database.
- Do not uninstall an ITLingoCloud module to repair or upgrade it. An uninstall deletes the records of its models.
- Do not run `docker compose down -v` on a database that you need. It deletes the database and filestore volumes.

Git excludes local secrets, database exports, virtual environments, Node.js dependencies, and Python caches. The repository includes the compiled browser assets and Node.js bundles that Odoo requires at runtime.
