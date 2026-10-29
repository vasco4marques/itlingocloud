from odoo import api, models
from odoo.exceptions import AccessDenied
from odoo.http import request
from werkzeug.exceptions import Forbidden


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _itlingo_can_use_backend(self):
        self.ensure_one()
        return (
            (self.active or self._is_superuser())
            and self._is_internal()
            and self.has_group('itlingo_core.group_itlingo_admin')
        )

    @api.model
    def _check_uid_passwd(self, uid, passwd):
        result = super()._check_uid_passwd(uid, passwd)
        user = self.with_user(uid).env.user
        if not user._itlingo_can_use_backend():
            raise AccessDenied()
        return result


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _pre_dispatch(cls, rule, args):
        if rule.rule.startswith(('/web/action/', '/web/export/')):
            if not request.env.user._itlingo_can_use_backend():
                raise Forbidden('Only platform administrators can use backend actions and exports.')
        return super()._pre_dispatch(rule, args)
