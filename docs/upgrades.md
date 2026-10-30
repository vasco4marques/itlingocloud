# Upgrades

This guide gives the constraints for the update of an existing database. A new database does not need these steps.

## Rules for every update

- Back up the database and the filestore before each module update. See [deployment.md](deployment.md#backups).
- Update all six modules with `-u` and the pre-upgrade script `itlingo_core/upgrade.py`. Production uses `make upgrade`. For a local database, see [local-development.md](local-development.md).
- Do not uninstall a module to fix an upgrade or to get new access rules. An uninstall can delete records.
- After an image rebuild, start the container with `--renew-anon-volumes`. Otherwise Docker can keep old module files.
- Module migrations cannot be reversed. To go back, restore the backup.

## Module consolidation

Older databases have the modules `itlingo_organizations`, `itlingo_workspace_access`, `itlingo_documents`, and `itlingo_notifications`. `itlingo_core` replaces them. `upgrade.py` moves their module metadata to `itlingo_core` before Odoo loads the modules. The tables, record IDs, and workspace keys do not change.

- Odoo runs the script only with `-u` and `--pre-upgrade-scripts`. Use the same command for every update.
- The script checks the database first. If the state is not safe, it stops with an error before it writes.
- `itlingo_documents` must be at version `19.0.1.7.0` or later. `itlingo_workspace_access` must be at version `19.0.2.0.0` or later. If a database has an older version, update it first with the old code.
- The script runs in one transaction. A second run does nothing.

## Retired features (core `19.0.3.1.0`)

This update deletes data. Make a backup first.

- It deletes the retired report and backlog tables and the document library grouping.
- It deletes these fields and their values: organization type, workspace methodology, planned cost, and current cost.
- It removes the old sprint and backlog fields from upstream project tasks. The task records stay.
- Documents and attachments stay. Documents with a retired library, language-specific, report, or template type move to the corresponding current type.
- The projects API no longer returns `methodology`. The current ITOI and chatbot code do not read it.
- The document review no longer requires a library. The one-time Django importer and its commands are removed.

## Workspace grants and invitations (core `19.0.3.2.0`)

- Old accepted `Workspace Manager` grants that are not from the workspace creator get the grant source `legacy`. The Odoo log lists them. An administrator must examine them in the backend menu Workspace Roles with the filter "Legacy grants (review)" and remove the incorrect ones. Until then, these grants keep their rights.
- Old pending roles and invitations now require mailbox proof. Users cannot claim them at signup or from the bell. Send these invitations again.
- The update deletes pending invitations to workspaces that do not exist.

## Access rules (core `19.0.3.3.0`, integration `19.0.1.6.0`)

- The Odoo backend and generic model RPC require an active internal user in `ITLingo Admin`. This includes `call_kw`, `call_button`, JSON-2, and password login through the external RPC API.
- Older databases kept old record rules because Odoo marked them as not updatable. The update removes that mark. Odoo then writes the current rules from the module files and deletes the rules that the modules no longer declare. Rule record IDs do not change.
- Before the integration update, portal users could read the integration tokens of other users. After it, portal and `ITLingo Member` users read and change only their own tokens. Tokens do not change.
- A public workspace launch includes only the published documents of that workspace.
- Old ITOI launch tokens that the server did not record do not open a session. Users must launch ITOI again from the portal.

The update does not delete or change organizations, workspaces, roles, documents, or attachments.

## ITOI

Deploy the matching ITOI version with each ITLingo Cloud update that changes the token API. See [architecture.md](architecture.md#external-applications).
