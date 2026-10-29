"""Let the module data refresh the integration token rules (19.0.1.6.0).

Older installs flagged ``itlingo_token_rule_own`` ``noupdate`` with the
``base.group_user`` group only. Portal and ITLingo Member users then had no
token rule and read every token. Odoo never resets the flag of an existing XML
ID and skips ``noupdate`` records during an update, so the rule file had no
effect. This is the same fix as ``itlingo_core`` 19.0.3.3.0.

Clearing the flag before the data files load makes the XML file the only
authority: Odoo rewrites each rule in place (same record ID). The rule file
replaces the groups with ``(6, 0, ...)``, so the obsolete group goes away.
No token changes. Idempotent.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        UPDATE ir_model_data SET noupdate = FALSE
         WHERE module = 'itlingo_integration' AND model = 'ir.rule' AND noupdate
     RETURNING name
    """)
    names = sorted(name for (name,) in cr.fetchall())
    if names:
        _logger.info("ITLingo integration: %d record rule(s) refresh from the module data: %s.",
                     len(names), ', '.join(names))
