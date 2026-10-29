from odoo import http
from odoo.addons.rpc.controllers.json2 import WebJson2Controller
from odoo.addons.web.controllers.dataset import DataSet

from .web import _require_platform_admin


class PlatformDataSet(DataSet):
    @http.route()
    def call_kw(self, model, method, args, kwargs, path=None):
        _require_platform_admin()
        return super().call_kw(model, method, args, kwargs, path=path)

    @http.route()
    def call_button(self, model, method, args, kwargs, path=None):
        _require_platform_admin()
        return super().call_button(model, method, args, kwargs, path=path)


class PlatformJson2(WebJson2Controller):
    @http.route()
    def web_json_2_rpc(self, __model__, __method__, **kwargs):
        _require_platform_admin()
        return super().web_json_2_rpc(__model__, __method__, **kwargs)
