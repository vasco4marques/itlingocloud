from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


def _is_itlingo_admin(env):
    """Superuser code or a platform administrator. Never read from context."""
    return env.su or env.user.has_group('itlingo_core.group_itlingo_admin')


def _strip_default_context(records):
    """Drop client ``default_*`` context keys. They fill fields missing from
    ``vals`` after the create guards ran, so non-admin creates ignore them."""
    ctx = records.env.context
    if any(key.startswith('default_') for key in ctx):
        return records.with_context(
            {k: v for k, v in ctx.items() if not k.startswith('default_')})
    return records


class ItlingoOrganization(models.Model):
    _name = 'itlingo.organization'
    _description = 'ITLingo Organization'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    # Only platform administrators may set these fields. Memberships,
    # workspaces and documents change through their own models.
    _ADMIN_ONLY_FIELDS = frozenset({
        'partner_id', 'company_id', 'state',
        'role_ids', 'workspace_ids', 'document_ids',
    })

    name = fields.Char(required=True, tracking=True)
    activity_type = fields.Selection([
        ('it', 'IT'),
        ('marketing', 'Marketing'),
        ('consulting', 'Consulting'),
        ('finance', 'Finance'),
        ('education', 'Education'),
        ('other', 'Other'),
    ], string='Activity Type', default='it', required=True, tracking=True)
    state = fields.Selection([
        ('active', 'Active'),
        ('suspended', 'Suspended'),
    ], default='active', required=True, tracking=True)
    country_id = fields.Many2one('res.country', string='Country')
    partner_id = fields.Many2one(
        'res.partner', string='Related Contact',
        help='Odoo contact record linked to this organization.',
    )
    description = fields.Html()
    logo = fields.Image(max_width=256, max_height=256)
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company,
    )

    role_ids = fields.One2many(
        'itlingo.organization.role', 'organization_id', string='Roles',
    )
    # Members see the true total even though they may read only their own row.
    member_count = fields.Integer(
        compute='_compute_member_count', string='Members', compute_sudo=True,
    )

    @api.depends('role_ids', 'role_ids.state')
    def _compute_member_count(self):
        for org in self:
            org.member_count = len(
                org.role_ids.filtered(lambda r: r.state == 'accepted')
            )

    def _itlingo_user_role(self, user=None):
        """Accepted role of ``user`` (default: current user), read as sudo."""
        self.ensure_one()
        user = user or self.env.user
        return self.env['itlingo.organization.role'].sudo().search([
            ('organization_id', '=', self.id),
            ('user_id', '=', user.id),
            ('state', '=', 'accepted'),
        ], limit=1)

    def _check_admin_only_fields(self, vals):
        if not _is_itlingo_admin(self.env) and self._ADMIN_ONLY_FIELDS & set(vals):
            raise AccessError(_('Only platform administrators can change %s.',
                                ', '.join(sorted(self._ADMIN_ONLY_FIELDS & set(vals)))))

    @api.model_create_multi
    def create(self, vals_list):
        if not _is_itlingo_admin(self.env):
            self = _strip_default_context(self)
        # Savepoint: a caller that catches a refusal keeps no partial rows.
        with self.env.cr.savepoint():
            for vals in vals_list:
                self._check_admin_only_fields(vals)
                if not vals.get('partner_id'):
                    # Contacts are back-office data: portal users cannot create them.
                    partner = self.env['res.partner'].sudo().create({
                        'name': vals.get('name', ''),
                        'is_company': True,
                        'country_id': vals.get('country_id'),
                        'company_id': vals.get('company_id', self.env.company.id),
                    })
                    vals['partner_id'] = partner.id
            orgs = super().create(vals_list)
            if not self.env.su:
                # Bootstrap: the creator manages the new organization.
                self.env['itlingo.organization.role'].sudo().create([{
                    'organization_id': org.id,
                    'user_id': self.env.user.id,
                    'role': 'org_manager',
                    'state': 'accepted',
                } for org in orgs])
        return orgs

    def write(self, vals):
        self._check_admin_only_fields(vals)
        return super().write(vals)

    def unlink(self):
        if not self.env.su and 'itlingo.workspace' in self.env and self.env[
                'itlingo.workspace'].sudo().with_context(active_test=False).search_count(
                    [('organization_id', 'in', self.ids)], limit=1):
            raise UserError(_('Delete the workspaces of this organization first.'))
        return super().unlink()

    def action_suspend(self):
        self.write({'state': 'suspended'})

    def action_activate(self):
        self.write({'state': 'active'})

    def action_invite_member(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Invite Member'),
            'res_model': 'itlingo.organization.role',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_organization_id': self.id,
                'default_state': 'pending',
            },
        }
