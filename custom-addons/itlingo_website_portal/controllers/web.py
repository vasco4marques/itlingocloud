from odoo import http
from werkzeug.exceptions import Forbidden
from odoo.addons.portal.controllers.web import Home as PortalHome
from odoo.addons.website.controllers.main import Website as WebsiteHome
from odoo.addons.website.controllers.main import WebsiteSession
from odoo.http import request


def _require_platform_admin():
    if not request.env.user._itlingo_can_use_backend():
        raise Forbidden('Only platform administrators can use the Odoo backend and model RPC.')


class Website(WebsiteHome):
    """Send portal users to the website home ``/`` after login, not ``/my``."""

    def _login_redirect(self, uid, redirect=None):
        if not redirect:
            user = request.env['res.users'].sudo().browse(uid)
            if user._itlingo_can_use_backend():
                if request.params.get('login_success'):
                    redirect = '/odoo?' + request.httprequest.query_string.decode()
            elif user.org_setup_pending:
                redirect = '/welcome/create-organization'
            else:
                redirect = '/'
        return super()._login_redirect(uid, redirect=redirect)

    @http.route()
    def web_client(self, s_action=None, **kw):
        user = request.env['res.users'].sudo().browse(request.session.uid)
        if user and not user._itlingo_can_use_backend():
            return request.redirect_query('/', query=request.params)
        return super(PortalHome, self).web_client(s_action, **kw)

    @http.route()
    def switch_to_admin(self):
        _require_platform_admin()
        return super().switch_to_admin()

    @http.route()
    def web_load_menus(self, lang=None):
        _require_platform_admin()
        return super().web_load_menus(lang=lang)


class WebsiteLogout(WebsiteSession):
    """Default logout to website home ``/`` when no ``redirect`` query is given."""

    @http.route(auth='public')
    def logout(self, *args, **kw):
        redir = request.params.get('redirect') or '/'
        return super(WebsiteSession, self).logout(redirect=redir)
