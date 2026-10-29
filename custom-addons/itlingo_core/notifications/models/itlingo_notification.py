from odoo import api, fields, models, _
from odoo.exceptions import AccessError

from odoo.addons.itlingo_core.organizations.models.itlingo_organization import _is_itlingo_admin


class ItlingoNotification(models.Model):
    _name = 'itlingo.notification'
    _description = 'ITLingo Notification'
    _order = 'create_date desc'

    user_id = fields.Many2one(
        'res.users', string='Recipient', required=True,
        default=lambda self: self.env.user, index=True, ondelete='cascade',
    )
    notification_type = fields.Selection([
        ('invite', 'Invitation'),
        ('status_change', 'Status Change'),
        ('assignment', 'Assignment'),
        ('mention', 'Mention'),
        ('system', 'System'),
    ], required=True, default='system')
    title = fields.Char(required=True)
    body = fields.Html()
    is_read = fields.Boolean(default=False, index=True)
    read_date = fields.Datetime()

    res_model = fields.Char(string='Related Model')
    res_id = fields.Many2oneReference(
        string='Related Record',
        model_field='res_model',
    )

    INVITE_ROLE_MODELS = ('itlingo.organization.role', 'itlingo.project.role')

    def _linked_invitation_role(self):
        """Return the pending role record this invite notification points to,
        or an empty/None value when the notification is not an actionable
        invitation for its recipient."""
        self.ensure_one()
        if (self.notification_type != 'invite'
                or self.res_model not in self.INVITE_ROLE_MODELS
                or not self.res_id):
            return None
        role = self.env[self.res_model].sudo().browse(self.res_id)
        if role.exists() and role.user_id.id == self.user_id.id:
            # Caller's environment: the role's own actor checks then apply.
            return role.sudo(self.env.su)
        return None

    def _is_pending_invitation(self):
        self.ensure_one()
        role = self._linked_invitation_role()
        return bool(role and role.state == 'pending')

    # Recipients only flip the read flag; title, body, link and recipient
    # come from the system (``_notify``).
    _RECIPIENT_FIELDS = frozenset({'is_read', 'read_date'})

    @api.model_create_multi
    def create(self, vals_list):
        if not _is_itlingo_admin(self.env):
            raise AccessError(_('Notifications are created by the system.'))
        return super().create(vals_list)

    def write(self, vals):
        if not _is_itlingo_admin(self.env) and set(vals) - self._RECIPIENT_FIELDS:
            raise AccessError(_('Only the read state of a notification can change.'))
        return super().write(vals)

    def action_mark_read(self):
        self.filtered(lambda n: not n.is_read).write({
            'is_read': True,
            'read_date': fields.Datetime.now(),
        })

    def action_mark_unread(self):
        self.write({'is_read': False, 'read_date': False})

    @api.model
    def _notify(self, user, title, body, notification_type='system',
                res_model=None, res_id=None):
        """Helper to create a notification for a user."""
        return self.sudo().create({
            'user_id': user.id,
            'title': title,
            'body': body,
            'notification_type': notification_type,
            'res_model': res_model,
            'res_id': res_id,
        })

    @api.model
    def _notify_many(self, users, title, body, notification_type='system',
                     res_model=None, res_id=None):
        """Send the same notification to multiple users."""
        vals_list = [{
            'user_id': u.id,
            'title': title,
            'body': body,
            'notification_type': notification_type,
            'res_model': res_model,
            'res_id': res_id,
        } for u in users]
        return self.sudo().create(vals_list)
