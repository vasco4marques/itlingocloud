import json
import time

from odoo.exceptions import AccessError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged

from ..controllers.chat import _sign_payload

SHARED_MODELS = (
    'itlingo.chat.workspace', 'itlingo.chat.folder', 'itlingo.chat.thread',
    'itlingo.chat.message', 'itlingo.model.usage', 'itlingo.thread.file',
    'itlingo.thread.file.chunk', 'itlingo.message.file.link',
    'itlingo.ops.configuration', 'itlingo.kb.language', 'itlingo.kb.file',
    'itlingo.session.settings', 'itlingo.chatbot.settings',
    'itlingo.chatbot.settings.provider', 'itlingo.chatbot.settings.option',
    'itlingo.sys.instruction',
)


@tagged('post_install', '-at_install')
class TestChatbotModelAccess(TransactionCase):

    def test_shared_chatbot_models_are_admin_only(self):
        internal = new_test_user(
            self.env, login='chatbot_acl_internal', groups='base.group_user')
        member = new_test_user(
            self.env, login='chatbot_acl_member',
            groups='itlingo_core.group_itlingo_member')
        portal = new_test_user(
            self.env, login='chatbot_acl_portal', groups='base.group_portal')
        admin = new_test_user(
            self.env, login='chatbot_acl_admin',
            groups='base.group_user,itlingo_core.group_itlingo_admin')
        for model in SHARED_MODELS:
            for user in (internal, member, portal):
                for operation in ('read', 'write', 'create', 'unlink'):
                    with self.assertRaises(AccessError, msg=(model, operation)):
                        self.env[model].with_user(user).check_access(operation)
            for operation in ('read', 'write', 'create', 'unlink'):
                self.env[model].with_user(admin).check_access(operation)


@tagged('post_install', '-at_install')
class TestChatbotLaunchAndExport(HttpCase):

    SECRET = 'chatbot-security-test-secret'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param(
            'itlingo_chatbot.secret', cls.SECRET)
        cls.env['itlingo.integration.settings'].sudo()._get_settings().write({
            'itoi_url': '',
            'importable_extensions': 'txt',
        })
        cls.editor = new_test_user(
            cls.env, login='chatbot_sec_editor', groups='base.group_portal')
        cls.reader = new_test_user(
            cls.env, login='chatbot_sec_reader', groups='base.group_portal')
        cls.outsider = new_test_user(
            cls.env, login='chatbot_sec_outsider', groups='base.group_portal')
        cls.private_ws = cls.env['itlingo.workspace'].create({
            'name': 'Chatbot private workspace',
        })
        cls.public_ws = cls.env['itlingo.workspace'].create({
            'name': 'Chatbot public workspace',
            'is_public_workspace': True,
        })
        for user, role in ((cls.editor, 'doc_manager'), (cls.reader, 'ws_member')):
            cls.env['itlingo.project.role'].create({
                'user_id': user.id,
                'project_id': cls.private_ws.id,
                'role': role,
                'state': 'accepted',
            })

    def _token(self, user, read_only=False, **claims):
        now = int(time.time())
        payload = {
            'read_only': read_only,
            'aud': 'itlingo-chatbot',
            'sub': user.id,
            'odoo_user_id': user.id,
            'odoo_user_login': user.login,
            'workspace_id': self.private_ws.id,
            'iat': now,
            'exp': now + 3600,
        }
        payload.update(claims)
        return _sign_payload(self.SECRET, payload)

    def _export(self, token, filename='notes.txt'):
        return self.url_open(
            '/chatbot_api/v1/export-document',
            data=json.dumps({
                'workspace_id': self.private_ws.id,
                'filename': filename,
                'content': 'exported text',
            }),
            headers={
                'Authorization': 'Bearer %s' % token,
                'Content-Type': 'application/json',
            },
        )

    def _documents(self, filename='notes.txt'):
        return self.env['itlingo.document'].search([
            ('project_id', '=', self.private_ws.id),
            ('file_name', '=', filename),
        ])

    def test_private_chat_denies_nonmember(self):
        self.authenticate(self.outsider.login, self.outsider.login)
        response = self.url_open(
            '/my/workspaces/%s/chat' % self.private_ws.id,
            allow_redirects=False)
        self.assertEqual(response.status_code, 404)

        response = self.url_open(
            '/my/workspaces/%s/chat' % self.public_ws.id,
            allow_redirects=False)
        self.assertIn(response.status_code, (301, 302, 303))
        self.assertTrue(response.headers['Location'].endswith(
            '/public-workspaces/%s/chat' % self.public_ws.id))

    def test_export_by_writer_creates_document_as_principal(self):
        response = self._export(self._token(self.editor))
        self.assertEqual(response.status_code, 200, response.text)
        document = self._documents()
        self.assertEqual(len(document), 1)
        self.assertEqual(document.creator_id, self.editor)
        self.assertEqual(json.loads(response.text)['itoi']['reason_code'],
                         'not_configured')

    def test_export_denials(self):
        expired = self._token(self.editor, exp=int(time.time()) - 1)
        header, payload, signature = self._token(self.editor).split('.')
        forged = '.'.join((header, payload, signature[::-1]))
        cases = (
            (self._token(self.editor, read_only=True), 403),
            (self._token(self.reader), 403),
            (self._token(self.outsider), 403),
            (self._token(self.editor, workspace_id=self.public_ws.id), 403),
            (expired, 401),
            (forged, 401),
        )
        for token, status in cases:
            response = self._export(token)
            self.assertEqual(response.status_code, status, response.text)

        self.editor.active = False
        response = self._export(self._token(self.editor))
        self.assertEqual(response.status_code, 401, response.text)
        self.assertFalse(self._documents())
