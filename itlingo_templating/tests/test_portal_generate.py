import base64
import io
import json
import re
import zipfile

from odoo.tests import HttpCase, tagged
from odoo.tests.common import new_test_user

from odoo.addons.itlingo_templating.controllers.portal_generate import (
    ItlingoTemplatingPortal,
)
from odoo.addons.itlingo_templating.services.text_renderer import render_text


SOURCE_GRAMMAR = r"""
grammar TemplateSource
entry Specification:
    'specification' name=ID requirements+=Requirement*;
Requirement:
    'requirement' name=ID;
hidden terminal WS: /\s+/;
terminal ID: /[a-zA-Z_][a-zA-Z0-9_]*/;
"""


@tagged("post_install", "-at_install")
class TestPortalGenerate(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.portal_user = new_test_user(
            cls.env,
            login="template_portal",
            groups="base.group_portal",
        )
        cls.organization = cls.env["itlingo.organization"].create({
            "name": "Template Portal Test",
        })
        cls.env["itlingo.organization.role"].create({
            "user_id": cls.portal_user.id,
            "organization_id": cls.organization.id,
            "role": "org_manager",
            "state": "accepted",
        })
        cls.dsl = cls.env["itlingo.dsl"].create({
            "name": "Template Source Language",
            "acronym": "TSL",
            "version": "test-1.0",
            "status": "draft",
            "file_extensions": ".tsl",
            "template_profile": json.dumps({
                "bucket_aliases": {"Requirement": "requirements"},
            }),
        })
        cls.env["itlingo.dsl.file"]._create_grammar_text(
            cls.dsl, "TSL.langium", SOURCE_GRAMMAR,
        )
        cls.dsl.action_publish()
        cls.document = cls.env["itlingo.document"].create({
            "name": "Requirements report",
            "organization_id": cls.organization.id,
            "document_type_id": cls.env.ref(
                "itlingo_documents.doc_type_template"
            ).id,
            "dsl_id": cls.dsl.id,
            "document_file": base64.b64encode(b"{{ root.name }}"),
            "file_name": "requirements.py",
            "status": "published",
            "creator_id": cls.portal_user.id,
        })
        cls.detail_url = (
            f"/my/organizations/{cls.organization.id}/documents/{cls.document.id}"
        )
        cls.workspace = cls.env["itlingo.workspace"].create({
            "name": "Template Workspace Test",
            "organization_id": cls.organization.id,
        })
        cls.env["itlingo.project.role"].create({
            "user_id": cls.portal_user.id,
            "project_id": cls.workspace.id,
            "role": "ws_manager",
            "state": "accepted",
        })
        cls.workspace_document = cls.env["itlingo.document"].create({
            "name": "Workspace report",
            "project_id": cls.workspace.id,
            "document_type_id": cls.env.ref(
                "itlingo_documents.doc_type_template"
            ).id,
            "dsl_id": cls.dsl.id,
            "document_file": base64.b64encode(b"{{ specification.name }}"),
            "file_name": "workspace-report.txt",
            "status": "published",
            "creator_id": cls.portal_user.id,
        })
        cls.workspace_detail_url = (
            f"/my/workspaces/{cls.workspace.id}/documents/"
            f"{cls.workspace_document.id}"
        )

    def setUp(self):
        super().setUp()
        self.authenticate("template_portal", "template_portal")

    def test_template_detail_embeds_generation_form(self):
        response = self.url_open(self.detail_url)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Generate a document", response.text)
        self.assertIn("Generate and download", response.text)
        self.assertIn("Template information", response.text)
        self.assertIn("Check template", response.text)
        self.assertIn(".tsl", response.text)
        self.assertIn(
            f"/dsl/{self.document.dsl_id.id}/template-reference",
            response.text,
        )

    def test_bundle_guidance_hidden_only_for_office_attachments(self):
        guidance = "Producing several files from one text template"
        for file_name, expected in (
            ("report.docx", False),
            ("report.xlsx", False),
            ("REPORT.DOCX", False),
            ("REPORT.XLSX", False),
            ("relatório.txt", True),
            ("requirements.py", True),
        ):
            self.document.file_name = file_name
            self.env.flush_all()
            response = self.url_open(self.detail_url)

            self.assertEqual(response.status_code, 200, file_name)
            self.assertEqual(guidance in response.text, expected, file_name)

    def test_generation_error_stays_in_document_detail(self):
        detail_response = self.url_open(self.detail_url)
        csrf_token = re.search(
            r'name="csrf_token" value="([^"]+)"', detail_response.text,
        ).group(1)

        response = self.url_open(
            self.detail_url + "/generate",
            data={"csrf_token": csrf_token},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Please upload a TSL specification file.", response.text)
        self.assertIn("Template information", response.text)
        self.assertIn("Documents", response.text)

    def test_generates_arbitrary_utf8_extension(self):
        detail_response = self.url_open(self.detail_url)
        csrf_token = re.search(
            r'name="csrf_token" value="([^"]+)"', detail_response.text,
        ).group(1)

        response = self.url_open(
            self.detail_url + "/generate",
            data={"csrf_token": csrf_token},
            files={
                "source_file": (
                    "demo.tsl",
                    b"specification demo requirement first",
                    "text/plain",
                ),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"demo")
        self.assertEqual(
            response.headers["Content-Type"], "text/x-python; charset=utf-8",
        )
        self.assertIn(".py", response.headers["Content-Disposition"])

    def test_legacy_generate_get_redirects_to_detail(self):
        response = self.url_open(
            self.detail_url + "/generate", allow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["Location"], self.detail_url + "#generate")

    def test_workspace_generation_error_uses_workspace_detail(self):
        detail_response = self.url_open(self.workspace_detail_url)
        csrf_token = re.search(
            r'name="csrf_token" value="([^"]+)"', detail_response.text,
        ).group(1)

        response = self.url_open(
            self.workspace_detail_url + "/generate",
            data={"csrf_token": csrf_token},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Please upload a TSL specification file.", response.text)
        self.assertIn("Template Workspace Test", response.text)
        self.assertIn("Workspace report", response.text)

    def test_template_check_renders_advisory_findings_without_spec(self):
        self.document.document_file = base64.b64encode(
            b"{% for requirement in requirements %}"
            b"{{ requirement.titel|lenght }}{% endfor %}"
        )
        detail_response = self.url_open(self.detail_url)
        csrf_token = re.search(
            r'name="csrf_token" value="([^"]+)"', detail_response.text,
        ).group(1)

        response = self.url_open(
            self.detail_url + "/check", data={"csrf_token": csrf_token},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Advisory template finding", response.text)
        self.assertIn("titel", response.text)
        self.assertIn("title", response.text)
        self.assertIn("Unknown Jinja filter `lenght`", response.text)
        self.assertLess(
            response.text.index('data-category="filter"'),
            response.text.index('data-category="dsl"'),
        )
        self.assertIn("Generate and download", response.text)

    def test_record_profile_alias_and_acronym_render_in_context(self):
        context = ItlingoTemplatingPortal._build_context(self.dsl, {
            "$type": "Specification",
            "name": "demo",
            "requirements": [{"$type": "Requirement", "name": "first"}],
        })

        output = render_text(
            b"{{ dsl }}:{% for item in requirements %}{{ item.id }}{% endfor %}",
            context,
        )

        self.assertEqual(output, b"TSL:first")

    def _post_generate(self, source=b"specification demo requirement first"):
        csrf_token = re.search(
            r'name="csrf_token" value="([^"]+)"',
            self.url_open(self.detail_url).text,
        ).group(1)
        return self.url_open(
            self.detail_url + "/generate",
            data={"csrf_token": csrf_token},
            files={"source_file": ("demo.tsl", source, "text/plain")},
        )

    def test_bundle_template_downloads_named_zip_with_mixed_members(self):
        self.document.document_file = base64.b64encode(
            b"{# output: {{ spec_name }}_model.py #}\n"
            b"class {{ root.name }}:\n"
            b"    pass\n"
            b"{# endoutput #}\n"
            b"{# output: {{ root.name }}_schema.sql #}\n"
            b"CREATE TABLE {{ root.name }} (id INTEGER PRIMARY KEY);\n"
            b"{# endoutput #}\n"
        )
        self.document.output_filename_pattern = (
            "{{ spec_name }}_{{ template_name }}"
        )

        response = self._post_generate()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "application/zip")
        self.assertIn(
            "demo_requirements.zip", response.headers["Content-Disposition"],
        )
        self.assertEqual(
            int(response.headers["Content-Length"]), len(response.content),
        )
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertEqual(
                archive.namelist(), ["demo_model.py", "demo_schema.sql"],
            )
            self.assertEqual(
                archive.read("demo_model.py"), b"class demo:\n    pass\n",
            )
            self.assertEqual(
                archive.read("demo_schema.sql"),
                b"CREATE TABLE demo (id INTEGER PRIMARY KEY);\n",
            )

    def test_bundle_failure_returns_detail_error_not_partial_zip(self):
        self.document.document_file = base64.b64encode(
            b"{# output: a.py #}\nx\n{# endoutput #}\n"
            b"{# output: A.PY #}\ny\n{# endoutput #}\n"
        )

        response = self._post_generate()

        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(
            response.headers["Content-Type"], "application/zip",
        )
        self.assertIn("Document generation failed", response.text)
