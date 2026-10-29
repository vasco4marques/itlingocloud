"""Consolidate the legacy ITLingo modules into ``itlingo_core`` in place.

Odoo runs this file through ``--pre-upgrade-scripts`` with the raw cursor,
before it loads ``base`` (``odoo/modules/loading.py``, ``load_modules``), so
the removed module directories are never needed. Odoo runs it only with
``-u``::

    odoo-bin -c <conf> -d <db> -u itlingo_core \
        --pre-upgrade-scripts=<addons>/itlingo_core/upgrade.py \
        --stop-after-init

What it does, in the caller's transaction (any exception rolls back all):

* renames the ``itlingo_organizations`` module row to ``itlingo_core`` (the
  row ID, constraint and relation ownership stay), then merges
  ``itlingo_workspace_access``, ``itlingo_documents`` and
  ``itlingo_notifications`` into it;
* moves every XML ID of these modules to ``itlingo_core``, except the
  itlingo.document DSL fields, which go to ``itlingo_dsl``. Identical aliases
  (same name, same record) collapse into one row. Records, ``noupdate`` flags,
  groups, ACLs, rules and user data stay untouched;
* moves ``itlingo_website_portal.portal_list_pager`` to ``itlingo_core``
  without a new view;
* rewrites module names in dependencies, view keys, QWeb ``t-call``/group
  references, ``arch_fs``/``template_fs`` paths, static URLs and menu icons.

It stops before any write if the database is in a state it cannot merge
safely. A second run, a fresh database and a core-only database are no-ops.
"""
import logging
from collections import defaultdict

from odoo.tools import SQL
from odoo.tools.parse_version import parse_version

_logger = logging.getLogger(__name__)

CORE = 'itlingo_core'
DSL = 'itlingo_dsl'
ROOT = 'itlingo_organizations'
# Legacy module -> sub-package that now holds its files inside itlingo_core.
OLD = {
    'itlingo_organizations': 'organizations',
    'itlingo_workspace_access': 'workspaces',
    'itlingo_documents': 'documents',
    'itlingo_notifications': 'notifications',
}
# The last historical migration folder of each module. Older installs did not
# run them and the folders are gone, so they must upgrade with the old code.
MIN_VERSION = {
    'itlingo_documents': '19.0.1.7.0',
    'itlingo_workspace_access': '19.0.2.0.0',
}
# Legacy XML IDs that the itlingo.document DSL extension now owns.
TO_DSL = {
    ('itlingo_documents', 'field_itlingo_document__dsl_family_id'),
    ('itlingo_documents', 'field_itlingo_document__dsl_version_id'),
}
DSL_CONSTRAINTS = ('itlingo_document_dsl_family_id_fkey', 'itlingo_document_dsl_version_id_fkey')
PAGER = ('itlingo_website_portal', 'portal_list_pager')
PAGER_FS = 'itlingo_core/views/portal_pagination.xml'
INSTALLED = ('installed', 'to upgrade')
UNINSTALLED = ('uninstalled', 'uninstallable')
# Tables with a FK to ir_module_module that this script handles itself, or
# whose rows (wizard leftovers, demo failures) may go with a removed module.
FK_HANDLED = {
    'ir_module_module_dependency', 'ir_module_module_exclusion',
    'ir_model_constraint', 'ir_model_relation', 'ir_demo_failure',
    'base_module_uninstall_ir_module_module_rel', 'rel_modules_langexport',
    'base_module_install_request', 'base_module_install_review',
}

_OLD_RE = '|'.join(OLD)
# (pattern, replacement) pairs for PostgreSQL regexp_replace; order matters.
ARCH_REWRITES = [
    *((rf'\m{m}\.{n}\M', f'{DSL}.{n}') for m, n in sorted(TO_DSL)),
    (rf'\m{PAGER[0]}\.{PAGER[1]}\M', f'{CORE}.{PAGER[1]}'),
    (rf'\m({_OLD_RE})\.', f'{CORE}.'),
    (rf'/({_OLD_RE})/static/', f'/{CORE}/static/'),
]


class ConsolidationError(Exception):
    pass


def migrate(cr, version):
    cr.execute(
        "SELECT name, id, state, latest_version FROM ir_module_module WHERE name IN %s",
        [(*OLD, CORE, DSL)],
    )
    mods = {name: (mid, state, ver) for name, mid, state, ver in cr.fetchall()}
    old = {name: mods[name] for name in OLD if name in mods}
    if not old:
        return  # fresh, core-only or already consolidated database

    plan = _plan(cr, mods, old)
    _apply(cr, plan)
    _logger.info(
        "Consolidated %s into %s: %d XML IDs moved, %d duplicate aliases removed.",
        ', '.join(sorted(plan['installed'])), CORE, plan['moved'], len(plan['imd_delete']),
    )


