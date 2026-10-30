# ITLingoCloud modules

These six Odoo modules belong to this repository. No separate Git clone is necessary.

- `itlingo_core`: organizations, workspaces, documents, membership, access rules, and notifications.
- `itlingo_dsl`: DSL definitions, versions, and language services.
- `itlingo_templating`: templates and document generation.
- `itlingo_website_portal`: the web portal and the grammar editor.
- `itlingo_integration`: API tokens and the ITOI integration.
- `itlingo_chatbot_integration`: the connection to the separate ITLingo-Chatbot application.

Each module declares its dependencies in `__manifest__.py`. Refer to [`docs/architecture.md`](../docs/architecture.md) for the module boundaries. Refer to [`docs/local-development.md`](../docs/local-development.md) for the install, update, and test commands.
