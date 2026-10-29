from odoo import api, models, _


class ItlingoOrganizationRole(models.Model):
    _inherit = 'itlingo.organization.role'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        Notif = self.env['itlingo.notification']
        template = self.env.ref(
            'itlingo_core.mail_template_itlingo_invitation',
            raise_if_not_found=False,
        )
        # System notification: the invitee's address and the template are
        # not readable by the inviting manager.
        for role in records.sudo():
            if role.state != 'pending':
                continue
            role_label = dict(role._fields['role'].selection).get(role.role, role.role)
            body = _(
                'You were invited to join <b>%s</b> as <b>%s</b>. '
                'Respond from <a href="/my/notifications">your notifications</a>.',
                role.organization_id.name,
                role_label,
            )
            notif = Notif._notify(
                role.user_id,
                _('Invitation: %s', role.organization_id.name),
                body,
                notification_type='invite',
                res_model='itlingo.organization.role',
                res_id=role.id,
            )
            if template and role.user_id.email:
                template.sudo().send_mail(notif.id, force_send=False)
        return records

    def action_accept(self):
        res = super().action_accept()
        Notif = self.env['itlingo.notification']
        for role in self.sudo():
            managers = role.organization_id.role_ids.filtered(
                lambda r: r.role == 'org_manager' and r.state == 'accepted'
            ).mapped('user_id')
            Notif._notify_many(
                managers,
                _('%s accepted the invitation', role.user_id.name),
                _('%s joined organization <b>%s</b>.',
                  role.user_id.name, role.organization_id.name),
                notification_type='invite',
                res_model='itlingo.organization',
                res_id=role.organization_id.id,
            )
        return res

    def action_reject(self):
        res = super().action_reject()
        Notif = self.env['itlingo.notification']
        for role in self.sudo():
            managers = role.organization_id.role_ids.filtered(
                lambda r: r.role == 'org_manager' and r.state == 'accepted'
            ).mapped('user_id')
            Notif._notify_many(
                managers,
                _('%s rejected the invitation', role.user_id.name),
                _('%s declined to join organization <b>%s</b>.',
                  role.user_id.name, role.organization_id.name),
                notification_type='invite',
                res_model='itlingo.organization',
                res_id=role.organization_id.id,
            )
        return res
