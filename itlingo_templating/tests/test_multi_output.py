import io
import unittest
import zipfile

from odoo.addons.itlingo_templating.services.multi_output import (
    MultiOutputTemplateError,
    build_zip,
    render_outputs,
    validate_output_template,
)


BUNDLE = (
    "{# output: {{ spec_name }}_model.py #}\n"
    "class {{ root.name }}:\n"
    "    pass\n"
    "{# endoutput #}\n"
    "\n"
    "  {# output: {{ spec_name }}_schema.sql #}  \n"
    "CREATE TABLE {{ root.name }} (id INTEGER PRIMARY KEY);\n"
    "{# endoutput #}\n"
).encode("utf-8")

CONTEXT = {"spec_name": "shop", "root": {"name": "Order"}}


class TestMultiOutput(unittest.TestCase):

    def test_marker_free_template_returns_none(self):
        self.assertIsNone(
            render_outputs(b"# {{ spec_name }}\nplain text\n", CONTEXT)
        )

    def test_renders_mixed_extensions_in_source_order(self):
        outputs = render_outputs(BUNDLE, CONTEXT)

        self.assertEqual(
            [name for name, _ in outputs],
            ["shop_model.py", "shop_schema.sql"],
        )
        self.assertEqual(
            outputs[0][1].decode("utf-8"), "class Order:\n    pass\n"
        )
        self.assertEqual(
            outputs[1][1].decode("utf-8"),
            "CREATE TABLE Order (id INTEGER PRIMARY KEY);\n",
        )

    def test_preserves_crlf_body_line_endings(self):
        outputs = render_outputs(
            b"{# output: a.py #}\r\n"
            b"first\r\n"
            b"second {{ value }}\r\n"
            b"{# endoutput #}\r\n",
            {"value": "line"},
        )

        self.assertEqual(outputs, [("a.py", b"first\r\nsecond line\r\n")])

    def test_single_block_is_still_bundle_mode(self):
        outputs = render_outputs(
            b"{# output: a.py #}\nx = 1\n{# endoutput #}\n", {}
        )

        self.assertEqual(outputs, [("a.py", b"x = 1\n")])

    def test_empty_body_is_valid(self):
        outputs = render_outputs(
            b"{# output: empty.txt #}\n{# endoutput #}\n", {}
        )

        self.assertEqual(outputs, [("empty.txt", b"")])

    def test_non_standalone_marker_is_ordinary_content(self):
        outputs = render_outputs(
            b"{# output: doc.md #}\n"
            b"literal {# output: nested.py #} inline\n"
            b"{# endoutput #}\n",
            {},
        )

        self.assertEqual(
            outputs, [("doc.md", b"literal  inline\n")]
        )

    def test_rejects_content_outside_blocks(self):
        with self.assertRaises(MultiOutputTemplateError):
            render_outputs(
                b"stray\n{# output: a.py #}\nx\n{# endoutput #}\n", {}
            )

    def test_rejects_unclosed_and_nested_and_stray_fences(self):
        for source in (
            b"{# output: a.py #}\nx\n",
            b"{# output: a.py #}\n{# output: b.py #}\nx\n{# endoutput #}\n",
            b"{# endoutput #}\n",
        ):
            with self.assertRaises(MultiOutputTemplateError):
                render_outputs(source, {})

    def test_rejects_malformed_standalone_fence_candidates(self):
        for source in (
            b"{# output a.py #}\nbody\n",
            b"{# endoutput extra #}\n",
        ):
            with self.subTest(source=source):
                with self.assertRaises(MultiOutputTemplateError):
                    render_outputs(source, {})

    def test_rejects_unsafe_or_empty_rendered_names(self):
        for name in (
            "{{ missing }}",
            "..",
            "sub/dir.py",
            "back\\slash.py",
            "c:name.py",
            "star*.py",
            "trailing.",
            "bad\x01.py",
            "x" * 256 + ".py",
        ):
            source = (
                "{# output: %s #}\nbody\n{# endoutput #}\n" % name
            ).encode("utf-8")
            with self.subTest(name=name):
                with self.assertRaises(MultiOutputTemplateError):
                    render_outputs(source, {})

    def test_rejects_rendered_name_with_trailing_space(self):
        with self.assertRaises(MultiOutputTemplateError):
            render_outputs(
                b"{# output: {{ bad }} #}\nbody\n{# endoutput #}\n",
                {"bad": "trailing.py "},
            )

    def test_rejects_rendered_unicode_control_name(self):
        with self.assertRaises(MultiOutputTemplateError):
            render_outputs(
                b"{# output: {{ bad }} #}\nbody\n{# endoutput #}\n",
                {"bad": "bad\x85.py"},
            )

    def test_rejects_case_insensitive_duplicate_names(self):
        with self.assertRaises(MultiOutputTemplateError):
            render_outputs(
                b"{# output: Model.py #}\na\n{# endoutput #}\n"
                b"{# output: model.PY #}\nb\n{# endoutput #}\n",
                {},
            )

    def test_build_zip_contains_ordered_entries(self):
        outputs = render_outputs(BUNDLE, CONTEXT)
        data = build_zip(outputs)

        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(
                archive.namelist(), ["shop_model.py", "shop_schema.sql"]
            )
            self.assertEqual(
                archive.read("shop_schema.sql"), outputs[1][1]
            )

    def test_rejects_non_utf8_bytes(self):
        with self.assertRaises(UnicodeDecodeError):
            render_outputs(b"\xff\xfe", {})

    def test_validate_output_template_marker_free_returns_none(self):
        self.assertIsNone(
            validate_output_template(b"# {{ spec_name }}\nplain text\n")
        )

    def test_validate_output_template_returns_raw_headers_in_order(self):
        self.assertEqual(
            validate_output_template(BUNDLE),
            ["{{ spec_name }}_model.py", "{{ spec_name }}_schema.sql"],
        )

    def test_validate_output_template_rejects_malformed_structure(self):
        for source in (
            b"{# output: a.py #}\nx\n",
            b"{# endoutput #}\n",
            b"{# output: a.py #}\nx\n{# endoutput #}\nstray\n",
            b"{# output a.py #}\nx\n{# endoutput #}\n",
        ):
            with self.assertRaises(MultiOutputTemplateError):
                validate_output_template(source)

    def test_validate_output_template_rejects_unsafe_literal_names(self):
        for source in (
            b"{# output: sub/dir.py #}\n{# endoutput #}\n",
            b"{# output: a.py #}\n{# endoutput #}\n"
            b"{# output: A.PY #}\n{# endoutput #}\n",
        ):
            with self.assertRaises(MultiOutputTemplateError) as caught:
                validate_output_template(source)
            self.assertIn("filename", str(caught.exception))

    def test_validate_output_template_defers_dynamic_names(self):
        # Same literal tail behind different variables is not a duplicate, and
        # dynamic parts may still render into anything: generation decides.
        self.assertEqual(
            validate_output_template(
                b"{# output: {{ spec_name }}_a.py #}\n{# endoutput #}\n"
                b"{# output: {{ template_name }}_a.py #}\n{# endoutput #}\n"
            ),
            ["{{ spec_name }}_a.py", "{{ template_name }}_a.py"],
        )

    def test_validate_output_template_rejects_empty_literal_header(self):
        # Advisory checking must not accept what generation rejects.
        for source in (
            b"{# output: #}\n{# endoutput #}\n",
            b"{# output:   #}\n{# endoutput #}\n",
        ):
            with self.assertRaises(MultiOutputTemplateError) as caught:
                validate_output_template(source)
            self.assertIn("filename", str(caught.exception))
            with self.assertRaises(MultiOutputTemplateError):
                render_outputs(source, CONTEXT)

    def test_validate_output_template_rejects_non_utf8_bytes(self):
        with self.assertRaises(UnicodeDecodeError):
            validate_output_template(b"\xff\xfe")
