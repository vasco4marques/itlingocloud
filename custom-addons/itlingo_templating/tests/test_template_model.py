import base64

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestUnifiedTemplateModel(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template_type = cls.env.ref(
            "itlingo_core.doc_type_template"
        )
        cls.family = cls.env["itlingo.dsl.family"].create({
            "name": "Unified Template Test DSL",
            "acronym": "UTT",
        })
        cls.dsl = cls.env["itlingo.dsl"].create({
            "family_id": cls.family.id,
            "name": "Unified Template Test DSL",
            "acronym": "UTT",
            "version": "test-1",
            "status": "draft",
            "file_extensions": ".utt",
        })

    def test_template_type_uses_unified_code(self):
        self.assertEqual(self.template_type.name, "Template")
        self.assertEqual(self.template_type.type_code, "template")

    def test_template_requires_a_dsl_family(self):
        with self.assertRaisesRegex(ValidationError, "DSL family"):
            self.env["itlingo.document"].create({
                "name": "Missing DSL",
                "document_type_id": self.template_type.id,
            })

    def test_template_rejects_binary_file_with_arbitrary_extension(self):
        with self.assertRaisesRegex(ValidationError, "UTF-8 text files"):
            self.env["itlingo.document"].create({
                "name": "Unsupported Template",
                "document_type_id": self.template_type.id,
                "dsl_family_id": self.family.id,
                "dsl_version_id": self.dsl.id,
                "file_name": "template.custom",
                "document_file": base64.b64encode(b"\xff\xfe\x00"),
            })

    def test_template_accepts_any_utf8_text_extension(self):
        document = self.env["itlingo.document"].create({
            "name": "Python Template",
            "document_type_id": self.template_type.id,
            "dsl_family_id": self.family.id,
            "dsl_version_id": self.dsl.id,
            "file_name": "template.py",
            "document_file": base64.b64encode(b"# {{ specification.name }}"),
        })

        self.assertTrue(document.is_template)
        self.assertTrue(document.template_format_supported)
