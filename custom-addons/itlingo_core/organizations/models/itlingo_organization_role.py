from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

from .itlingo_organization import _is_itlingo_admin, _strip_default_context


class ItlingoOrganizationRole(models.Model):
    _name = 'itlingo.organization.role'
    _description = 'ITLingo Organization Role'
    _order = 'organization_id, user_id'

    user_id = fields.Many2one(
        'res.users', string='User', required=True, ondelete='cascade',
    )
    organization_id = fields.Many2one(
        'itlingo.organization', string='Organization',
        required=True, ondelete='cascade',
    )
    role = fields.Selection([
        ('org_manager', 'Org Manager'),
        ('org_member', 'Org Member'),
        ('doc_manager', 'Document Manager'),
    ], required=True, default='org_member')
    state = fields.Selection([
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
    ], default='pending', required=True)
    invite_date = fields.Datetime(
        default=fields.Datetime.now, readonly=True,
    )
    response_date = fields.Datetime(readonly=True)
    mailbox_proof_required = fields.Boolean(
        readonly=True, copy=False, default=False,
        help='Legacy pending invitation: the invitee must use the emailed proof link.',
    )

    _unique_user_org = models.Constraint(
        'UNIQUE(user_id, organization_id)',
        'A user can only have one role per organization.',
    )

    # Fields a non-administrator may send. The record rules decide on which
    # rows: invitations by organization managers, role changes by them.
    _INVITE_FIELDS = frozenset({'user_id', 'organization_id', 'role', 'state'})

    def _accepted_managers(self):
        return self.filtered(lambda r: r.role == 'org_manager' and r.state == 'accepted')

    def _cascade_ws_manager(self, workspaces=None):
        """Give each accepted org manager of ``self`` the workspace manager
        role on every workspace of the organization, or only on
        ``workspaces`` (a new workspace) when given. The previous role of an
        upgraded row is kept so that a revocation restores it."""
        ProjectRole = self.env['itlingo.project.role'].sudo()
        Workspace = self.env['itlingo.workspace'].sudo().with_context(active_test=False)
        for rec in self._accepted_managers():
            domain = [('organization_id', '=', rec.organization_id.id)]
            if workspaces is not None:
                domain.append(('id', 'in', workspaces.ids))
            workspaces_of_org = Workspace.search(domain)
            rows = {r.project_id.id: r for r in ProjectRole.search([
                ('user_id', '=', rec.user_id.id), ('project_id', 'in', workspaces_of_org.ids),
            ])}
            for workspace in workspaces_of_org:
                row = rows.get(workspace.id)
                if not row:
                    ProjectRole.create({
                        'user_id': rec.user_id.id,
                        'project_id': workspace.id,
                        'role': 'ws_manager',
                        'state': 'accepted',
                        'grant_source': 'org_manager',
                    })
                elif row.grant_source == 'legacy':
                    # Keep the review marker; the cascade never takes over a
                    # legacy row, so a revocation never relabels it.
                    continue
                elif row.role != 'ws_manager' or row.state != 'accepted':
                    row.write({
                        'role': 'ws_manager',
                        'state': 'accepted',
                        'grant_source': 'org_manager',
                        'cascade_prior_role': row.role,
                        'cascade_prior_state': row.state,
                    })

    @api.model
    def _revoke_ws_manager_cascade(self, pairs):
        """Undo the workspace roles that the org manager role granted to each
        ``(user, organization)`` pair. Explicit and legacy rows stay.

        The rows change as sudo, but the workspace last-manager rule still
        applies to the actor: only a real platform administrator (by group,
        so a non-admin's sudo never qualifies) may leave a workspace without
        a manager, for recovery."""
        ProjectRole = self.env['itlingo.project.role'].sudo()
        workspaces = self.env['itlingo.workspace'].sudo()
        for user, organization in pairs:
            rows = ProjectRole.search([
                ('grant_source', '=', 'org_manager'),
                ('user_id', '=', user.id),
                ('project_id.organization_id', '=', organization.id),
            ])
            restore = rows.filtered('cascade_prior_role')
            for row in restore:
                row.write({
                    'role': row.cascade_prior_role,
                    'state': row.cascade_prior_state or 'accepted',
                    'grant_source': 'explicit',
                    'cascade_prior_role': False,
                    'cascade_prior_state': False,
                })
            workspaces |= rows.project_id
            (rows - restore).unlink()
        if workspaces and not self.env.user.has_group('itlingo_core.group_itlingo_admin'):
            ProjectRole._assert_workspace_managers(workspaces)

    def _check_last_manager(self, organizations):
        # Only a real platform administrator may orphan an organization (by
        # group, so a non-admin's scoped sudo still gets the check).
        if self.env.user.has_group('itlingo_core.group_itlingo_admin'):
            return
        Role = self.sudo()
        for org in organizations.exists():
            if not Role.search_count([
                ('organization_id', '=', org.id),
                ('role', '=', 'org_manager'),
                ('state', '=', 'accepted'),
            ], limit=1):
                raise UserError(_('An organization needs at least one accepted manager.'))

    @api.model_create_multi
    def create(self, vals_list):
        if not _is_itlingo_admin(self.env):
            # Context defaults would bypass the checks below (state, user...).
            self = _strip_default_context(self)
            for vals in vals_list:
                if set(vals) - self._INVITE_FIELDS or vals.get('state', 'pending') != 'pending':
                    raise AccessError(_('Organization managers can only send pending invitations.'))
                # Checked before the insert, so a duplicate row cannot turn
                # the denial into a database error. The create rule agrees.
                org = self.env['itlingo.organization'].browse(vals.get('organization_id')).exists()
                if not org or org._itlingo_user_role().role != 'org_manager':
                    raise AccessError(_('Only organization managers can invite members.'))
        with self.env.cr.savepoint():
            records = super().create(vals_list)
            records._cascade_ws_manager()
        todo_xmlid = 'mail.mail_activity_data_todo'
        for rec in records.sudo():
            if rec.state != 'pending':
                continue
            role_label = dict(rec._fields['role'].selection).get(rec.role, rec.role)
            rec.organization_id.activity_schedule(
                todo_xmlid,
                user_id=rec.user_id.id,
                summary=_('Invitation: %s', rec.organization_id.name),
                note=_(
                    'You were invited to join <b>%s</b> as <b>%s</b>. '
                    'Open your portal at <a href="/my/notifications">My Notifications</a> '
                    'to accept or decline.',
                    rec.organization_id.name,
                    role_label,
                ),
            )
        return records

    def write(self, vals):
        if not _is_itlingo_admin(self.env) and set(vals) - {'role'}:
            raise AccessError(_('Organization managers can only change the role of a member.'))
        if 'role' in vals and not self.env.su and any(
                r.state == 'pending' and r.role != vals['role'] for r in self):
            raise UserError(_('The role of a pending invitation cannot change.'))
        # Savepoint: the checks run after the tentative changes, and a caller
        # that catches the refusal must not keep half of them.
        with self.env.cr.savepoint():
            before = self._accepted_managers()
            res = super().write(vals)
            lost = before - self._accepted_managers()
            self._check_last_manager(lost.organization_id)
            self._revoke_ws_manager_cascade([(r.user_id, r.organization_id) for r in lost])
            (self - before)._cascade_ws_manager()
        return res

    def unlink(self):
        lost = [(r.user_id, r.organization_id) for r in self._accepted_managers()]
        organizations = self._accepted_managers().organization_id
        with self.env.cr.savepoint():
            res = super().unlink()
            self._check_last_manager(organizations)
            self._revoke_ws_manager_cascade(lost)
        return res

    @api.depends('user_id', 'organization_id', 'role')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f'{rec.user_id.sudo().name} - {rec.organization_id.sudo().name} ({rec.role})'

    def _check_invitation_response(self):
        """Only the invitee (or an administrator) answers a pending invitation.
        The role cannot change while pending, so the granted role is the one
        that the manager sent."""
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
            rec.organization_id.message_post(
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
            rec.organization_id.message_post(
                body=_('%s rejected the invitation as %s.',
                       rec.user_id.name, dict(self._fields['role'].selection).get(rec.role)),
                message_type='notification',
                subtype_xmlid='mail.mt_note',
            )
