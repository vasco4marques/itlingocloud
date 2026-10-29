"""Retire legacy document types and drop removed columns before the new code loads.

Runs before Odoo loads the ``itlingo_core`` models and data, so new inserts do
not hit the old NOT NULL ``organization_type`` column, and every document moves
off a retired type before Odoo removes that type's seed record. ``upgrade.py``
already moved the old ``itlingo_documents`` XML IDs to ``itlingo_core``.
Each statement is idempotent. An error rolls back the current transaction.
"""
import logging

from odoo.tools import SQL

_logger = logging.getLogger(__name__)

CORE = 'itlingo_core'
# Retired seed XML ID -> canonical seed XML ID (itlingo.document.type).
TYPE_MAP = {
    'doc_type_specification_library': 'doc_type_specification',
    'doc_type_rsl': 'doc_type_specification',
    'doc_type_psl': 'doc_type_specification',
    'doc_type_tsl': 'doc_type_specification',
    'doc_type_report': 'doc_type_technical_document',
    'doc_type_manual': 'doc_type_technical_document',
    'doc_type_specification_template': 'doc_type_template',
}
# SQL views of the retired itlingo_reports module; they read the columns below.
VIEWS = ('itlingo_burndown_report', 'itlingo_velocity_report')
COLUMNS = {
    'itlingo_organization': ('organization_type',),
    'itlingo_workspace': ('methodology', 'planned_cost', 'current_cost'),
    'itlingo_document': ('backlog_item_id',),
    'project_task': ('backlog_item_id', 'sprint_id', 'planned_effort', 'task_type'),
}


def migrate(cr, version):
    moved = _retire_document_types(cr)
    # RESTRICT (the default): an unknown dependent object aborts the upgrade.
    cr.execute(SQL('DROP VIEW IF EXISTS %s', SQL(', ').join(map(SQL.identifier, VIEWS))))
    for table, columns in COLUMNS.items():
        cr.execute(SQL(
            'ALTER TABLE IF EXISTS %s %s', SQL.identifier(table),
            SQL(', ').join(SQL('DROP COLUMN IF EXISTS %s', SQL.identifier(c)) for c in columns),
        ))
    _logger.info("ITLingo legacy cleanup: %d document(s) moved off retired types.", moved)


def _type_id(cr, name):
    cr.execute(
        "SELECT res_id FROM ir_model_data WHERE module = %s AND name = %s AND model = 'itlingo.document.type'",
        [CORE, name],
    )
    row = cr.fetchone()
    return row and row[0]


def _retire_document_types(cr):
    moved = 0
    for old, new in TYPE_MAP.items():
        old_id = _type_id(cr, old)
        if not old_id:
            continue
        new_id = _type_id(cr, new)
        if not new_id:
            # The canonical seed is gone: this record becomes it, and the data
            # file rewrites its fields during this upgrade.
            cr.execute("UPDATE ir_model_data SET name = %s WHERE module = %s AND name = %s", [new, CORE, old])
            continue
        cr.execute("DELETE FROM ir_model_data WHERE module = %s AND name = %s", [CORE, old])
        if old_id == new_id:
            continue  # alias of the canonical record: keep the record
        cr.execute("UPDATE itlingo_document SET document_type_id = %s WHERE document_type_id = %s", [new_id, old_id])
        moved += cr.rowcount
        cr.execute(
            """DELETE FROM itlingo_document_type t WHERE id = %s AND NOT EXISTS (
                   SELECT 1 FROM ir_model_data x WHERE x.model = 'itlingo.document.type' AND x.res_id = t.id)""",
            [old_id],
        )
    # User-made types with the removed selection value stay, as specifications.
    cr.execute("UPDATE itlingo_document_type SET type_code = 'specification' WHERE type_code = 'specification_library'")
    return moved
