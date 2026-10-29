import base64
import hashlib
import json

from odoo.tests import HttpCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestGetDsls(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source_user = new_test_user(
            cls.env,
            login='itoi_document_source_user',
            password='itoi_document_source_user',
            groups='base.group_portal',
        )
        cls.File = cls.env["itlingo.dsl.file"]
        cls.dsl = cls.env["itlingo.dsl"].create({
            "name": "ITOI multi-file grammar",
            "acronym": "ITOIMF",
            "version": "test-1",
            "status": "draft",
            "file_extensions": ".imf",
        })
        cls.dsl_alt = cls.env["itlingo.dsl"].create({
            "name": "ITOI multi-file grammar",
            "acronym": "ITOIMF",
            "version": "test-2",
            "status": "draft",
            "family_id": cls.dsl.family_id.id,
            "file_extensions": ".imf",
        })
        cls.File._create_grammar_text(
            cls.dsl,
            "Main.langium",
            "grammar ITOIMF\n"
            "import './shared/Terminals'\n"
            "entry Model: 'model' name=ID;\n",
            is_entry=True,
        )
        cls.File._create_grammar_text(
            cls.dsl,
            "shared/Terminals.langium",
            "hidden terminal WS: /\\s+/;\n"
            "terminal ID: /[_a-zA-Z][\\w_]*/;\n",
            is_entry=False,
        )
        cls.services_compiled = "export default function () { return {}; }\n"
        cls.services_digest = hashlib.sha256(
            cls.services_compiled.encode("utf-8")
        ).hexdigest()
        cls.dsl.write({
            "services_compiled": cls.services_compiled,
            "services_compiled_digest": cls.services_digest,
        })
        cls.plain_dsl = cls.env["itlingo.dsl"].create({
            "name": "ITOI grammar without custom services",
            "acronym": "ITOINOSERVICES",
            "version": "test-1",
            "status": "draft",
            "file_extensions": ".ins",
        })
        cls.File._create_grammar_text(
            cls.plain_dsl,
            "Main.langium",
            "grammar ITOINOSERVICES\nentry Model: 'model';\n",
            is_entry=True,
        )
        cls.broken_dsl = cls.env["itlingo.dsl"].create({
            "name": "ITOI broken grammar",
            "acronym": "ITOIBROKEN",
            "version": "test-1",
            "status": "draft",
        })
        cls.File._create_grammar_text(
            cls.broken_dsl,
            "Main.langium",
            "grammar ITOIBROKEN\nimport './Missing'\nentry Model: 'model';\n",
            is_entry=True,
        )
        cls.settings = (
            cls.env["itlingo.integration.settings"].sudo()._get_settings()
        )
        cls.settings.write({"encryption_key": "test-key-for-itoi-boundary-00001"})
        cls.organization = cls.env["itlingo.organization"].create({
            "name": "ITOI DSL source test organization",
        })
        cls.workspace = cls.env["itlingo.workspace"].create({
            "name": "ITOI DSL source test workspace",
            "organization_id": cls.organization.id,
        })
        cls.env["itlingo.project.role"].create({
            "user_id": cls.source_user.id,
            "project_id": cls.workspace.id,
            "role": "doc_manager",
            "state": "accepted",
        })
        doc_type = cls.env.ref("itlingo_core.doc_type_specification")
        cls.workspace_source = cls.env["itlingo.document"].create({
            "name": "Billing ASL",
            "document_type_id": doc_type.id,
            "project_id": cls.workspace.id,
            "dsl_family_id": cls.dsl.family_id.id,
            "dsl_version_id": cls.dsl.id,
            "file_name": "billing.imf",
            "document_file": base64.b64encode(
                b"Package p_Billing System Billing"
            ),
        })
        cls.organization_source = cls.env["itlingo.document"].create({
            "name": "Shared ASL",
            "document_type_id": doc_type.id,
            "organization_id": cls.organization.id,
            "dsl_family_id": cls.dsl.family_id.id,
            "dsl_version_id": cls.dsl.id,
            "file_name": "shared.imf",
            "document_file": base64.b64encode(
                b"Package p_Shared System Shared"
            ),
        })
        cls.organization_source_alt_version = cls.env["itlingo.document"].create({
            "name": "Shared ASL alternate version",
            "document_type_id": doc_type.id,
            "organization_id": cls.organization.id,
            "dsl_family_id": cls.dsl.family_id.id,
            "dsl_version_id": cls.dsl_alt.id,
            "file_name": "shared-alt.imf",
            "document_file": base64.b64encode(
                b"Package p_SharedAlt System SharedAlt"
            ),
        })
        foreign_org = cls.env["itlingo.organization"].create({
            "name": "Foreign DSL source organization",
        })
        cls.foreign_source = cls.env["itlingo.document"].create({
            "name": "Foreign ASL",
            "document_type_id": doc_type.id,
            "organization_id": foreign_org.id,
            "dsl_family_id": cls.dsl.family_id.id,
            "dsl_version_id": cls.dsl.id,
            "file_name": "foreign.imf",
            "document_file": base64.b64encode(
                b"Package p_Foreign System Foreign"
            ),
        })
        cls.env["itlingo.organization.role"].create({
            "user_id": cls.source_user.id,
            "organization_id": cls.organization.id,
            "role": "doc_manager",
            "state": "accepted",
        })
        # Drafts are visible in ITOI only to their family maintainers.
        for dsl in (cls.dsl, cls.plain_dsl, cls.broken_dsl):
            dsl.family_id.maintainer_ids = [(4, cls.source_user.id)]

    def _authorization_headers(self, user=None, workspace=None, public=False):
        iv, ciphertext = self.env[
            "itlingo.integration.token"
        ]._issue_launch_token(
            user or self.source_user, workspace or self.workspace, False,
            public=public,
        )
        return {"Authorization": "Bearer %s:%s" % (iv, ciphertext)}

    def test_get_dsls_emits_flattened_grammar_and_matching_digest(self):
        response = self.url_open(
            "/token_api/get-dsls", headers=self._authorization_headers(),
        )

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.text)
        result = next(
            item for item in payload["dsls"] if item["acronym"] == "ITOIMF"
        )
        expected = self.dsl._flattened_grammar_text()
        self.assertEqual(result["grammar"], expected)
        self.assertNotIn("import './shared/Terminals'", result["grammar"])
        self.assertIn("terminal ID", result["grammar"])
        self.assertEqual(
            result["digest"], hashlib.sha256(expected.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(result["services"], self.services_compiled)
        self.assertEqual(result["services_digest"], self.services_digest)
        self.assertEqual(result["id"], self.dsl.id)

        plain_result = next(
            item
            for item in payload["dsls"]
            if item["acronym"] == "ITOINOSERVICES"
        )
        self.assertEqual(plain_result["services"], "")
        self.assertEqual(plain_result["services_digest"], "")
        self.assertNotIn(
            "ITOIBROKEN", {item["acronym"] for item in payload["dsls"]},
        )

    def test_get_dsls_omits_deprecated_version_when_family_is_current(self):
        active = self.env["itlingo.dsl"].create({
            "name": "ITOI current fallback family",
            "acronym": "ITOICURRENT",
            "version": "test-1",
            "status": "active",
        })
        deprecated = self.env["itlingo.dsl"].create({
            "family_id": active.family_id.id,
            "version": "test-0",
            "status": "draft",
        })
        self.File._create_grammar_text(
            deprecated,
            "Main.langium",
            "grammar ITOICURRENT\nentry Model: 'model';\n",
            is_entry=True,
        )
        deprecated.with_context(
            allow_dsl_lifecycle_write=True,
        ).write({"status": "deprecated"})

        response = self.url_open(
            "/token_api/get-dsls", headers=self._authorization_headers(),
        )

        self.assertEqual(response.status_code, 200)
        ids = {item["id"] for item in json.loads(response.text)["dsls"]}
        self.assertNotIn(deprecated.id, ids)

    def test_get_dsls_includes_deprecated_only_family(self):
        deprecated = self.env["itlingo.dsl"].create({
            "name": "ITOI deprecated fallback family",
            "acronym": "ITOIDEPFALLBACK",
            "version": "test-1",
            "status": "draft",
            "file_extensions": ".idf",
        })
        self.File._create_grammar_text(
            deprecated,
            "Main.langium",
            "grammar ITOIDEPFALLBACK\nentry Model: 'model';\n",
            is_entry=True,
        )
        deprecated.with_context(
            allow_dsl_lifecycle_write=True,
        ).write({"status": "deprecated"})

        response = self.url_open(
            "/token_api/get-dsls", headers=self._authorization_headers(),
        )

        self.assertEqual(response.status_code, 200)
        result = next(
            item
            for item in json.loads(response.text)["dsls"]
            if item["id"] == deprecated.id
        )
        self.assertEqual(result["status"], "deprecated")


    def test_get_dsl_sources_is_limited_to_launch_workspace_and_organization(self):
        response = self.url_open(
            "/token_api/get-dsl-sources/%s" % self.dsl.id,
            headers=self._authorization_headers(),
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = json.loads(response.text)
        source_ids = {item["id"] for item in payload["sources"]}
        self.assertEqual(source_ids, {
            self.workspace_source.id,
            self.organization_source.id,
            self.organization_source_alt_version.id,
        })
        self.assertNotIn(self.foreign_source.id, source_ids)
        billing = next(
            item for item in payload["sources"]
            if item["id"] == self.workspace_source.id
        )
        self.assertEqual(
            billing["content"], "Package p_Billing System Billing",
        )
        self.assertEqual(billing["packages"], ["p_Billing"])
        self.assertEqual(payload["conflicting_packages"], [])

    def test_get_dsl_sources_accepts_deprecated_version(self):
        deprecated = self.env["itlingo.dsl"].create({
            "name": "ITOI deprecated source language",
            "acronym": "ITOIDEPSOURCE",
            "version": "test-1",
            "status": "deprecated",
        })
        response = self.url_open(
            "/token_api/get-dsl-sources/%s" % deprecated.id,
            headers=self._authorization_headers(),
        )

        self.assertEqual(response.status_code, 200, response.text)

    def _visible_dsl_ids(self, user, workspace, public=False):
        response = self.url_open(
            "/token_api/get-dsls",
            headers=self._authorization_headers(user, workspace, public),
        )
        self.assertEqual(response.status_code, 200, response.text)
        return {item["id"] for item in json.loads(response.text)["dsls"]}

    def test_get_dsls_hides_drafts_from_non_maintainers(self):
        published = self.env["itlingo.dsl"].create({
            "name": "ITOI published grammar",
            "acronym": "ITOIPUBLISHED",
            "version": "test-1",
            "status": "draft",
            "file_extensions": ".ipub",
        })
        self.File._create_grammar_text(
            published,
            "Main.langium",
            "grammar ITOIPUBLISHED\n"
            "entry Model: 'model' name=ID;\n"
            "hidden terminal WS: /\\s+/;\n"
            "terminal ID: /[_a-zA-Z][\\w_]*/;\n",
            is_entry=True,
        )
        published.action_publish()
        public_workspace = self.env["itlingo.workspace"].create({
            "name": "ITOI public DSL workspace",
            "is_public_workspace": True,
        })
        non_maintainer = new_test_user(
            self.env, login="itoi_dsl_non_maintainer",
            groups="base.group_portal",
        )
        self.env["itlingo.project.role"].create({
            "user_id": non_maintainer.id,
            "project_id": public_workspace.id,
            "role": "ws_manager",
            "state": "accepted",
        })
        drafts = {self.dsl.id, self.dsl_alt.id, self.plain_dsl.id}

        for user, public in (
                (non_maintainer, False),
                (self.env.ref("base.public_user"), True)):
            visible = self._visible_dsl_ids(user, public_workspace, public)
            self.assertIn(published.id, visible)
            self.assertFalse(visible & drafts)

        visible = self._visible_dsl_ids(self.source_user, self.workspace)
        self.assertIn(published.id, visible)
        self.assertTrue({self.dsl.id, self.plain_dsl.id} <= visible)
