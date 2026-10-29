import json
import os
import time
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import requests

from odoo import SUPERUSER_ID, api
from odoo.modules.registry import DummyRLock, Registry
from odoo.tests import HttpCase, new_test_user, tagged
from odoo.tools import mute_logger

from ..controllers import chat
from ..controllers.chat import ChatController, _sign_payload

SECRET = 'chatbot-push-transaction-secret'
AES_KEY = 'push-transaction-test-key-000001'


@tagged('post_install', '-at_install')
class TestExportPushTransaction(HttpCase):
    """Chatbot export -> ITOI push across real, separate DB connections.

    Outside registry test mode every HTTP request runs on its own database
    connection and sees committed rows only, as in production. The ITOI
    stand-in does what ITOI's ``/pushFile`` does first: it calls the real
    ``/token_api/validate-launch`` over HTTP while the export request is still
    open. Fixtures are therefore committed here and removed in cleanup.

    The test runner holds ``Registry._lock`` while it runs post-install
    tests, and request threads take it to look up the registry. Only that
    lock and registry signaling are patched, as registry test mode does;
    ``registry.cursor`` is not, so requests keep their own connections.
    """
    registry_test_mode = False

    @contextmanager
    def _env(self):
        """Superuser environment on a new connection, committed on exit."""
        with self.registry.cursor() as cr:
            yield api.Environment(cr, SUPERUSER_ID, {})

    def setUp(self):
        super().setUp()
        self.startPatcher(patch.object(Registry, '_lock', DummyRLock()))
        self.startPatcher(patch.object(
            self.registry, 'setup_signaling', return_value=None))
        self.startPatcher(patch.object(
            self.registry, 'check_signaling', return_value=self.registry))
        tag = uuid.uuid4().hex[:8]
        with self._env() as env:
            settings = env['itlingo.integration.settings']._get_settings()
            saved = {
                name: settings[name]
                for name in ('encryption_key', 'itoi_url', 'importable_extensions')
            }
            settings.write({
                'encryption_key': AES_KEY,
                'itoi_url': 'http://itoi.test',
                'importable_extensions': 'txt',
            })
            editor = new_test_user(
                env, login='push_tx_editor_' + tag, groups='base.group_portal')
            reader = new_test_user(
                env, login='push_tx_reader_' + tag, groups='base.group_portal')
            workspace = env['itlingo.workspace'].create({
                'name': 'Push transaction workspace ' + tag,
            })
            for user, role in ((editor, 'doc_manager'), (reader, 'ws_member')):
                env['itlingo.project.role'].create({
                    'user_id': user.id,
                    'project_id': workspace.id,
                    'role': role,
                    'state': 'accepted',
                })
            self.settings_id = settings.id
            self.editor_id, self.editor_login = editor.id, editor.login
            self.reader_id = reader.id
            self.workspace_id = workspace.id
        self.addCleanup(self._cleanup, saved)
        self.startPatcher(patch.dict(os.environ, {'ITLINGO_CHATBOT_SECRET': SECRET}))
        self.startPatcher(patch.object(chat.http_requests, 'post', self._itoi_push_file))
        self.validations = []

    def _cleanup(self, saved):
        with self._env() as env:
            users = env['res.users'].browse([self.editor_id, self.reader_id])
            partners = users.partner_id
            env['itlingo.document'].search([
                ('project_id', '=', self.workspace_id),
            ]).unlink()
            env['itlingo.integration.token'].search([
                ('user_id', 'in', users.ids),
            ]).unlink()
            env['itlingo.workspace'].browse(self.workspace_id).unlink()
            users.unlink()
            partners.unlink()
            env['itlingo.integration.settings'].browse(self.settings_id).write(saved)

    def _validate(self, authorization):
        return requests.get(
            self.base_url() + '/token_api/validate-launch',
            headers={
                'Authorization': authorization,
                'X-Odoo-Database': self.cr.dbname,
            },
            timeout=10,
        )

    def _itoi_push_file(self, url, headers=None, json=None, timeout=None):
        """ITOI ``/pushFile`` stand-in: revalidate online, then accept."""
        response = self._validate(headers['Authorization'])
        self.validations.append((headers['Authorization'], response))
        if response.status_code == 200 and response.json()['write']:
            body, status = {
                'pushed': True, 'live': False, 'file_name': json['filename'],
            }, 200
        else:
            body, status = {
                'code': 'auth_denied', 'error': 'Token rejected by ITLingo Cloud',
            }, 401
        return SimpleNamespace(
            status_code=status, json=lambda: body, text=str(body))

    def _export(self, user_id, read_only=False):
        now = int(time.time())
        token = _sign_payload(SECRET, {
            'read_only': read_only,
            'aud': 'itlingo-chatbot',
            'sub': user_id,
            'odoo_user_id': user_id,
            'workspace_id': self.workspace_id,
            'iat': now,
            'exp': now + 3600,
        })
        return self.url_open(
            '/chatbot_api/v1/export-document',
            data=json.dumps({
                'workspace_id': self.workspace_id,
                'filename': 'pushed.txt',
                'content': 'exported text',
            }),
            headers={
                'Authorization': 'Bearer %s' % token,
                'Content-Type': 'application/json',
                'X-Odoo-Database': self.cr.dbname,
            },
        )

    def _committed(self):
        """Documents and launch tokens of the fixture, as committed now."""
        with self._env() as env:
            documents = env['itlingo.document'].search([
                ('project_id', '=', self.workspace_id),
            ])
            tokens = env['itlingo.integration.token'].search([
                ('user_id', 'in', [self.editor_id, self.reader_id]),
            ])
            return (
                [(d.file_name, d.creator_id.id) for d in documents],
                [(t.token_kind, t.launch_write, t.is_active) for t in tokens],
            )

    def test_push_token_is_valid_on_another_connection_then_revoked(self):
        response = self._export(self.editor_id)
        self.assertEqual(response.status_code, 200, response.text)
        itoi = response.json()['itoi']
        self.assertEqual(
            (itoi['pushed'], itoi['reason_code']), (True, None), itoi)

        # ITOI's online check ran while the export request was still open.
        [(authorization, validation)] = self.validations
        self.assertEqual(validation.status_code, 200, validation.text)
        launch = validation.json()
        self.assertEqual(
            (launch['user'], launch['wsid'], launch['write'], launch['public']),
            (self.editor_login, self.workspace_id, True, False))

        documents, tokens = self._committed()
        self.assertEqual(documents, [('pushed.txt', self.editor_id)])
        self.assertEqual(tokens, [('launch', True, False)])
        denied = self._validate(authorization)
        self.assertEqual(denied.status_code, 401, denied.text)
        self.assertEqual(denied.headers['Cache-Control'], 'no-store')

    def test_failed_request_commits_no_document_and_revokes_token(self):
        with mute_logger('odoo.http'), patch.object(
                ChatController, '_json_response',
                side_effect=RuntimeError('fail after push')):
            response = self._export(self.editor_id)
        self.assertEqual(response.status_code, 500, response.text)

        # Known window: ITOI accepted the file before the request failed;
        # ITLingo Cloud keeps neither the document nor a usable token.
        [(authorization, validation)] = self.validations
        self.assertEqual(validation.status_code, 200, validation.text)
        documents, tokens = self._committed()
        self.assertEqual(documents, [])
        self.assertEqual(tokens, [('launch', True, False)])
        self.assertEqual(self._validate(authorization).status_code, 401)

    def test_read_only_token_and_reader_issue_no_launch_token(self):
        for user_id, read_only in ((self.editor_id, True), (self.reader_id, False)):
            response = self._export(user_id, read_only=read_only)
            self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.validations, [])
        self.assertEqual(self._committed(), ([], []))
