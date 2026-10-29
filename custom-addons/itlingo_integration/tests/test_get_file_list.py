import base64
import json

from odoo.tests import HttpCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestGetFileList(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source_user = new_test_user(
            cls.env,
            login="itoi_file_list_user",
            password="itoi_file_list_user",
            groups="base.group_user",
        )
        cls.settings = (
            cls.env["itlingo.integration.settings"].sudo()._get_settings()
        )
        cls.settings.write({
            "encryption_key": "test-key-for-itoi-boundary-00001",
            "importable_extensions": "txt,md,json,xml,yaml,yml,csv,properties,rsl",
        })
        cls.organization = cls.env["itlingo.organization"].create({
            "name": "ITOI file-list test organization",
        })
        cls.workspace = cls.env["itlingo.workspace"].create({
            "name": "ITOI file-list test workspace",
            "organization_id": cls.organization.id,
        })
        cls.env["itlingo.project.role"].create({
            "user_id": cls.source_user.id,
            "project_id": cls.workspace.id,
            "role": "ws_member",
            "state": "accepted",
        })
        doc_type = cls.env.ref("itlingo_documents.doc_type_specification")
        cls.workspace_document = cls.env["itlingo.document"].create({
            "name": "Workspace specification display title",
            "document_type_id": doc_type.id,
            "project_id": cls.workspace.id,
            "file_name": "ws-spec.rsl",
            "document_file": base64.b64encode(b"workspace specification"),
        })
        cls.organization_document = cls.env["itlingo.document"].create({
            "name": "Organization glossary display title",
            "document_type_id": doc_type.id,
            "organization_id": cls.organization.id,
            "file_name": "org-glossary.rsl",
            "document_file": base64.b64encode(b"organization glossary"),
        })

    def _authorization_headers(self):
        iv, ciphertext = self.settings._aes_encrypt(json.dumps({
            "user": self.source_user.login,
            "wsid": self.workspace.id,
        }))
        return {"Authorization": "Bearer %s:%s" % (iv, ciphertext)}

    def test_get_file_list_includes_titles_and_scopes(self):
        response = self.url_open(
            "/token_api/get-file-list/%s" % self.workspace.id,
            headers=self._authorization_headers(),
        )

        self.assertEqual(response.status_code, 200, response.text)
        namelist = {
            item["name"]: item for item in json.loads(response.text)["namelist"]
        }
        workspace_item = namelist["ws-spec.rsl"]
        self.assertEqual(workspace_item["name"], "ws-spec.rsl")
        self.assertEqual(workspace_item["type"], "rsl")
        self.assertEqual(
            workspace_item["title"], "Workspace specification display title",
        )
        self.assertEqual(workspace_item["scope"], "workspace")

        organization_item = namelist["org-glossary.rsl"]
        self.assertEqual(organization_item["name"], "org-glossary.rsl")
        self.assertEqual(organization_item["type"], "rsl")
        self.assertEqual(
            organization_item["title"], "Organization glossary display title",
        )
        self.assertEqual(organization_item["scope"], "organization")
