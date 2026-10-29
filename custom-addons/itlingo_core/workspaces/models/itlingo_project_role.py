from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

from odoo.addons.itlingo_core.organizations.models.itlingo_organization import (
    _is_itlingo_admin, _strip_default_context,
)

WS_ROLES = [
    ('ws_manager', 'Workspace Manager'),
    ('doc_manager', 'Document Manager'),
    ('ws_member', 'Workspace Member'),
]
ROLE_STATES = [
    ('pending', 'Pending'),
    ('accepted', 'Accepted'),
    ('rejected', 'Rejected'),
]


class ItlingoProjectRole(models.Model):
    _name = 'itlingo.project.role'
    _description = 'ITLingo Project Role'
    _order = 'project_id, user_id'

    user_id = fields.Many2one(
        'res.users', string='User', required=True, ondelete='cascade',
    )
    project_id = fields.Many2one(
        'itlingo.workspace', string='Workspace',
        required=True, ondelete='cascade',
    )
    role = fields.Selection(WS_ROLES, required=True, default='ws_member')
    state = fields.Selection(ROLE_STATES, default='pending', required=True)
    invite_date = fields.Datetime(
        default=fields.Datetime.now, readonly=True,
    )
    response_date = fields.Datetime(readonly=True)
    mailbox_proof_required = fields.Boolean(
        readonly=True, copy=False, default=False,
        help='Legacy pending invitation: the invitee must use the emailed proof link.',
    )
    # Provenance of the row. ``org_manager`` rows exist only because the
    # user manages the organization and go away with that role. ``legacy``
    # rows predate provenance and need an owner review (19.0.3.2.0).
    grant_source = fields.Selection([
        ('explicit', 'Explicit'),
        ('org_manager', 'Organization manager'),
        ('legacy', 'Legacy (review)'),
    ], default='explicit', required=True, readonly=True)
    cascade_prior_role = fields.Selection(WS_ROLES, readonly=True, copy=False)
    cascade_prior_state = fields.Selection(ROLE_STATES, readonly=True, copy=False)

    _unique_user_project = models.Constraint(
        'UNIQUE(user_id, project_id)',
        'A user can only have one role per project.',
    )

    _INVITE_FIELDS = frozenset({'user_id', 'project_id', 'role', 'state'})

    @api.model
    def _assert_workspace_managers(self, workspaces):
        """Raise unless each workspace still has an accepted manager. Runs
        after the tentative change, inside the caller's savepoint."""
        Role = self.sudo()
        for workspace in workspaces.exists():
            if not Role.search_count([
                ('project_id', '=', workspace.id),
                ('role', '=', 'ws_manager'),
                ('state', '=', 'accepted'),
            ], limit=1):
                raise UserError(_('A workspace needs at least one accepted manager.'))

    def _check_last_manager(self, workspaces):
        # Only a real platform administrator may orphan a workspace (by
        # group, so a non-admin's scoped sudo, e.g. the org-manager cascade
        # acting for a portal user, still gets the check).
        if self.env.user.has_group('itlingo_core.group_itlingo_admin'):
            return
        self._assert_workspace_managers(workspaces)

    @api.model_create_multi
    def create(self, vals_list):
        if not _is_itlingo_admin(self.env):
            # Context defaults would bypass the checks below (state, user...).
            self = _strip_default_context(self)
            for vals in vals_list:
                if set(vals) - self._INVITE_FIELDS or vals.get('state', 'pending') != 'pending':
                    raise AccessError(_('Workspace managers can only send pending invitations.'))
                # Checked before the insert, so a duplicate row cannot turn
                # the denial into a database error. The create rule agrees.
                workspace = self.env['itlingo.workspace'].browse(vals.get('project_id')).exists()
                if not workspace or workspace._itlingo_user_role().role != 'ws_manager':
                    raise AccessError(_('Only workspace managers can invite members.'))
        with self.env.cr.savepoint():
            records = super().create(vals_list)
        todo_xmlid = 'mail.mail_activity_data_todo'
        for rec in records.sudo():
            if rec.state != 'pending':
                continue
            role_label = dict(rec._fields['role'].selection).get(rec.role, rec.role)
            rec.project_id.activity_schedule(
                todo_xmlid,
                user_id=rec.user_id.id,
                summary=_('Workspace invitation: %s', rec.project_id.name),
                note=_(
                    'You were invited to workspace <b>%s</b> as <b>%s</b>. '
                    'Open your portal at <a href="/my/notifications">My Notifications</a> '
                    'to accept or decline.',
                    rec.project_id.name,
                    role_label,
                ),
            )
        return records

    def write(self, vals):
        if not _is_itlingo_admin(self.env) and set(vals) - {'role'}:
            raise AccessError(_('Workspace managers can only change the role of a member.'))
        if 'role' in vals and not self.env.su and any(
                r.state == 'pending' and r.role != vals['role'] for r in self):
            raise UserError(_('The role of a pending invitation cannot change.'))
        if {'role', 'state'} & set(vals) and 'grant_source' not in vals:
            # Whoever sets a role or state makes it an explicit grant, so a
            # 'legacy' row is always an accepted ws_manager awaiting review.
            vals = dict(vals, grant_source='explicit',
                        cascade_prior_role=False, cascade_prior_state=False)
        # Only workspaces where this write removed an accepted manager row
        # are checked: accepting an invitation in an unmanaged legacy
        # workspace must keep working.
        lost = self.filtered(lambda r: r.role == 'ws_manager' and r.state == 'accepted')
        with self.env.cr.savepoint():
            res = super().write(vals)
            if {'role', 'state'} & set(vals):
                self._check_last_manager(lost.project_id)
        return res

    def unlink(self):
        workspaces = self.filtered(
            lambda r: r.role == 'ws_manager' and r.state == 'accepted').project_id
        with self.env.cr.savepoint():
            res = super().unlink()
            self._check_last_manager(workspaces)
        return res

    @api.depends('user_id', 'project_id', 'role')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f'{rec.user_id.sudo().name} - {rec.project_id.sudo().name} ({rec.role})'

    def _ensure_org_member(self, user, project):
        """Auto-assign org_member on the workspace's parent organization."""
        if not project.organization_id:
            return
        OrgRole = self.env['itlingo.organization.role'].sudo()
        existing = OrgRole.search([
            ('user_id', '=', user.id),
            ('organization_id', '=', project.organization_id.id),
        ], limit=1)
        if not existing:
            OrgRole.create({
                'organization_id': project.organization_id.id,
                'user_id': user.id,
                'role': 'org_member',
                'state': 'accepted',
            })

    def _check_invitation_response(self):
        """Only the invitee (or an administrator) answers a pending
        invitation; the role cannot change while it is pending."""
        for rec in self:
            if rec.state != 'pending':
                raise UserError(_('Only pending invitations can be accepted or rejected.'))
            if rec.mailbox_proof_required and not _is_itlingo_admin(self.env):
                raise AccessError(_('Open the invitation link from your email to accept this invitation.'))
            if rec.user_id != self.env.user and not _is_itlingo_admin(self.env):
                raise AccessError(_('Only the invited user can respond to this invitation.'))

    def action_accept(self):
        self._check_invitation_response()
        for rec in self.sudo():
            rec.write({
                'state': 'accepted',
                'response_date': fields.Datetime.now(),
            })
            rec._ensure_org_member(rec.user_id, rec.project_id)
            rec.project_id.message_subscribe(partner_ids=rec.user_id.partner_id.ids)
            rec.project_id.message_post(
                body=_('%s accepted the invitation as %s.',
                       rec.user_id.name, dict(self._fields['role'].selection).get(rec.role)),
                message_type='notification',
                subtype_xmlid='mail.mt_note',
            )

    def action_reject(self):
        self._check_invitation_response()
        for rec in self.sudo():
            rec.write({
                'state': 'rejected',
                'response_date': fields.Datetime.now(),
            })
            rec.project_id.message_post(
                body=_('%s rejected the invitation as %s.',
                       rec.user_id.name, dict(self._fields['role'].selection).get(rec.role)),
                message_type='notification',
                subtype_xmlid='mail.mt_note',
            )
