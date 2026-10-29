import json
import xmlrpc.client
from datetime import timedelta
from urllib.parse import urlsplit

from odoo import Command, fields
from odoo.exceptions import AccessDenied
from odoo.tests import HttpCase, JsonRpcException, new_test_user, tagged
from odoo.tools.misc import mute_logger


@tagged('post_install', '-at_install')
class TestPlatformRpcAccess(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.portal = new_test_user(
            cls.env, login='rpc_portal', password='rpc_portal',
            groups='base.group_portal,itlingo_core.group_itlingo_member',
        )
        cls.internal = new_test_user(
            cls.env, login='rpc_internal', password='rpc_internal',
            groups='base.group_user',
        )
        cls.administrator = new_test_user(
            cls.env, login='rpc_administrator', password='rpc_administrator',
            groups='base.group_system,itlingo_core.group_itlingo_admin',
        )
        cls.organization = cls.env['itlingo.organization'].create({
            'name': 'RPC boundary organization',
        })
        cls.document = cls.env['itlingo.document'].create({
            'name': 'RPC review document',
            'organization_id': cls.organization.id,
        })
        cls.keys = {
            user.id: cls.env['res.users.apikeys'].with_user(user)._generate(
                None, 'RPC boundary check',
                fields.Datetime.now() + timedelta(hours=1),
            )
            for user in (cls.portal, cls.internal, cls.administrator)
        }

    def _search_params(self):
        return {
            'model': 'itlingo.organization',
            'method': 'search_read',
            'args': [[('id', '=', self.organization.id)]],
            'kwargs': {'fields': ['name']},
        }

    def _expected_records(self):
        return [{'id': self.organization.id, 'name': self.organization.name}]

    def test_generic_session_rpc_requires_platform_administrator(self):
        paths = (
            '/web/dataset/call_kw',
            '/web/dataset/call_kw/itlingo.organization.search_read',
            '/web/dataset/call_button',
        )
        for user in (self.portal, self.internal):
            self.authenticate(user.login, user.login)
            for path in paths:
                with self.subTest(user=user.login, path=path):
                    params = self._search_params()
                    params['kwargs']['context'] = {
                        'uid': self.administrator.id, 'sudo': True,
                    }
                    with self.assertRaises(JsonRpcException), mute_logger('odoo.http'):
                        self.make_jsonrpc_request(path, params)
        self.authenticate(self.administrator.login, self.administrator.login)
        for path in paths[:2]:
            self.assertEqual(
                self.make_jsonrpc_request(path, self._search_params()),
                self._expected_records(),
            )
        self.assertFalse(self.make_jsonrpc_request(
            '/web/dataset/call_button', {
                'model': 'itlingo.document', 'method': 'action_submit_review',
                'args': [[self.document.id]], 'kwargs': {},
            },
        ))

        self.document.invalidate_recordset(['status'])
        self.assertEqual(self.document.status, 'in_review')

    def test_json2_api_keys_require_platform_administrator(self):
        for user in (self.portal, self.internal, self.administrator):
            self.authenticate(None, None)
            response = self.url_open(
                '/json/2/itlingo.organization/search_read',
                data=json.dumps({
                    'domain': [('id', '=', self.organization.id)],
                    'fields': ['name'],
                }),
                headers={
                    'Authorization': 'Bearer ' + self.keys[user.id],
                    'Content-Type': 'application/json',
                },
            )
            if user == self.administrator:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), self._expected_records())
            else:
                self.assertEqual(response.status_code, 403)

    def test_legacy_rpc_checks_the_credential_user(self):
        self.authenticate(self.administrator.login, self.administrator.login)
        for user in (self.portal, self.internal, self.administrator):
            args = [
                self.env.cr.dbname, user.id, user.login,
                'itlingo.organization', 'search_read',
                [[('id', '=', self.organization.id)]], {'fields': ['name']},
            ]
            response = self.url_open(
                '/jsonrpc', data=json.dumps({
                    'jsonrpc': '2.0', 'method': 'call', 'id': 1,
                    'params': {'service': 'object', 'method': 'execute_kw', 'args': args},
                }), headers={'Content-Type': 'application/json'},
            )
            result = response.json()
            if user == self.administrator:
                self.assertEqual(result['result'], self._expected_records())
            else:
                self.assertIn('error', result)
                self.assertEqual(result['error']['data']['name'], 'odoo.exceptions.AccessDenied')
            response = self.url_open(
                '/xmlrpc/2/object',
                data=xmlrpc.client.dumps(tuple(args), methodname='execute_kw'),
                headers={'Content-Type': 'text/xml'},
            )
            if user == self.administrator:
                records, _method = xmlrpc.client.loads(response.content)
                self.assertEqual(records[0], self._expected_records())
            else:
                with self.assertRaises(xmlrpc.client.Fault) as fault:
                    xmlrpc.client.loads(response.content)
                self.assertEqual(fault.exception.faultCode, 3)

    def test_backend_and_privilege_switch_require_platform_administrator(self):
        for user in (self.portal, self.internal):
            self.authenticate(user.login, user.login)
            for path in ('/web', '/odoo', '/odoo/action-1', '/scoped_app/test'):
                response = self.url_open(path, allow_redirects=False)
                self.assertIn(response.status_code, (302, 303))
                self.assertEqual(urlsplit(response.headers['Location']).path, '/')
            self.assertEqual(self.url_open('/web/become').status_code, 403)
            with self.assertRaises(JsonRpcException), mute_logger('odoo.http'):
                self.make_jsonrpc_request('/web/action/run', {'action_id': 1})
            with self.assertRaises(JsonRpcException), mute_logger('odoo.http'):
                self.make_jsonrpc_request('/web/export/get_fields', {'model': 'itlingo.organization'})
        self.authenticate(self.administrator.login, self.administrator.login)
        self.assertEqual(self.url_open('/odoo').status_code, 200)
        response = self.url_open('/web/become', allow_redirects=False)
        self.assertIn(response.status_code, (302, 303))
        self.assertEqual(
            self.make_jsonrpc_request('/web/dataset/call_kw', self._search_params()),
            self._expected_records(),
        )

    def test_admin_role_revocation_applies_to_cached_credentials(self):
        Users = self.env['res.users']
        Users._check_uid_passwd(self.administrator.id, self.administrator.login)
        self.administrator.write({
            'group_ids': [Command.unlink(self.env.ref('itlingo_core.group_itlingo_admin').id)],
        })
        with self.assertRaises(AccessDenied):
            Users._check_uid_passwd(self.administrator.id, self.administrator.login)
        self.authenticate(self.administrator.login, self.administrator.login)
        response = self.url_open(
            '/json/2/itlingo.organization/search_read',
            data=json.dumps({'domain': [], 'fields': ['name']}),
            headers={
                'Authorization': 'Bearer ' + self.keys[self.administrator.id],
                'Content-Type': 'application/json',
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_inactive_administrator_cannot_use_an_existing_api_key(self):
        self.administrator.active = False
        self.authenticate(None, None)
        response = self.url_open(
            '/json/2/itlingo.organization/search_read',
            data=json.dumps({'domain': [], 'fields': ['name']}),
            headers={
                'Authorization': 'Bearer ' + self.keys[self.administrator.id],
                'Content-Type': 'application/json',
            },
        )
        self.assertIn(response.status_code, (401, 403))
