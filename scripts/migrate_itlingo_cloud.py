"""Migrate users, organizations, workspaces, roles and document metadata from
an ITLingo Cloud (Django) ``pg_dump`` text dump into the Odoo ``itlingo_dev``
database, using the Odoo ORM.

Run this script through ``odoo-bin shell`` (see ``odoo/Makefile`` targets
``migrate_itlingo_cloud`` and ``migrate_itlingo_cloud_dry``). ``odoo-bin
shell`` exposes the globals ``env`` and ``odoo`` to scripts read from stdin,
which is why CLI arguments are passed through the ``ITLINGO_MIGRATE_ARGS``
environment variable.

Behaviour highlights:

* Single DB transaction. Commits at the end on success; rolls back on
  ``--dry-run`` or on any exception.
* Idempotent. Each record is matched by a stable key before creation, so
  re-running the script never duplicates data.
* Notifications/tracking are suppressed during the import (no inbox spam).
* Only ``Accepted`` org / workspace roles are imported. ``Pending`` rows are
  intentionally dropped.
* Documents are created without a file binary (the dump only contains
  filenames, not bytes).
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import secrets
import shlex
import sys
import traceback
from collections import defaultdict
from datetime import date, datetime
from typing import Any

_log = logging.getLogger("itlingo.migrate")


# ---------------------------------------------------------------------------
# pg_dump text-format parser
# ---------------------------------------------------------------------------

_COPY_RE = re.compile(
    r'^COPY\s+public\.(?:"(?P<qname>[^"]+)"|(?P<name>[A-Za-z_][A-Za-z_0-9]*))\s+'
    r'\((?P<cols>[^)]*)\)\s+FROM\s+stdin;\s*$'
)

# Tables we actually care about. Everything else in the dump is ignored.
WANTED_TABLES = {
    "auth_user",
    "Organization",
    "Project",
    "Document",
    "OrganizationRole",
    "ProjectRole",
}


def _decode_pg_value(raw: str) -> Any:
    """Decode one ``pg_dump`` text-format column value."""
    if raw == r"\N":
        return None
    out = []
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == "\\" and i + 1 < len(raw):
            nxt = raw[i + 1]
            mapping = {
                "n": "\n",
                "r": "\r",
                "t": "\t",
                "b": "\b",
                "f": "\f",
                "v": "\v",
                "\\": "\\",
            }
            if nxt in mapping:
                out.append(mapping[nxt])
                i += 2
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def parse_pg_dump(path: str) -> dict[str, list[dict[str, Any]]]:
    """Read a ``pg_dump`` plain SQL file and extract the rows for the tables
    listed in :data:`WANTED_TABLES`.

    Returns a dict mapping table name (without schema/quotes) to a list of row
    dicts keyed by column name.
    """
    result: dict[str, list[dict[str, Any]]] = {name: [] for name in WANTED_TABLES}
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        current_table: str | None = None
        current_cols: list[str] | None = None
        for line in fh:
            line = line.rstrip("\n")
            if current_table is None:
                m = _COPY_RE.match(line)
                if not m:
                    continue
                name = m.group("qname") or m.group("name")
                if name not in WANTED_TABLES:
                    continue
                cols = [c.strip().strip('"') for c in m.group("cols").split(",")]
                current_table = name
                current_cols = cols
                continue
            if line == r"\.":
                current_table = None
                current_cols = None
                continue
            parts = line.split("\t")
            if len(parts) != len(current_cols or []):
                _log.warning(
                    "Skipping malformed row in %s (got %d cols, expected %d): %r",
                    current_table,
                    len(parts),
                    len(current_cols or []),
                    line[:120],
                )
                continue
            row = {
                col: _decode_pg_value(val)
                for col, val in zip(current_cols or [], parts)
            }
            result[current_table].append(row)
    return result


# ---------------------------------------------------------------------------
# Value coercion helpers
# ---------------------------------------------------------------------------

def _to_bool(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    return s in {"t", "true", "1", "y", "yes"}


def _to_date(value: Any) -> date | bool:
    if not value:
        return False
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return False


def _to_float(value: Any) -> float:
    if value in (None, "", r"\N"):
        return 0.0
    try:
        return float(str(value).strip().replace(",", "."))
    except ValueError:
        return 0.0


# ---------------------------------------------------------------------------
# Mapping helpers
# ---------------------------------------------------------------------------

_ORG_TYPE_MAP = {
    "public": "public",
    "private": "private",
}

_ACTIVITY_MAP = {
    "it": "it",
    "marketing": "marketing",
    "consulting": "consulting",
    "finance": "finance",
    "education": "education",
    "other": "other",
    # Source-only values that have no direct Odoo selection -> fallback.
    "engineering": "other",
    "operations": "other",
    "product": "other",
    "design": "other",
}

_ORG_STATE_MAP = {
    "active": "active",
    "suspended": "suspended",
}

_METHODOLOGY_MAP = {
    "scrum": "scrum",
    "kanban": "kanban",
}

_BUSINESS_STATUS_MAP = {
    "not started": "not_started",
    "executing": "executing",
    "canceled": "canceled",
    "cancelled": "canceled",
    "concluded": "concluded",
}

_ORG_ROLE_MAP = {
    "organization manager": "org_manager",
    "organization member": "org_member",
    "document manager": "doc_manager",
    # No direct Odoo equivalent. Mapped to org_member per migration spec.
    "organization workspace manager": "org_member",
}

_WS_ROLE_MAP = {
    "workspace manager": "ws_manager",
    "workspace member": "ws_member",
    "document manager": "doc_manager",
    # No direct Odoo equivalent. Mapped to ws_member per migration spec.
    "product manager": "ws_member",
}

_DOC_STATUS_MAP = {
    "active": "published",
    "draft": "draft",
    "in review": "in_review",
    "approved": "approved",
    "archived": "archived",
}


# ---------------------------------------------------------------------------
# Migration core
# ---------------------------------------------------------------------------

class MigrationStats:
    def __init__(self) -> None:
        self.created: dict[str, int] = defaultdict(int)
        self.skipped_existing: dict[str, int] = defaultdict(int)
        self.skipped_missing_fk: dict[str, int] = defaultdict(int)
        self.errors: dict[str, int] = defaultdict(int)

    def render(self) -> str:
        cats = ("created", "skipped_existing", "skipped_missing_fk", "errors")
        labels = sorted(
            set(self.created)
            | set(self.skipped_existing)
            | set(self.skipped_missing_fk)
            | set(self.errors)
        )
        width = max((len(label) for label in labels), default=10)
        lines = ["", "Migration summary", "=" * 60]
        header = f'{"entity".ljust(width)} | {"created":>8} | {"existing":>8} | {"miss-fk":>8} | {"errors":>8}'
        lines.append(header)
        lines.append("-" * len(header))
        for label in labels:
            lines.append(
                f"{label.ljust(width)} | "
                f"{self.created[label]:>8} | "
                f"{self.skipped_existing[label]:>8} | "
                f"{self.skipped_missing_fk[label]:>8} | "
                f"{self.errors[label]:>8}"
            )
        return "\n".join(lines)


def _suppress_ctx(env):
    """Return an env with notifications/tracking/signup-emails disabled.

    ``no_reset_password=True`` is the explicit flag ``auth_signup`` checks to
    skip sending the "password reset / signup invitation" email when a
    ``res.users`` record is created. Without it, the bulk user import would
    spam every migrated user with an invitation email. The other flags handle
    mail.thread tracking and auto-subscribe noise.
    """
    return env(context=dict(
        env.context,
        tracking_disable=True,
        mail_create_nosubscribe=True,
        mail_create_nolog=True,
        mail_notrack=True,
        no_reset_password=True,
        active_test=False,
    ))


def _portugal_country_id(env) -> int | bool:
    pt = env["res.country"].search([("code", "=", "PT")], limit=1)
    return pt.id if pt else False


def _portal_group(env):
    group = env.ref("base.group_portal", raise_if_not_found=False)
    if not group:
        raise RuntimeError("base.group_portal not found in this database.")
    return group


# ----- Users -----

def migrate_users(env, rows: list[dict[str, Any]], stats: MigrationStats) -> dict[int, int]:
    Users = env["res.users"].sudo().with_context(
        no_reset_password=True,
        mail_create_nosubscribe=True,
        mail_create_nolog=True,
        mail_notrack=True,
        tracking_disable=True,
    )
    portal_group = _portal_group(env)
    src_to_odoo: dict[int, int] = {}

    for row in rows:
        try:
            src_id = int(row["id"])
        except (KeyError, TypeError, ValueError):
            stats.errors["res.users"] += 1
            continue

        email = (row.get("email") or "").strip().lower()
        username = (row.get("username") or "").strip()
        if not email and not username:
            stats.errors["res.users"] += 1
            continue
        login = email or username

        existing = Users.search(
            ["|", ("login", "=ilike", login), ("email", "=ilike", login)],
            limit=1,
        )
        if existing:
            src_to_odoo[src_id] = existing.id
            stats.skipped_existing["res.users"] += 1
            continue

        first = (row.get("first_name") or "").strip()
        last = (row.get("last_name") or "").strip()
        name = (f"{first} {last}".strip()) or username or login

        try:
            user = Users.create({
                "login": login,
                "email": email or False,
                "name": name,
                "active": _to_bool(row.get("is_active")),
                "password": secrets.token_urlsafe(24),
                "group_ids": [(6, 0, [portal_group.id])],
                "org_setup_pending": True,
            })
        except Exception as exc:
            _log.warning("Failed to create user %s (%s): %s", src_id, login, exc)
            stats.errors["res.users"] += 1
            continue

        src_to_odoo[src_id] = user.id
        stats.created["res.users"] += 1

    return src_to_odoo


# ----- Organizations -----

def migrate_orgs(env, rows: list[dict[str, Any]], stats: MigrationStats) -> dict[int, int]:
    Org = env["itlingo.organization"].sudo()
    pt_id = _portugal_country_id(env)
    src_to_odoo: dict[int, int] = {}

    for row in rows:
        try:
            src_id = int(row["ID"])
        except (KeyError, TypeError, ValueError):
            stats.errors["itlingo.organization"] += 1
            continue

        name = (row.get("name") or "").strip()
        if not name:
            stats.errors["itlingo.organization"] += 1
            continue

        existing = Org.search([("name", "=", name)], limit=1)
        if existing:
            src_to_odoo[src_id] = existing.id
            stats.skipped_existing["itlingo.organization"] += 1
            continue

        org_type = _ORG_TYPE_MAP.get((row.get("tipo") or "").strip().lower(), "private")
        activity = _ACTIVITY_MAP.get(
            (row.get("tipo_atividade") or "").strip().lower(), "other"
        )
        state = _ORG_STATE_MAP.get(
            (row.get("suspended") or "active").strip().lower(), "active"
        )
        country = pt_id if (row.get("country") and str(row["country"]).strip() == "177") else False

        try:
            org = Org.create({
                "name": name,
                "organization_type": org_type,
                "activity_type": activity,
                "state": state,
                "country_id": country,
            })
        except Exception as exc:
            _log.warning("Failed to create org %s (%s): %s", src_id, name, exc)
            stats.errors["itlingo.organization"] += 1
            continue

        src_to_odoo[src_id] = org.id
        stats.created["itlingo.organization"] += 1

    return src_to_odoo


# ----- Projects -----

def migrate_projects(
    env,
    rows: list[dict[str, Any]],
    user_map: dict[int, int],
    org_map: dict[int, int],
    stats: MigrationStats,
) -> dict[int, int]:
    Project = env["project.project"].sudo()
    admin_uid = env.ref("base.user_admin").id
    src_to_odoo: dict[int, int] = {}

    for row in rows:
        try:
            src_id = int(row["id"])
        except (KeyError, TypeError, ValueError):
            stats.errors["project.project"] += 1
            continue

        name = (row.get("name") or "").strip()
        if not name:
            stats.errors["project.project"] += 1
            continue

        src_org = row.get("organization")
        org_id = False
        if src_org is not None and str(src_org).strip() != "":
            try:
                org_id = org_map.get(int(src_org)) or False
            except (TypeError, ValueError):
                org_id = False
        if not org_id:
            stats.skipped_missing_fk["project.project"] += 1
            continue

        existing = Project.search(
            [("name", "=", name), ("organization_id", "=", org_id)], limit=1
        )
        if existing:
            src_to_odoo[src_id] = existing.id
            stats.skipped_existing["project.project"] += 1
            continue

        creator_uid = admin_uid
        src_user = row.get("utilizadorID")
        if src_user is not None and str(src_user).strip() != "":
            try:
                creator_uid = user_map.get(int(src_user), admin_uid)
            except (TypeError, ValueError):
                pass

        methodology = _METHODOLOGY_MAP.get(
            (row.get("methodology") or "").strip().lower(), False
        )
        business_status = _BUSINESS_STATUS_MAP.get(
            (row.get("status") or "").strip().lower(), "not_started"
        )

        vals = {
            "name": name,
            "description": row.get("description") or False,
            "organization_id": org_id,
            "creator_id": creator_uid,
            "methodology": methodology,
            "business_status": business_status,
            "planned_start": _to_date(row.get("plannedStart")),
            "planned_end": _to_date(row.get("plannedEnd")),
            "actual_start": _to_date(row.get("actualStart")),
            "actual_end": _to_date(row.get("actualEnd")),
            "planned_cost": _to_float(row.get("plannedCost")),
            "current_cost": _to_float(row.get("currentCost")),
        }
        try:
            project = Project.create(vals)
        except Exception as exc:
            _log.warning("Failed to create project %s (%s): %s", src_id, name, exc)
            stats.errors["project.project"] += 1
            continue

        src_to_odoo[src_id] = project.id
        stats.created["project.project"] += 1

    return src_to_odoo


# ----- Organization roles -----

def migrate_org_roles(
    env,
    rows: list[dict[str, Any]],
    user_map: dict[int, int],
    org_map: dict[int, int],
    stats: MigrationStats,
) -> None:
    OrgRole = env["itlingo.organization.role"].sudo()
    now = datetime.utcnow().replace(microsecond=0)

    for row in rows:
        status = (row.get("status") or "").strip().lower()
        if status != "accepted":
            continue

        try:
            src_user = int(row["utilizadorID"])
            src_org = int(row["organizationID"])
        except (KeyError, TypeError, ValueError):
            stats.errors["itlingo.organization.role"] += 1
            continue

        user_id = user_map.get(src_user)
        org_id = org_map.get(src_org)
        if not user_id or not org_id:
            stats.skipped_missing_fk["itlingo.organization.role"] += 1
            continue

        role = _ORG_ROLE_MAP.get(
            (row.get("role") or "").strip().lower(), "org_member"
        )

        existing = OrgRole.search(
            [("user_id", "=", user_id), ("organization_id", "=", org_id)],
            limit=1,
        )
        if existing:
            stats.skipped_existing["itlingo.organization.role"] += 1
            continue

        try:
            OrgRole.create({
                "user_id": user_id,
                "organization_id": org_id,
                "role": role,
                "state": "accepted",
                "response_date": now,
            })
        except Exception as exc:
            _log.warning(
                "Failed to create org role user=%s org=%s: %s",
                src_user, src_org, exc,
            )
            stats.errors["itlingo.organization.role"] += 1
            continue

        stats.created["itlingo.organization.role"] += 1


# ----- Workspace roles -----

def migrate_ws_roles(
    env,
    rows: list[dict[str, Any]],
    user_map: dict[int, int],
    proj_map: dict[int, int],
    stats: MigrationStats,
) -> None:
    WsRole = env["itlingo.project.role"].sudo()
    now = datetime.utcnow().replace(microsecond=0)

    for row in rows:
        status = (row.get("status") or "").strip().lower()
        if status != "accepted":
            continue

        try:
            src_user = int(row["utilizadorID"])
            src_proj = int(row["projectReference"])
        except (KeyError, TypeError, ValueError):
            stats.errors["itlingo.project.role"] += 1
            continue

        user_id = user_map.get(src_user)
        proj_id = proj_map.get(src_proj)
        if not user_id or not proj_id:
            stats.skipped_missing_fk["itlingo.project.role"] += 1
            continue

        role = _WS_ROLE_MAP.get(
            (row.get("role") or "").strip().lower(), "ws_member"
        )

        existing = WsRole.search(
            [("user_id", "=", user_id), ("project_id", "=", proj_id)],
            limit=1,
        )
        if existing:
            stats.skipped_existing["itlingo.project.role"] += 1
            continue

        try:
            WsRole.create({
                "user_id": user_id,
                "project_id": proj_id,
                "role": role,
                "state": "accepted",
                "response_date": now,
            })
        except Exception as exc:
            _log.warning(
                "Failed to create ws role user=%s project=%s: %s",
                src_user, src_proj, exc,
            )
            stats.errors["itlingo.project.role"] += 1
            continue

        stats.created["itlingo.project.role"] += 1


# ----- Documents -----

def migrate_documents(
    env,
    rows: list[dict[str, Any]],
    org_map: dict[int, int],
    proj_map: dict[int, int],
    stats: MigrationStats,
) -> None:
    Doc = env["itlingo.document"].sudo()
    admin_uid = env.ref("base.user_admin").id

    for row in rows:
        name = (row.get("name") or "").strip()
        if not name:
            stats.errors["itlingo.document"] += 1
            continue

        proj_id = False
        src_proj = row.get("projectReference")
        if src_proj is not None and str(src_proj).strip() != "":
            try:
                proj_id = proj_map.get(int(src_proj)) or False
            except (TypeError, ValueError):
                proj_id = False

        org_id = False
        if not proj_id:
            src_org = row.get("organization")
            if src_org is not None and str(src_org).strip() != "":
                try:
                    org_id = org_map.get(int(src_org)) or False
                except (TypeError, ValueError):
                    org_id = False

        if not org_id and not proj_id:
            stats.skipped_missing_fk["itlingo.document"] += 1
            continue

        domain = [("name", "=", name)]
        domain.append(
            ("project_id", "=", proj_id)
            if proj_id else ("organization_id", "=", org_id)
        )
        existing = Doc.search(domain, limit=1)
        if existing:
            stats.skipped_existing["itlingo.document"] += 1
            continue

        status = _DOC_STATUS_MAP.get(
            (row.get("status") or "").strip().lower(), "draft"
        )
        version = (row.get("version") or "1.0").strip() or "1.0"
        creation = _to_date(row.get("creationDate"))

        vals = {
            "name": name,
            "status": status,
            "version": version,
            "creator_id": admin_uid,
        }
        vals["project_id" if proj_id else "organization_id"] = (
            proj_id or org_id
        )
        if creation:
            vals["creation_date"] = datetime.combine(creation, datetime.min.time())

        try:
            Doc.create(vals)
        except Exception as exc:
            _log.warning("Failed to create document %r: %s", name, exc)
            stats.errors["itlingo.document"] += 1
            continue

        stats.created["itlingo.document"] += 1


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="migrate_itlingo_cloud",
        description="Migrate an ITLingo Cloud Django pg_dump into the Odoo DB.",
    )
    parser.add_argument("--sql-file", required=True, help="Path to the pg_dump SQL file.")
    parser.add_argument("--dry-run", action="store_true", help="Rollback at the end.")
    parser.add_argument("--limit-users", type=int, default=0)
    parser.add_argument("--limit-orgs", type=int, default=0)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def _run(env_obj):
    """Main entry called by ``odoo-bin shell``.

    ``env_obj`` is the ``env`` global provided by the shell.
    """
    raw_args = os.environ.get("ITLINGO_MIGRATE_ARGS", "")
    args = _parse_args(shlex.split(raw_args))
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _log.info("Parsing dump: %s", args.sql_file)
    src = parse_pg_dump(args.sql_file)
    for table in WANTED_TABLES:
        _log.info("  %s rows for %s", len(src.get(table, [])), table)

    env = _suppress_ctx(env_obj)

    if args.limit_users:
        src["auth_user"] = src["auth_user"][: args.limit_users]
    if args.limit_orgs:
        src["Organization"] = src["Organization"][: args.limit_orgs]

    stats = MigrationStats()
    try:
        _log.info("Migrating users...")
        user_map = migrate_users(env, src["auth_user"], stats)
        _log.info("Migrating organizations...")
        org_map = migrate_orgs(env, src["Organization"], stats)
        _log.info("Migrating projects...")
        proj_map = migrate_projects(env, src["Project"], user_map, org_map, stats)
        _log.info("Migrating organization roles...")
        migrate_org_roles(env, src["OrganizationRole"], user_map, org_map, stats)
        _log.info("Migrating workspace roles...")
        migrate_ws_roles(env, src["ProjectRole"], user_map, proj_map, stats)
        _log.info("Migrating documents...")
        migrate_documents(env, src["Document"], org_map, proj_map, stats)
    except Exception:
        env.cr.rollback()
        _log.error("Migration failed, rolled back:\n%s", traceback.format_exc())
        print(stats.render())
        raise

    if args.dry_run:
        env.cr.rollback()
        _log.info("Dry run: rolled back all changes.")
    else:
        env.cr.commit()
        _log.info("Committed.")
    print(stats.render())


# ``odoo-bin shell`` injects ``env`` into globals when reading scripts from
# stdin. When imported as a regular module (e.g. for unit testing), ``env``
# won't exist and we skip auto-run.
try:
    _shell_env = env  # type: ignore[name-defined]  # noqa: F821
except NameError:
    _shell_env = None

if _shell_env is not None:
    try:
        _run(_shell_env)
    except SystemExit:
        raise
    except Exception:
        sys.exit(1)
