"""Prepare ``itlingo.pending.invitation.project_id`` for its foreign key.

The field becomes a Many2one to ``itlingo.workspace``. An invitation whose
workspace no longer exists can never be claimed, and it would block the new
foreign key, so it is deleted here (and logged). No grant moves to another
workspace. Idempotent.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("SELECT to_regclass('itlingo_pending_invitation'), to_regclass('itlingo_workspace')")
    if None in cr.fetchone():
        return
    cr.execute("""
        DELETE FROM itlingo_pending_invitation i
         WHERE i.project_id IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM itlingo_workspace w WHERE w.id = i.project_id)
     RETURNING i.id, i.email, i.project_id
    """)
    for inv_id, email, project_id in cr.fetchall():
        _logger.warning(
            "ITLingo permissions: deleted pending invitation %s (%s) to missing workspace %s.",
            inv_id, email, project_id,
        )