def _plan(cr, mods, old):
    """Validate the database and return the mutation plan; no writes."""
    errors = []
    installed = {n for n, (_, s, _) in old.items() if s in INSTALLED}
    leftovers = {n for n, (_, s, _) in old.items() if s in UNINSTALLED}
    for name in set(old) - installed - leftovers:
        errors.append(f"{name} is in state {old[name][1]!r}; finish or cancel that operation first.")

    def owned(module_name, module_id):
        cr.execute(
            """SELECT (SELECT count(*) FROM ir_model_data WHERE module = %s)
                    + (SELECT count(*) FROM ir_model_constraint WHERE module = %s)
                    + (SELECT count(*) FROM ir_model_relation WHERE module = %s)""",
            [module_name, module_id, module_id],
        )
        return cr.fetchone()[0]

    for name in sorted(leftovers):
        if owned(name, old[name][0]):
            errors.append(f"{name} is {old[name][1]} but still owns metadata; it cannot be removed safely.")

    core = mods.get(CORE)
    if installed:
        if ROOT not in installed:
            errors.append(f"{', '.join(sorted(installed))} installed without {ROOT}.")
        for name, minimum in MIN_VERSION.items():
            if name in installed and parse_version(old[name][2] or '0') < parse_version(minimum):
                errors.append(
                    f"{name} {old[name][2]} is older than {minimum}; upgrade it with the "
                    "pre-consolidation code first."
                )
        if 'itlingo_documents' in installed and mods.get(DSL, (0, None))[1] not in INSTALLED:
            errors.append(f"itlingo_documents is installed but {DSL} is not.")
        if core:
            if core[1] not in UNINSTALLED:
                errors.append(f"{CORE} is {core[1]!r} while legacy modules are still installed.")
            elif owned(CORE, core[0]):
                errors.append(f"{CORE} is {core[1]} but already owns metadata.")
        cr.execute(
            "SELECT res_id FROM ir_model_data WHERE module = 'base' AND name = %s",
            [f'module_{CORE}'],
        )
        stale = [r for (r,) in cr.fetchall() if not core or r != core[0]]
        if stale:
            errors.append(f"base.module_{CORE} points to an unknown module row {stale}.")

    root_id = old[ROOT][0] if ROOT in old else None
    merged_ids = [old[n][0] for n in installed if n != ROOT]
    delete_ids = merged_ids + [old[n][0] for n in leftovers] + ([core[0]] if installed and core else [])

    # Rows of any other table that point to a module row we remove.
    cr.execute(
        """SELECT k.relname, a.attname
             FROM pg_constraint c
             JOIN pg_class k ON k.oid = c.conrelid
             JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
            WHERE c.contype = 'f' AND c.confrelid = 'ir_module_module'::regclass"""
    )
    for table, column in cr.fetchall():
        if table in FK_HANDLED or not delete_ids:
            continue
        cr.execute(SQL(
            "SELECT count(*) FROM %s WHERE %s = ANY(%s)",
            SQL.identifier(table), SQL.identifier(column), delete_ids,
        ))
        if cr.fetchone()[0]:
            errors.append(f"{table}.{column} references a legacy module row; resolve it first.")

    # XML IDs: group moving rows with rows already in the target namespace.
    groups = defaultdict(list)
    if installed:
        cr.execute(
            """SELECT id, module, name, model, res_id, noupdate FROM ir_model_data
                WHERE module IN %s OR module IN %s OR (module = %s AND name = %s)""",
            [tuple(installed), (CORE, DSL), *PAGER],
        )
        for row in cr.fetchall():
            _id, module, name = row[:3]
            target = module if module in (CORE, DSL) else DSL if (module, name) in TO_DSL else CORE
            groups[target, name].append(row)
    imd_delete, imd_move = [], defaultdict(list)
    for (target, name), rows in groups.items():
        if len({(r[3], r[4]) for r in rows}) > 1:
            errors.append(f"XML ID {target}.{name} would point to different records: {rows}.")
            continue
        if len({bool(r[5]) for r in rows}) > 1:
            errors.append(f"XML ID {target}.{name} aliases disagree on noupdate: {rows}.")
            continue
        rows.sort(key=lambda r: (r[1] != target, r[0]))  # keep the target row, else the oldest
        keep, *dups = rows
        imd_delete += [r[0] for r in dups]
        if keep[1] != target:
            imd_move[target].append(keep[0])

    # SQL constraints: ir_model_constraint is unique on (name, module).
    con_move = defaultdict(list)
    if installed:
        dsl_id = mods[DSL][0] if DSL in mods else None
        cr.execute(
            "SELECT id, name, module FROM ir_model_constraint WHERE module = ANY(%s)",
            [[old[n][0] for n in installed] + ([dsl_id] if dsl_id else [])],
        )
        seen = defaultdict(list)
        docs_id = old.get('itlingo_documents', (None,))[0]
        for cid, name, module in cr.fetchall():
            if module == dsl_id or (module == docs_id and name in DSL_CONSTRAINTS):
                target = dsl_id
            else:
                target = root_id
            seen[target, name].append(cid)
            if module != target:
                con_move[target].append(cid)
        errors += [f"Constraint {n} would be owned twice by one module: {ids}."
                   for (_, n), ids in seen.items() if len(ids) > 1]

    if errors:
        raise ConsolidationError("ITLingo consolidation aborted, nothing changed:\n- " + "\n- ".join(errors))
    return {
        'installed': installed, 'root_id': root_id, 'core': core if installed else None,
        'merged_ids': merged_ids, 'leftover_ids': [old[n][0] for n in leftovers],
        'imd_delete': imd_delete, 'imd_move': imd_move, 'con_move': con_move,
        'moved': sum(map(len, imd_move.values())),
    }


