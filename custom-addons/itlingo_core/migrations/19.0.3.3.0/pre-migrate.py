"""Let the module data refresh every ITLingo Core record rule (19.0.3.3.0).

Older installs flagged the rule XML IDs ``noupdate``. The rule files now use
``<data noupdate="0">``, but Odoo never resets the flag of an existing XML ID
(``ir.model.data._update_xmlids`` only updates ``model``/``res_id``) and
``_load_records`` skips records whose XML ID is ``noupdate`` during an update.
The old rules (wider domains, one group each, all four permissions) therefore
stayed active after an upgrade, and group rules are OR-ed with the new ones.

Clearing the flag here, before the data files load, makes the XML files the
only authority: Odoo rewrites each rule in place (same record ID, so its
domain, groups and permissions) and ``_process_end`` deletes rules that the
module no longer declares. No business record changes. Idempotent.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        UPDATE ir_model_data SET noupdate = FALSE
         WHERE module = 'itlingo_core' AND model = 'ir.rule' AND noupdate
     RETURNING name
    """)
    names = sorted(name for (name,) in cr.fetchall())
    if names:
        _logger.info("ITLingo permissions: %d record rule(s) refresh from the module data: %s.",
                     len(names), ', '.join(names))
