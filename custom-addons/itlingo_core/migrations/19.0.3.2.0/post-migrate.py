"""Classify existing workspace grants and invitations (19.0.3.2.0).

``itlingo.project.role.grant_source`` is new. Old rows have no provenance:
an accepted ``ws_manager`` row may be an explicit grant or a copy made by the
old organization-manager cascade, which never revoked it. Nothing is
deleted. Rows of the workspace creator stay ``explicit``; the other accepted
``ws_manager`` rows become ``legacy`` and are listed in the log for owner
review (backend: Workspace Roles, filter "Grant source = Legacy (review)").
Future revocations remove only ``org_manager`` rows, so legacy rows keep
their current rights until an owner changes them.

Pending invitations created before the auth_signup proof have no invited
contact: a signup no longer claims them by email alone. They stay, and a
manager's "invite again" sends a token link that makes them claimable.

Pending role rows were created by an email lookup without mailbox proof (the
address may belong to an unverified signup). They stay with their IDs but get
``mailbox_proof_required``: the invitee cannot answer them from the bell. A
manager resends the invitation; the proof link then accepts the row.
Idempotent.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        UPDATE itlingo_project_role r
           SET grant_source = 'legacy'
          FROM itlingo_workspace w
         WHERE w.id = r.project_id
           AND r.role = 'ws_manager' AND r.state = 'accepted'
           AND r.grant_source = 'explicit'
           AND r.user_id IS DISTINCT FROM w.creator_id
     RETURNING r.id, r.user_id, r.project_id, EXISTS (
            SELECT 1 FROM itlingo_organization_role o
             WHERE o.organization_id = w.organization_id AND o.user_id = r.user_id
               AND o.role = 'org_manager' AND o.state = 'accepted')
    """)
    rows = cr.fetchall()
    for role_id, user_id, project_id, is_org_manager in rows:
        _logger.warning(
            "ITLingo permissions: review legacy ws_manager grant %s (user %s, workspace %s): %s.",
            role_id, user_id, project_id,
            'user is an accepted org manager (likely cascade)' if is_org_manager
            else 'user is NOT an org manager (explicit grant or stale cascade)',
        )
    proof_required = 0
    for table in ('itlingo_organization_role', 'itlingo_project_role'):
        cr.execute(f"""
            UPDATE {table} SET mailbox_proof_required = TRUE
             WHERE state = 'pending' AND mailbox_proof_required IS NOT TRUE
        """)
        proof_required += cr.rowcount
    cr.execute("SELECT count(*) FROM itlingo_pending_invitation WHERE partner_id IS NULL")
    unproven = cr.fetchone()[0]
    _logger.info(
        "ITLingo permissions: %d workspace manager grant(s) marked legacy for review; "
        "%d pending invitation(s) need a new invite before signup can claim them; "
        "%d pending role invitation(s) need a resend and mailbox proof.",
        len(rows), unproven, proof_required,
    )
