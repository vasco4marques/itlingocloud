import unittest

from odoo.addons.itlingo_templating.services.rendering import (
    render_filename,
    template_format,
)
from odoo.addons.itlingo_templating.services.text_renderer import render_text


class TestTextRenderer(unittest.TestCase):

    def test_renders_utf8_jinja_template(self):
        output = render_text(
            "# {{ project.name }}\n{{ missing.value }}\n".encode("utf-8"),
            {"project": {"name": "Caf\u00e9"}},
        )

        self.assertEqual(output.decode("utf-8"), "# Caf\u00e9\n\n")

    def test_rejects_non_utf8_template_bytes(self):
        with self.assertRaises(UnicodeDecodeError):
            render_text(b"\xff\xfe", {})

    def test_missing_values_render_as_json_null_with_tojson(self):
        output = render_text(
            b'{"known": {{ known | tojson }}, '
            b'"missing": {{ missing.value | tojson }}}',
            {"known": "value"},
        )

        self.assertEqual(
            output.decode("utf-8"),
            '{"known": "value", "missing": null}',
        )
    def test_accepts_any_utf8_text_extension(self):
        self.assertEqual(template_format("model.py", b"class Model:\n    pass\n"), "py")
        self.assertEqual(template_format("main.go", b"package main\n"), "go")

    def test_rejects_binary_or_extensionless_templates(self):
        self.assertIsNone(template_format("payload.bin", b"\xff\xfe"))
        self.assertIsNone(template_format("payload.bin", b"text\x00data"))
        self.assertIsNone(template_format("README", b"UTF-8 text"))

    def test_accepts_office_formats_for_specialized_renderers(self):
        self.assertEqual(template_format("report.docx", b"PK\x03\x04"), "docx")
        self.assertEqual(template_format("report.xlsx", b"PK\x03\x04"), "xlsx")


    def test_filename_replaces_existing_extension(self):
        self.assertEqual(
            render_filename("output.custom", {}, "generated", ".py"),
            "output.py",
        )
