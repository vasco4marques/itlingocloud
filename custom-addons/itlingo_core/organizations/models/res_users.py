from odoo import api, fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    org_setup_pending = fields.Boolean(
        default=False,
        help='When True the user is redirected to the welcome '
             'organisation-creation screen on next login.',
    )

    @property
    def SELF_WRITEABLE_FIELDS(self):
        # Users close their own welcome screen without sudo.
        return super().SELF_WRITEABLE_FIELDS + ['org_setup_pending']

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        itlingo_member = self.env.ref(
            'itlingo_core.group_itlingo_member',
            raise_if_not_found=False,
        )
        if not itlingo_member:
            return users
        # A user created from the invited contact (native signup token) gets
        # its invitations, whatever its groups. Only active portal accounts
        # join ITLingo: the inactive portal template, the public user and
        # internal users stay unchanged.
        Pending = self.env['itlingo.pending.invitation']
        for user in users.filtered('active'):
            claimed = Pending._claim_for_user(user)
            if user.has_group('base.group_portal') \
                    and not user.has_group('itlingo_core.group_itlingo_member'):
                self.env.cr.execute(
                    "INSERT INTO res_groups_users_rel (gid, uid) "
                    "VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (itlingo_member.id, user.id),
                )
                if not claimed:
                    user.sudo().org_setup_pending = True
        self.env.registry.clear_cache()
        return users