def _drop_module_rows(cr, ids):
    if ids:
        cr.execute(
            "DELETE FROM ir_model_data WHERE module = 'base' AND model = 'ir.module.module' AND res_id = ANY(%s)",
            [ids],
        )
        cr.execute("DELETE FROM ir_module_module WHERE id = ANY(%s)", [ids])  # cascades dependency rows


def _apply(cr, plan):
    _drop_module_rows(cr, plan['leftover_ids'])
    if not plan['installed']:
        return
    if plan['core']:  # empty row created by an earlier module list update
        _drop_module_rows(cr, [plan['core'][0]])

    root_id, merged = plan['root_id'], plan['merged_ids']
    cr.execute("UPDATE ir_module_module SET name = %s WHERE id = %s", [CORE, root_id])
    cr.execute(
        "UPDATE ir_model_data SET name = %s WHERE module = 'base' AND name = %s",
        [f'module_{CORE}', f'module_{ROOT}'],
    )

    # XML IDs: remove identical aliases first so the (module, name) index holds.
    if plan['imd_delete']:
        cr.execute("DELETE FROM ir_model_data WHERE id = ANY(%s)", [plan['imd_delete']])
    for target, ids in plan['imd_move'].items():
        cr.execute("UPDATE ir_model_data SET module = %s WHERE id = ANY(%s)", [target, ids])

    for target, ids in plan['con_move'].items():
        cr.execute("UPDATE ir_model_constraint SET module = %s WHERE id = ANY(%s)", [target, ids])
    cr.execute("UPDATE ir_model_relation SET module = %s WHERE module = ANY(%s)", [root_id, merged])
    cr.execute(
        """DELETE FROM ir_model_relation a USING ir_model_relation b
            WHERE a.module = %s AND b.module = %s AND a.name = b.name
              AND a.model = b.model AND a.id > b.id""",
        [root_id, root_id],
    )

    # Dependencies of the remaining modules (old module rows cascade theirs).
    _drop_module_rows(cr, merged)
    old_names = tuple(OLD)
    cr.execute(
        """DELETE FROM ir_module_module_dependency d
            WHERE d.name IN %s AND EXISTS (
                  SELECT 1 FROM ir_module_module_dependency o
                   WHERE o.module_id = d.module_id
                     AND (o.name = %s OR (o.name IN %s AND o.id < d.id)))""",
        [old_names, CORE, old_names],
    )
    cr.execute("UPDATE ir_module_module_dependency SET name = %s WHERE name IN %s", [CORE, old_names])
    cr.execute("DELETE FROM ir_module_module_dependency WHERE module_id = %s AND name = %s", [root_id, CORE])
    cr.execute("UPDATE ir_module_module_exclusion SET name = %s WHERE name IN %s", [CORE, old_names])

    # Names and paths that embed the module name (views, mail templates, menus).
    for name, package in OLD.items():
        cr.execute(
            "UPDATE ir_ui_view SET key = %s || substr(key, %s) WHERE key LIKE %s",
            [CORE, len(name) + 1, f'{name}.%'],
        )
        for table, column in (('ir_ui_view', 'arch_fs'), ('mail_template', 'template_fs')):
            cr.execute(SQL(
                "UPDATE %(t)s SET %(c)s = %(new)s || substr(%(c)s, %(cut)s) WHERE %(c)s LIKE %(like)s",
                t=SQL.identifier(table), c=SQL.identifier(column),
                new=f'{CORE}/{package}/', cut=len(name) + 2, like=f'{name}/%',
            ))
        cr.execute(
            "UPDATE ir_ui_menu SET web_icon = %s || substr(web_icon, %s) WHERE web_icon LIKE %s",
            [f'{CORE},', len(name) + 2, f'{name},%'],
        )
    cr.execute(
        """UPDATE ir_ui_view v SET key = %s, arch_fs = %s
             FROM ir_model_data x
            WHERE x.model = 'ir.ui.view' AND x.res_id = v.id AND x.module = %s AND x.name = %s""",
        [f'{CORE}.{PAGER[1]}', PAGER_FS, CORE, PAGER[1]],
    )
    cr.execute("UPDATE ir_ui_view SET key = %s WHERE key = %s", [f'{CORE}.{PAGER[1]}', '.'.join(PAGER)])
    for pattern, repl in ARCH_REWRITES:
        cr.execute(
            """UPDATE ir_ui_view SET arch_db = regexp_replace(arch_db::text, %s, %s, 'g')::jsonb
                WHERE arch_db::text ~ %s""",
            [pattern, repl, pattern],
        )
        cr.execute(
            "UPDATE ir_ui_view SET arch_prev = regexp_replace(arch_prev, %s, %s, 'g') WHERE arch_prev ~ %s",
            [pattern, repl, pattern],
        )
