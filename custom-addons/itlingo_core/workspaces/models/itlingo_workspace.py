from odoo import api, fields, models, _
from odoo.exceptions import AccessError
import uuid

from odoo.addons.itlingo_core.organizations.models.itlingo_organization import (
    _is_itlingo_admin, _strip_default_context,
)


class ItlingoWorkspace(models.Model):
    _name = 'itlingo.workspace'
    _description = 'ITLingo Workspace'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(string='Name', required=True, tracking=True)
    description = fields.Html(string='Description')
    active = fields.Boolean(string='Active', default=True)

    organization_id = fields.Many2one(
        'itlingo.organization', string='Organization',
        tracking=True,
        domain="[('state', '=', 'active')]",
    )
    creator_id = fields.Many2one(
        'res.users', string='Creator',
        default=lambda self: self.env.user,
        readonly=True,
    )
    business_status = fields.Selection([
        ('not_started', 'Not Started'),
        ('executing', 'Executing'),
        ('canceled', 'Canceled'),
        ('concluded', 'Concluded'),
    ], string='State', default='not_started', tracking=True)
    planned_start = fields.Date(string='Planned Start')
    planned_end = fields.Date(string='Planned End')
    actual_start = fields.Date(string='Actual Start')
    actual_end = fields.Date(string='Actual End')
    is_public_workspace = fields.Boolean(
        string='Public workspace',
        default=False,
        tracking=True,
        help='If enabled, the workspace is listed on the public workspace page and all users can view its documents, specifications and AI chats.',
    )

    workspace_key = fields.Char(
        string='Workspace Key',
        required=True,
        readonly=True,
        default=lambda self: str(uuid.uuid4()),
        help='Stable external identifier (UUID) used by external services to reference this workspace',
        copy=False,
        index=True,
    )

    _unique_workspace_key = models.Constraint(
        'UNIQUE(workspace_key)',
        'Each workspace must have a unique workspace key.',
    )

    workspace_role_ids = fields.One2many(
        'itlingo.project.role', 'project_id', string='Workspace Roles',
    )
    workspace_member_count = fields.Integer(
        compute='_compute_workspace_member_count', string='Workspace Members',
    )

    # Identity and scope: set once by the system, changed only by admins.
    _ADMIN_ONLY_FIELDS = frozenset({
        'organization_id', 'creator_id', 'workspace_key', 'workspace_role_ids', 'document_ids',
    })

    @api.depends('workspace_role_ids', 'workspace_role_ids.state')
    def _compute_workspace_member_count(self):
        for workspace in self:
            workspace.workspace_member_count = len(
                workspace.workspace_role_ids.filtered(lambda r: r.state == 'accepted')
            )

    def _itlingo_user_role(self, user=None):
        """Accepted role of ``user`` (default: current user), read as sudo."""
        self.ensure_one()
        user = user or self.env.user
        return self.env['itlingo.project.role'].sudo().search([
            ('project_id', '=', self.id),
            ('user_id', '=', user.id),
            ('state', '=', 'accepted'),
        ], limit=1)

    @api.model_create_multi
    def create(self, vals_list):
        if not _is_itlingo_admin(self.env):
            # Context defaults would set creator/key/scope after these checks.
            self = _strip_default_context(self)
            for vals in vals_list:
                locked = set(vals) & (self._ADMIN_ONLY_FIELDS - {'organization_id'})
                if vals.get('creator_id') == self.env.user.id:
                    locked.discard('creator_id')
                if locked or not vals.get('organization_id'):
                    raise AccessError(_(
                        'A workspace needs an organization; its creator and key are set by the system.'))
        # The create rule requires an accepted role in the organization.
        with self.env.cr.savepoint():
            workspaces = super().create(vals_list)
            if not self.env.su:
                # Bootstrap: the creator manages the new workspace.
                self.env['itlingo.project.role'].sudo().create([{
                    'project_id': ws.id,
                    'user_id': self.env.user.id,
                    'role': 'ws_manager',
                    'state': 'accepted',
                } for ws in workspaces])
            # Org managers manage every workspace of their organization
            # (same policy as on promotion); only the new workspaces.
            self.env['itlingo.organization.role'].sudo().search([
                ('organization_id', 'in', workspaces.organization_id.ids),
                ('role', '=', 'org_manager'),
                ('state', '=', 'accepted'),
            ])._cascade_ws_manager(workspaces)
        return workspaces

    def write(self, vals):
        if not _is_itlingo_admin(self.env) and self._ADMIN_ONLY_FIELDS & set(vals):
            raise AccessError(_('Only platform administrators can change %s.',
                                ', '.join(sorted(self._ADMIN_ONLY_FIELDS & set(vals)))))
        return super().write(vals)

    def action_invite_workspace_member(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Invite Workspace Member'),
            'res_model': 'itlingo.project.role',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_project_id': self.id,
                'default_state': 'pending',
            },
        }

    def action_start(self):
        self.write({
            'business_status': 'executing',
            'actual_start': fields.Date.context_today(self),
        })

    def action_conclude(self):
        self.write({
            'business_status': 'concluded',
            'actual_end': fields.Date.context_today(self),
        })

    def action_cancel(self):
        self.write({'business_status': 'canceled'})

    def action_reset(self):
        self.write({'business_status': 'not_started'})
