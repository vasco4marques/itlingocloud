# Configuration

ITLingoCloud reads its configuration from three places:

- The `.env` file gives the database connection to Docker Compose.
- An Odoo configuration file gives the server options.
- The Odoo database stores the Cloud settings, for example the ITOI and chatbot connections.

Git ignores the real configuration files. Create them from the examples with `cp -n`, so that you do not overwrite an existing file. Do not commit real passwords or keys.

## Credentials

Each installation has three different secrets. Do not use the same value for two of them.

- `DB_PASSWORD` in `.env` connects Odoo to PostgreSQL.
- `admin_passwd` in the Odoo configuration file is the master password. It protects the database manager at `/web/database/manager`, which can create, copy, back up, restore, and delete databases. It is not a login password.
- The administrator login (`admin`) is a user account in one database. Change its password after the first sign-in.

## The `.env` file

Copy `.env.example` to `.env`. Both Compose files read it.

- `DB_USER`: the PostgreSQL user. The default is `odoo`. Do not use `postgres`, because Odoo refuses to connect as that user.
- `DB_PASSWORD`: the PostgreSQL password. The local Compose file does not start without it.
- `LOCAL_ODOO_PORT`: the loopback port of the local Odoo. The default is `8069`. Change it if another program uses that port.
- `ODOO_TAG`: the production image tag. Only `docker-compose.yml` uses it. `deploy.sh` sets it on the production host.

The local PostgreSQL container creates its user from `DB_USER` and `DB_PASSWORD` only when it initializes an empty volume. If you change these values later, the existing database keeps the old credentials.

## Odoo configuration files

Each installation type has its own example:

- `config/odoo.local.conf.example` for the local Compose file. Copy it to `config/odoo.local.conf`. Compose mounts the copy read-only at `/etc/odoo/odoo.conf`.
- `odoo.docker.conf.example` for production. The production host keeps the copy as `/opt/odoo/odoo.docker.conf`. Refer to [deployment.md](deployment.md).
- `config/odoo.config.example` for a source installation. Copy it to `config/odoo.config`. Refer to [local-development.md](local-development.md#optional-source-installation).

The important options are:

- `addons_path`: `/mnt/extra-addons` in the image. A source installation uses the absolute path of `custom-addons`.
- `data_dir`: `/var/lib/odoo` in the image. The filestore is below this directory.
- `admin_passwd`: the master password.
- `http_interface`: the local file uses `0.0.0.0` inside the container. Compose publishes the port only on `127.0.0.1`. The production file uses `127.0.0.1` because the container uses host networking behind a reverse proxy.
- `proxy_mode`: `False` locally and `True` in production behind the reverse proxy.

The Docker files do not contain database options. The image entrypoint reads them from the Compose environment (`HOST`, `PORT`, `USER`, `PASSWORD`). If you add `db_host`, `db_port`, `db_user`, or `db_password` to the Docker configuration file, that value overrides the Compose environment.

## Cloud settings

An ITLingo Admin changes these settings in the backend, under the ITLingo menu. The values are stored in the database, so each database has its own values.

ITLingo > Integration > Settings controls the ITOI connection:

- Shared AES Key: a 32-character key. It must be equal to `COM_KEY` in the ITOI configuration. If the field is empty, Cloud makes a random key the first time that it needs one. Copy that key to ITOI.
- ITOI URL: the base URL of ITOI, with a trailing slash. The default is `http://localhost:3000/`.
- API Base URL: the base URL for external API callbacks.
- Token Expiry (hours): the lifetime of an API token. The default is 24.
- Extra Importable File Extensions: other text file types that ITOI users can import from Cloud documents. Do not list DSL extensions. Cloud adds them automatically.

The ITOI URL has two uses. The browser of the user follows it when the user launches ITOI. The Odoo server also sends files to `<ITOI URL>/pushFile` from the chatbot page. Inside the Odoo container, `localhost` is the container itself. Thus, with the local Compose file and the default URL, the launch can work while the file push fails.

ITLingo > Chatbot Settings > Running Settings controls the chatbot connection:

- Chatbot URL: the base URL of the chatbot application. The chatbot page loads this URL in an iframe, so the browser must reach it. If it is empty, Cloud uses `http://127.0.0.1:8000/`.
- Langium AI Service URL: the base URL of the Langium AI service. Cloud stores this value for the chatbot.
- Chatbot Secret Key: the shared secret that signs the workspace access tokens for the chatbot. The chatbot must use the same secret. If the environment variable `ITLINGO_CHATBOT_SECRET` is set in the Odoo process, it overrides this field. The Compose files do not set it.

ITLingo > Chatbot Settings > LLM Settings controls the model providers and models of the chatbot.

The Chatbot Settings pages, the LLM Settings page of an organization, and the other chatbot features require the chatbot database tables. Without these tables, the pages show a server error. Refer to [architecture.md](architecture.md#persistent-data).

## System parameters

These keys are in Settings > Technical > System Parameters. That menu requires the developer mode. The defaults are correct for the Docker image.

- `itlingo_dsl.node_path` and `itlingo_templating.node_path`: the Node.js executable. The default is `node`.
- `itlingo_dsl.validate_timeout`, `itlingo_dsl.describe_timeout`, `itlingo_dsl.services_compile_timeout`, and `itlingo_templating.parse_timeout`: the time limits in seconds for the Node.js helpers. The default is 30.
- `auth_signup.invitation_scope`: `itlingo_core` sets it to `b2c` at each update. The website signup page does not use this value. It uses the website setting Website > Configuration > Settings > Customer Account, which is "On invitation" on a new database. Refer to [local-development.md](local-development.md#accounts-and-access).
- `auth_signup.signup.validity.hours`: the lifetime of a signup or invitation link. The Odoo default is 144 hours.

## Mail and public URL

Invitations and signup links use Odoo mail. Production already has an outgoing mail server for the Brevo SMTP relay. An administrator configured it manually in the database, so Git does not contain it. Refer to [email.md](email.md) for the values, the setup procedure, and the verification without sending.

Each installation needs these items:

- An outgoing mail server, in Settings > Technical > Email > Outgoing Mail Servers. That menu requires the developer mode.
- A valid email address for the company, and the `email_from` option in the Odoo configuration file.
- `web.base.url` with the public URL of the installation. The links in the mail use this URL.

Production runs without the scheduler, and the mail queue contains old messages. Do not start the scheduler or process the queue before you read [deployment.md](deployment.md#scheduler-and-outgoing-mail).

Do not copy production data or a production mail server into a local database. A local Odoo can send the mail that is in the queue of the copied data.
