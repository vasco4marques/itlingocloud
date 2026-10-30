# Architecture

ITLingo Cloud is a set of six custom modules for Odoo 19. The Docker image uses the upstream `odoo:19` image and copies `custom-addons/` into `/mnt/extra-addons`.

## Modules

Put new code in the module that owns the responsibility:

- `itlingo_core`: organizations, workspaces, documents, roles, invitations, notifications, security groups, and record rules. It also blocks the Odoo backend and generic model RPC for users who are not in `ITLingo Admin`.
- `itlingo_dsl`: the DSL registry, DSL versions, grammar and services files, DSL resources, and the allowed DSLs of organizations and workspaces.
- `itlingo_website_portal`: the website and portal pages under `/my`, `/public-workspaces`, and `/dsl`, and the browser Grammar Editor.
- `itlingo_templating`: document generation from a template and a DSL specification, and the template reference pages.
- `itlingo_integration`: ITOI launch, launch and API tokens, and the token APIs that ITOI uses.
- `itlingo_chatbot_integration`: the chatbot page in workspaces, chatbot settings, and Odoo models for the chatbot tables.

## Frontend and backend

The server code is Python with the Odoo ORM. The pages are QWeb XML templates with small JavaScript and SCSS assets. Portal controllers and JSON routes do their own access checks. Models enforce access through ACLs and record rules. Code that uses `sudo()` must do its own checks.

The Grammar Editor is a separate TypeScript bundle in `itlingo_website_portal/frontend/grammar-editor`. Its build output is committed in `static/dist/grammar-editor`.

Odoo runs three Node.js 22 helpers as local subprocesses, not as separate services: `itlingo_dsl/validator` (grammar validation), `itlingo_dsl/services_compiler` (DSL services compilation), and `itlingo_templating/parser` (specification parsing).

## External applications

ITOI and ITLingo-Chatbot are separate applications. This repository contains only the Odoo side of each connection.

- ITOI: "Launch ITOI" redirects the user to ITOI with an encrypted launch token. ITOI calls `/token_api/validate-launch` before the workspace creation and before its other integration HTTP requests that use the launch token. ITOI reads documents and DSL grammars through the other `/token_api/` routes.
- Chatbot: Odoo shows the chatbot in an iframe with a signed JWT. The JWT stays valid for one hour.

Deploy the matching ITOI version together with ITLingo Cloud. If `/token_api/validate-launch` is not available, ITOI refuses the operation.

## Persistent data

- PostgreSQL holds the Odoo database.
- The filestore in `data_dir` (`/var/lib/odoo/filestore/<database>`) holds attachments, for example document files. Back up the database and the filestore together.
- The chatbot tables are in the same database. The chatbot's Django migrations own them, and the Odoo models use `_auto = False`. Do not create substitute tables in Odoo. Without the chatbot migrations, Odoo logs `Model ... has no table` and the chatbot features do not work.

## Trust limits

- DSL services code runs with the permissions of the Odoo process inside its container. Let only trusted authors write services code.
- A role change does not revoke a chatbot JWT that Odoo already issued.
- ITOI shares one Theia file system between sessions. Its file events do not identify the user. Thus, a role change does not immediately stop writes from an open ITOI session.
