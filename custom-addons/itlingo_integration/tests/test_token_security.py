import base64
import json
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import HttpCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestTokenSecurity(HttpCase):
    """Launch/API token authorization at the model and HTTP boundary."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Token = cls.env["itlingo.integration.token"]
        cls.settings = (
            cls.env["itlingo.integration.settings"].sudo()._get_settings()
        )
        cls.settings.write({
            "encryption_key": "test-key-for-itoi-boundary-00001",
            "itoi_url": "http://itoi.test/",
            "importable_extensions": "txt",
        })
        cls.member = new_test_user(
            cls.env, login="itoi_sec_member", groups="base.group_portal")
        cls.outsider = new_test_user(
            cls.env, login="itoi_sec_outsider", groups="base.group_portal")
        cls.admin = new_test_user(
            cls.env, login="itoi_sec_admin",
            groups="base.group_user,itlingo_core.group_itlingo_admin")
        cls.organization = cls.env["itlingo.organization"].create({
            "name": "ITOI security organization",
        })
        cls.private_ws = cls.env["itlingo.workspace"].create({
            "name": "ITOI private workspace",
            "organization_id": cls.organization.id,
        })
        cls.public_ws = cls.env["itlingo.workspace"].create({
            "name": "ITOI public workspace",
            "organization_id": cls.organization.id,
            "is_public_workspace": True,
        })
        # Workspace document editors read drafts; plain members and the
        # public read published documents only (core document policy).
        for workspace, role in (
                (cls.private_ws, "ws_member"), (cls.public_ws, "doc_manager")):
            cls.env["itlingo.project.role"].create({
                "user_id": cls.member.id,
                "project_id": workspace.id,
                "role": role,
                "state": "accepted",
            })
        cls.env["itlingo.organization.role"].create({
            "user_id": cls.member.id,
            "organization_id": cls.organization.id,
            "role": "org_member",
            "state": "accepted",
        })
        doc_type = cls.env.ref("itlingo_core.doc_type_specification")

        def document(name, status="draft", **scope):
            return cls.env["itlingo.document"].create(dict(
                scope,
                name=name,
                document_type_id=doc_type.id,
                file_name="%s.txt" % name,
                document_file=base64.b64encode(name.encode()),
                status=status,
            ))

        cls.public_published = document(
            "public-published", "published", project_id=cls.public_ws.id)
        cls.public_draft = document("public-draft", project_id=cls.public_ws.id)
        cls.org_document = document(
            "org-only", "published", organization_id=cls.organization.id)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _launch(self, user, workspace, write=False, public=False):
        return self.Token._issue_launch_token(
            user, workspace, write, public=public)

    def _get(self, path, iv, ct):
        return self.url_open(
            path, headers={"Authorization": "Bearer %s:%s" % (iv, ct)})

    def _file_names(self, workspace, iv, ct):
        response = self._get(
            "/token_api/get-file-list/%s" % workspace.id, iv, ct)
        self.assertEqual(response.status_code, 200, response.text)
        return {item["name"] for item in json.loads(response.text)["namelist"]}

    def _row(self, iv, ct):
        return self.Token.sudo().search([
            ("token_iv", "=", iv), ("token_ct", "=", ct),
        ])

    # ------------------------------------------------------------------
    # launch routes
    # ------------------------------------------------------------------

    def test_private_launch_denies_nonmember(self):
        self.authenticate(self.outsider.login, self.outsider.login)
        response = self.url_open(
            "/itoi/launch/%s" % self.private_ws.id, allow_redirects=False)
        self.assertEqual(response.status_code, 404)
        self.assertFalse(self.Token.sudo().search([
            ("user_id", "=", self.outsider.id),
        ]))

    def test_private_launch_sends_nonmember_of_public_ws_to_public_launch(self):
        self.authenticate(self.outsider.login, self.outsider.login)
        response = self.url_open(
            "/itoi/launch/%s" % self.public_ws.id, allow_redirects=False)
        self.assertIn(response.status_code, (301, 302, 303))
        self.assertTrue(response.headers["Location"].endswith(
            "/itoi/launch/public/%s" % self.public_ws.id))

    def test_member_launch_persists_unchanged_payload(self):
        self.authenticate(self.member.login, self.member.login)
        response = self.url_open(
            "/itoi/launch/%s" % self.private_ws.id, allow_redirects=False)
        self.assertEqual(response.status_code, 302)
        location = urlparse(response.headers["Location"])
        self.assertEqual(location.path, "/createTempWorkspace")
        query = parse_qs(location.query)
        iv, ct = query["iv"][0], query["t"][0]
        self.assertEqual(json.loads(self.settings._aes_decrypt(iv, ct)), {
            "user": self.member.login,
            "workspace": self.private_ws.name,
            "organization": self.organization.name,
            "write": False,
            "wsid": self.private_ws.id,
        })
        row = self._row(iv, ct)
        self.assertEqual(row.token_kind, "launch")
        self.assertEqual(row.user_id, self.member)
        self.assertEqual(row.project_id, self.private_ws)
        self.assertTrue(row.expires_at > fields.Datetime.now())

    def test_public_launch_requires_public_flag(self):
        response = self.url_open(
            "/itoi/launch/public/%s" % self.private_ws.id,
            allow_redirects=False)
        self.assertEqual(response.status_code, 404)

    def test_logged_in_public_launch_is_public_scoped(self):
        """A member using the explicit public launch gets no org documents."""
        self.authenticate(self.member.login, self.member.login)
        response = self.url_open(
            "/itoi/launch/public/%s" % self.public_ws.id,
            allow_redirects=False)
        self.assertEqual(response.status_code, 302)
        query = parse_qs(urlparse(response.headers["Location"]).query)
        iv, ct = query["iv"][0], query["t"][0]
        self.assertFalse(json.loads(self.settings._aes_decrypt(iv, ct))["write"])
        row = self._row(iv, ct)
        self.assertTrue(row.public_scope)
        self.assertFalse(row.launch_write)
        self.assertEqual(
            self._file_names(self.public_ws, iv, ct), {"public-published.txt"})

    # ------------------------------------------------------------------
    # token_api document scope
    # ------------------------------------------------------------------

    def test_member_sees_workspace_and_organization_documents(self):
        names = self._file_names(
            self.public_ws, *self._launch(self.member, self.public_ws))
        self.assertEqual(names, {
            "public-published.txt", "public-draft.txt", "org-only.txt",
        })

    def test_public_token_sees_only_published_workspace_documents(self):
        org_manager = new_test_user(
            self.env, login="itoi_sec_org_manager", groups="base.group_portal")
        self.env["itlingo.organization.role"].create({
            "user_id": org_manager.id,
            "organization_id": self.organization.id,
            "role": "org_manager",
            "state": "accepted",
        })
        for user in (self.outsider, self.member, org_manager,
                     self.env.ref("base.public_user")):
            iv, ct = self._launch(user, self.public_ws, public=True)
            self.assertEqual(
                self._file_names(self.public_ws, iv, ct),
                {"public-published.txt"},
            )
            response = self._get(
                "/token_api/download-file/%s/%s"
                % (self.public_ws.id, self.org_document.id), iv, ct)
            self.assertEqual(response.status_code, 403)

    def test_public_token_is_invalid_once_workspace_is_private(self):
        iv, ct = self._launch(self.outsider, self.public_ws, public=True)
        self.public_ws.is_public_workspace = False
        response = self._get(
            "/token_api/get-file-list/%s" % self.public_ws.id, iv, ct)
        self.assertEqual(response.status_code, 401)
        self.assertIn("Relaunch ITOI", response.text)

    def test_private_token_does_not_fall_back_to_public_scope(self):
        iv, ct = self._launch(self.member, self.public_ws)
        self.env["itlingo.project.role"].search([
            ("user_id", "=", self.member.id),
            ("project_id", "=", self.public_ws.id),
        ]).unlink()
        response = self._get(
            "/token_api/get-file-list/%s" % self.public_ws.id, iv, ct)
        self.assertEqual(response.status_code, 401)

    def test_write_token_requires_relaunch_after_demotion(self):
        iv, ct = self._launch(self.member, self.public_ws, write=True)
        self.assertTrue(self._row(iv, ct).launch_write)
        self._file_names(self.public_ws, iv, ct)
        self.env["itlingo.project.role"].search([
            ("user_id", "=", self.member.id),
            ("project_id", "=", self.public_ws.id),
        ]).role = "ws_member"
        response = self._get(
            "/token_api/get-file-list/%s" % self.public_ws.id, iv, ct)
        self.assertEqual(response.status_code, 401)
        self.assertIn("Relaunch ITOI", response.text)

    def test_nonmember_token_for_private_workspace_is_denied(self):
        iv, ct = self._launch(self.outsider, self.private_ws)
        response = self._get(
            "/token_api/get-file-list/%s" % self.private_ws.id, iv, ct)
        self.assertEqual(response.status_code, 401)

    def test_lost_membership_denies_private_workspace(self):
        iv, ct = self._launch(self.member, self.private_ws)
        self.env["itlingo.project.role"].search([
            ("user_id", "=", self.member.id),
            ("project_id", "=", self.private_ws.id),
        ]).unlink()
        response = self._get(
            "/token_api/get-file-list/%s" % self.private_ws.id, iv, ct)
        self.assertEqual(response.status_code, 401)

    def test_workspace_mismatch_is_denied(self):
        iv, ct = self._launch(self.member, self.public_ws)
        response = self._get(
            "/token_api/get-file-list/%s" % self.private_ws.id, iv, ct)
        self.assertEqual(response.status_code, 403)

    # ------------------------------------------------------------------
    # invalid tokens
    # ------------------------------------------------------------------

    def test_untracked_launch_payload_requires_relaunch(self):
        iv, ct = self.settings._aes_encrypt(json.dumps({
            "user": self.member.login,
            "workspace": self.public_ws.name,
            "organization": self.organization.name,
            "write": True,
            "wsid": self.public_ws.id,
        }))
        response = self._get(
            "/token_api/get-file-list/%s" % self.public_ws.id, iv, ct)
        self.assertEqual(response.status_code, 401)
        self.assertIn("Relaunch ITOI", response.text)

    def test_tampered_ciphertext_is_denied(self):
        iv, ct = self._launch(self.member, self.public_ws)
        tampered = ("A" if ct[0] != "A" else "B") + ct[1:]
        response = self._get(
            "/token_api/get-file-list/%s" % self.public_ws.id, iv, tampered)
        self.assertEqual(response.status_code, 401)

    def test_revoked_and_expired_launch_tokens_are_denied(self):
        revoked = self._launch(self.member, self.public_ws)
        self._row(*revoked).action_revoke()
        expired = self._launch(self.member, self.public_ws)
        self._row(*expired).write({
            "expires_at": fields.Datetime.now() - timedelta(minutes=1),
        })
        for iv, ct in (revoked, expired):
            response = self._get(
                "/token_api/get-file-list/%s" % self.public_ws.id, iv, ct)
            self.assertEqual(response.status_code, 401)

    def test_inactive_user_token_is_denied(self):
        iv, ct = self._launch(self.member, self.public_ws)
        self.member.active = False
        response = self._get(
            "/token_api/get-file-list/%s" % self.public_ws.id, iv, ct)
        self.assertEqual(response.status_code, 401)

    # ------------------------------------------------------------------
    # /token_api/validate-launch (called by ITOI before workspace creation
    # and before each token-authorized write)
    # ------------------------------------------------------------------

    def _validate(self, iv, ct):
        return self._get("/token_api/validate-launch", iv, ct)

    def test_validate_launch_returns_payload_and_capabilities(self):
        iv, ct = self._launch(self.member, self.public_ws, write=True)
        response = self._validate(iv, ct)
        self.assertEqual(response.status_code, 200, response.text)
        row = self._row(iv, ct)
        self.assertEqual(json.loads(response.text), {
            "user": self.member.login,
            "workspace": self.public_ws.name,
            "organization": self.organization.name,
            "write": True,
            "wsid": self.public_ws.id,
            "public": False,
            "expires_at": fields.Datetime.to_string(row.expires_at),
        })
        self.assertNotIn(iv, response.text)
        self.assertNotIn(ct, response.text)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIn("Authorization", response.headers["Vary"])

        iv, ct = self._launch(
            self.env.ref("base.public_user"), self.public_ws, public=True)
        body = json.loads(self._validate(iv, ct).text)
        self.assertTrue(body["public"])
        self.assertFalse(body["write"])

    def test_validate_launch_denies_revoked_expired_and_untracked(self):
        revoked = self._launch(self.member, self.public_ws)
        self._row(*revoked).action_revoke()
        expired = self._launch(self.member, self.public_ws)
        self._row(*expired).write({
            "expires_at": fields.Datetime.now() - timedelta(minutes=1),
        })
        untracked = self.settings._aes_encrypt(json.dumps({
            "user": self.member.login,
            "workspace": self.public_ws.name,
            "organization": self.organization.name,
            "write": False,
            "wsid": self.public_ws.id,
        }))
        for iv, ct in (revoked, expired, untracked):
            response = self._validate(iv, ct)
            self.assertEqual(response.status_code, 401, response.text)
            self.assertIn("error", json.loads(response.text))
        response = self.url_open("/token_api/validate-launch")
        self.assertEqual(response.status_code, 401)

    def test_validate_launch_denies_write_token_after_demotion(self):
        iv, ct = self._launch(self.member, self.public_ws, write=True)
        self.assertEqual(self._validate(iv, ct).status_code, 200)
        self.env["itlingo.project.role"].search([
            ("user_id", "=", self.member.id),
            ("project_id", "=", self.public_ws.id),
        ]).role = "ws_member"
        response = self._validate(iv, ct)
        self.assertEqual(response.status_code, 401)
        self.assertIn("Relaunch ITOI", response.text)

    def test_validate_launch_denial_is_not_cacheable(self):
        response = self.url_open("/token_api/validate-launch")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_autovacuum_removes_only_expired_launch_rows(self):
        past = fields.Datetime.now() - timedelta(minutes=1)
        expired_launch = self._row(*self._launch(
            self.env.ref("base.public_user"), self.public_ws, public=True))
        live_launch = self._row(*self._launch(self.member, self.public_ws))
        expired_api = self.Token.with_user(self.member).create({})
        expired_api.action_generate_token()
        (expired_launch | expired_api).write({"expires_at": past})

        self.Token._gc_expired_launch_tokens()

        self.assertFalse(expired_launch.exists())
        self.assertTrue(live_launch.exists())
        self.assertTrue(expired_api.exists())

    def test_validate_launch_denies_api_token(self):
        token = self.Token.with_user(self.member).create({})
        token.action_generate_token()
        response = self._validate(token.token_iv, token.token_ct)
        self.assertEqual(response.status_code, 401)

    # ------------------------------------------------------------------
    # API tokens: ownership, scope and server-controlled fields
    # ------------------------------------------------------------------

    def test_api_token_flow_and_project_scope(self):
        token = self.Token.with_user(self.member).create({
            "project_id": self.private_ws.id,
        })
        token.action_generate_token()
        response = self._get(
            "/api/itlingo/v1/whoami", token.token_iv, token.token_ct)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            set(json.loads(response.text)),
            {"user_id", "user_login", "project_id", "expires_at"},
        )
        response = self._get(
            "/api/itlingo/v1/projects", token.token_iv, token.token_ct)
        self.assertEqual(
            [p["id"] for p in json.loads(response.text)], [self.private_ws.id])

        token.with_user(self.member).action_revoke()
        response = self._get(
            "/api/itlingo/v1/whoami", token.token_iv, token.token_ct)
        self.assertEqual(response.status_code, 401)

    def test_api_token_cannot_be_used_as_launch_token(self):
        token = self.Token.with_user(self.member).create({})
        token.action_generate_token()
        response = self._get(
            "/token_api/get-dsls", token.token_iv, token.token_ct)
        self.assertEqual(response.status_code, 401)

    def test_owner_and_scope_are_enforced_on_create(self):
        Token = self.Token.with_user(self.member)
        with self.assertRaises(AccessError):
            Token.create({"user_id": self.outsider.id})
        with self.assertRaises(AccessError):
            self.Token.with_user(self.outsider).create({
                "project_id": self.private_ws.id,
            })
        with self.assertRaises(AccessError):
            Token.create({"token_ct": "forged", "token_iv": "forged"})
        with self.assertRaises(AccessError):
            Token.create({"token_kind": "launch"})
        # Platform admins manage tokens of every user.
        self.Token.with_user(self.admin).create({"user_id": self.outsider.id})

    def test_context_defaults_cannot_bypass_create_guards(self):
        Token = self.Token.with_user(self.outsider)
        for key, value in (
            ("default_user_id", self.member.id),
            ("default_project_id", self.private_ws.id),
            ("default_token_iv", "forged"),
            ("default_token_ct", "forged"),
            ("default_expires_at", "2999-01-01 00:00:00"),
            ("default_token_kind", "launch"),
            ("default_public_scope", True),
            ("default_launch_write", True),
            ("default_user_id", "not-an-id"),
            ("default_project_id", ["not", "an", "id"]),
        ):
            with self.assertRaises(AccessError, msg=key):
                Token.with_context(**{key: value}).create({})
        # Explicit own values still win over a hostile context default.
        token = Token.with_context(default_user_id=self.member.id).create({
            "user_id": self.outsider.id,
        })
        self.assertEqual(token.user_id, self.outsider)
        # Normal field defaults are preserved.
        token = self.Token.with_user(self.member).create({})
        self.assertEqual(token.user_id, self.member)
        self.assertEqual(token.token_kind, "api")
        self.assertFalse(token.public_scope)
        self.assertFalse(token.launch_write)
        self.assertFalse(token.token_ct)

    def test_server_fields_and_reactivation_are_protected(self):
        token = self.Token.with_user(self.member).create({})
        token.action_generate_token()
        for vals in (
            {"expires_at": fields.Datetime.now() + timedelta(days=365)},
            {"token_ct": "forged"},
            {"user_id": self.outsider.id},
            {"project_id": self.private_ws.id},
        ):
            with self.assertRaises(AccessError):
                token.write(vals)
        token.action_revoke()
        with self.assertRaises(AccessError):
            token.write({"is_active": True})
        with self.assertRaises(UserError):
            token.action_generate_token()
        self.assertFalse(token.is_active)

    def test_other_user_cannot_revoke_but_admin_can(self):
        token = self.Token.with_user(self.member).create({})
        token.action_generate_token()
        with self.assertRaises(AccessError):
            token.with_user(self.outsider).action_revoke()
        token.with_user(self.admin).action_revoke()
        self.assertFalse(token.is_active)
