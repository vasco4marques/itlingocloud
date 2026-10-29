"""Remove the leftovers of the retired agile, reports and library features.

``itlingo_agile`` and ``itlingo_reports`` are uninstalled but their metadata
and tables stayed. Odoo's own ``_module_data_uninstall`` removes their
metadata. Only aliases to records that stay alive (upstream ``project``
models, fields and records) lose their XML ID first, so the uninstall keeps
those records. Odoo skips ``DROP TABLE`` for models that the registry does
not know, so this script drops the named retired tables itself, with
RESTRICT: an unknown dependent object aborts the upgrade.

Odoo's ``_process_end`` after this script removes the library views, action,
menu, ACLs, fields and models that ``itlingo_core`` no longer declares.
``pre-migrate.py`` already dropped the retired SQL views and columns.
"""
import logging

from odoo import SUPERUSER_ID, api
from odoo.addons.itlingo_core.upgrade import _drop_module_rows
from odoo.tools import SQL

_logger = logging.getLogger(__name__)

RETIRED_MODULES = ('itlingo_agile', 'itlingo_reports')
# Dependents first; one DROP statement also resolves FKs between them.
RETIRED_TABLES = (
    'itlingo_backlog_export_wizard', 'itlingo_backlog_import_wizard',
    'itlingo_backlog_item_itlingo_sprint_plan_backlog_rel', 'itlingo_sprint_plan_backlog',
    'itlingo_sprint_user', 'itlingo_task_day_effort', 'itlingo_backlog_item', 'itlingo_sprint',
    'itlingo_document_library', 'itlingo_library',
)
RETIRED_VIEWS = ('itlingo_burndown_report', 'itlingo_velocity_report')
METADATA = ('ir.model', 'ir.model.fields', 'ir.model.fields.selection')


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    tables = RETIRED_TABLES + RETIRED_VIEWS
    # Model names are not known for sure; their table names are.
    cr.execute("SELECT model FROM ir_model WHERE replace(model, '.', '_') = ANY(%s)", [list(tables)])
    models = [m for (m,) in cr.fetchall()]

    # Keep notifications; only forget the record that no longer exists.
    cr.execute(
        "UPDATE itlingo_notification SET res_model = NULL, res_id = NULL WHERE res_model = ANY(%s)",
        [models],
    )
    detached = cr.rowcount
    aliases = _detach_live_aliases(env)

    cr.execute(SQL('DROP VIEW IF EXISTS %s', SQL(', ').join(map(SQL.identifier, RETIRED_VIEWS))))
    cr.execute(SQL('DROP TABLE IF EXISTS %s', SQL(', ').join(map(SQL.identifier, RETIRED_TABLES))))

    cr.execute("SELECT count(*) FROM ir_model_data WHERE module IN %s", [RETIRED_MODULES])
    removed = cr.fetchone()[0]
    env['ir.model.data']._module_data_uninstall(list(RETIRED_MODULES))
    # Constraint rows without an XML ID still name constraints on surviving tables.
    env['ir.model.constraint'].with_context(_force_unlink=True).search([
        ('module.name', 'in', RETIRED_MODULES),
    ]).unlink()

    cr.execute("SELECT id FROM ir_module_module WHERE name IN %s", [RETIRED_MODULES])
    _drop_module_rows(cr, [mid for (mid,) in cr.fetchall()])
    _logger.info(
        "ITLingo legacy cleanup: %d XML IDs of %s uninstalled (%d live aliases kept as records), "
        "%d notification(s) detached, retired tables dropped.",
        removed, ', '.join(RETIRED_MODULES), aliases, detached,
    )


def _detach_live_aliases(env):
    """Delete retired XML IDs of records that must stay: metadata that the
    registry still declares, and business records (e.g. project.project)."""
    cr = env.cr
    cr.execute("SELECT id, model, res_id FROM ir_model_data WHERE module IN %s", [RETIRED_MODULES])
    keep = []
    for xid, model, res_id in cr.fetchall():
        if model in METADATA:
            if _is_live(env, model, res_id):
                keep.append(xid)
        elif model in env and not model.startswith('ir.') and model != 'res.groups':
            keep.append(xid)
    if keep:
        cr.execute("DELETE FROM ir_model_data WHERE id = ANY(%s)", [keep])
    return len(keep)


def _is_live(env, model, res_id):
    record = env[model].browse(res_id).exists()
    if not record:
        return False
    if model == 'ir.model':
        return record.model in env
    field_rec = record if model == 'ir.model.fields' else record.field_id
    field = env[field_rec.model]._fields.get(field_rec.name) if field_rec.model in env else None
    if field is None or model == 'ir.model.fields':
        return field is not None
    return record.value in field.get_values(env)
