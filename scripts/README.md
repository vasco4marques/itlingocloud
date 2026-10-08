# Scripts

## `migrate_itlingo_cloud.py`

One-shot migration of the legacy Django ITLingo Cloud `pg_dump` text dump
(`itlingo_cloud_*.sql`) into the Odoo `itlingo_dev` database, through the Odoo
ORM (not raw SQL).

Migrates:

- `auth_user` -> `res.users` (portal users, random password, `org_setup_pending=True`)
- `Organization` -> `itlingo.organization`
- `Project` -> `project.project` (with `organization_id`, `methodology`, etc.)
- `OrganizationRole` (Accepted only) -> `itlingo.organization.role`
- `ProjectRole` (Accepted only) -> `itlingo.project.role`
- `Document` -> `itlingo.document` (metadata only, no file binary)

Does NOT migrate: backlog/sprint/task/notification/Django-internal tables, or
`Pending` invitations.

### Recommended workflow

1. Back up the target DB:

   ```bash
   pg_dump itlingo_dev > backup_pre_migrate.sql
   ```

2. Dry run first (parses the dump, exercises the ORM, then rolls back):

   ```bash
   cd odoo
   make migrate_itlingo_cloud_dry
   ```

   Review the printed summary (`created` / `existing` / `miss-fk` / `errors`).

3. Real run (commits at the end):

   ```bash
   cd odoo
   make migrate_itlingo_cloud
   ```

4. Re-run check: run the same target a second time and confirm the summary
   shows `created` columns at 0 across the board. The script is idempotent and
   looks up records by stable keys (email for users, name for orgs, etc.).

5. Refresh module integration:

   ```bash
   cd odoo
   make upgrade_custom
   ```

### Custom dump path

Override the dump path via the `SQL_DUMP` make variable:

```bash
cd odoo
make migrate_itlingo_cloud_dry SQL_DUMP=../itlingo_cloud_20260601_030001.sql
```

### Notes

- Migrated users have a random password and `org_setup_pending=True`. They
  must reset their password on first login.
- Notifications and mail tracking are disabled during the import, so users do
  not receive inbox spam from migrated activity.
- `Organization Workspace Manager` (source org role) is mapped to `org_member`.
- `Product Manager` (source workspace role) is mapped to `ws_member`.
- Documents are created without file content (the dump only contains
  filenames, not bytes). Re-upload files manually if needed.
