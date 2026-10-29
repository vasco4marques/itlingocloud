from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestImportableExtensions(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.settings = cls.env["itlingo.integration.settings"]._get_settings()
        cls.settings.importable_extensions = "txt,md"

    def _new_dsl(self, acronym, file_extensions, status="active", version="test-1"):
        return self.env["itlingo.dsl"].create({
            "name": "DSL %s" % acronym,
            "acronym": acronym,
            "version": version,
            "status": status,
            "file_extensions": file_extensions,
        })

    def test_active_dsl_extensions_are_importable_without_configuration(self):
        self._new_dsl("VSL", ".vsl", status="active")
        allowed = self.settings._get_importable_extensions()
        self.assertIn("vsl", allowed)

    def test_draft_dsl_extensions_are_importable_as_draft_variant(self):
        self._new_dsl("VSL", ".vsl", status="draft")
        allowed = self.settings._get_importable_extensions()
        self.assertIn("vsl-draft", allowed)
        # The plain extension is NOT importable for a draft-only DSL.
        self.assertNotIn("vsl", allowed)

    def test_configured_extras_are_kept(self):
        allowed = self.settings._get_importable_extensions()
        self.assertIn("txt", allowed)
        self.assertIn("md", allowed)

    def test_unknown_extension_stays_disallowed(self):
        allowed = self.settings._get_importable_extensions()
        self.assertNotIn("exe", allowed)

    def test_dsl_without_extensions_falls_back_to_acronym(self):
        self._new_dsl("PSL", False, status="active")
        allowed = self.settings._get_importable_extensions()
        self.assertIn("psl", allowed)

    def test_multiple_and_dotless_extensions_are_normalized(self):
        dsl = self._new_dsl("MSL", " .MSL , msl2 ", status="active")
        self.assertEqual(dsl._extensions(), ["msl", "msl2"])
        allowed = self.settings._get_importable_extensions()
        self.assertIn("msl", allowed)
        self.assertIn("msl2", allowed)

    def test_deprecated_dsl_extensions_fall_back_without_current_sibling(self):
        Dsl = self.env["itlingo.dsl"]
        self._new_dsl("DSL0", ".dsl0", status="deprecated")
        allowed = self.settings._get_importable_extensions()
        self.assertIn("dsl0", allowed)
        self.assertIn("dsl0", Dsl._all_extensions())
        self.assertEqual(Dsl._resolve_importable_extension("dsl0"), "dsl0")
        self.assertNotIn("dsl0-draft", allowed)
        self.assertNotIn("dsl0-draft", Dsl._all_extensions())

    def test_deprecated_dsl_extensions_are_shadowed_by_current_sibling(self):
        Dsl = self.env["itlingo.dsl"]
        self._new_dsl("DSL0", ".dsl0", status="deprecated", version="test-0.9")
        self._new_dsl("DSL0", ".dsl0", status="active", version="test-1.0")
        allowed = self.settings._get_importable_extensions()
        self.assertIn("dsl0", allowed)
        self.assertNotIn("dsl0-draft", allowed)
        self.assertEqual(Dsl._resolve_importable_extension("dsl0"), "dsl0")

    def test_odoo_archived_dsl_extensions_are_not_importable(self):
        dsl = self._new_dsl("ZSL", ".zsl", status="active")
        dsl.active = False
        allowed = self.settings._get_importable_extensions()
        self.assertNotIn("zsl", allowed)

    def test_resolve_importable_extension_active(self):
        Dsl = self.env["itlingo.dsl"]
        self._new_dsl("RSL", ".rsl", status="active")
        self.assertEqual(Dsl._resolve_importable_extension("rsl"), "rsl")
        self.assertEqual(Dsl._resolve_importable_extension(".RSL"), "rsl")

    def test_resolve_importable_extension_draft(self):
        Dsl = self.env["itlingo.dsl"]
        self._new_dsl("VSL", ".vsl", status="draft")
        self.assertEqual(Dsl._resolve_importable_extension("vsl"), "vsl-draft")
        # Idempotent: an already-suffixed extension resolves to itself.
        self.assertEqual(
            Dsl._resolve_importable_extension("vsl-draft"), "vsl-draft")

    def test_resolve_importable_extension_unknown(self):
        Dsl = self.env["itlingo.dsl"]
        self.assertIsNone(Dsl._resolve_importable_extension("txt"))
        self.assertIsNone(Dsl._resolve_importable_extension(""))
