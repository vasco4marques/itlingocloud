from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestDslFamilyLifecycle(TransactionCase):
    def test_version_creation_finds_or_creates_family(self):
        dsl = self.env["itlingo.dsl"].create({
            "name": "Family Test Language",
            "acronym": "FTL",
            "version": "1.0",
        })

        self.assertTrue(dsl.family_id)
        self.assertEqual(dsl.family_id.name, "Family Test Language")
        self.assertEqual(dsl.family_id.acronym, "FTL")
        self.assertEqual(dsl.family_id.dsl_ids, dsl)

    def test_explicit_family_is_source_of_stable_identity(self):
        family = self.env["itlingo.dsl.family"].create({
            "name": "Stable Family",
            "acronym": "SFL",
        })
        dsl = self.env["itlingo.dsl"].create({
            "family_id": family.id,
            "name": "Conflicting Version Name",
            "acronym": "OTHER",
            "version": "1.0",
        })

        self.assertEqual(dsl.family_id, family)
        self.assertEqual(dsl.name, "Stable Family")
        self.assertEqual(dsl.acronym, "SFL")
    def test_active_create_rejects_duplicate_family_active(self):
        dsl = self.env["itlingo.dsl"].create({
            "name": "Active First Family",
            "acronym": "AFF",
            "version": "1.0",
            "status": "active",
        })
        self.assertEqual(dsl.status, "active")

        with self.assertRaisesRegex(ValidationError, "only one active"):
            self.env["itlingo.dsl"].create({
                "family_id": dsl.family_id.id,
                "version": "2.0",
                "status": "active",
            })

    def test_existing_version_cannot_move_between_families(self):
        dsl = self.env["itlingo.dsl"].create({
            "name": "Move Guard Family",
            "acronym": "MGF",
            "version": "1.0",
        })
        other = self.env["itlingo.dsl.family"].create({
            "name": "Other Family",
            "acronym": "OTH",
        })

        with self.assertRaisesRegex(ValidationError, "cannot be moved"):
            dsl.write({"family_id": other.id})
        self.assertEqual(dsl.family_id.acronym, "MGF")
    def test_versions_reuse_family_for_drafts(self):
        dsl = self.env["itlingo.dsl"].create({
            "name": "Reusable Family",
            "acronym": "RFL",
            "version": "1.0",
            "status": "active",
        })
        draft = dsl.action_create_draft_version("2.0")

        self.assertEqual(draft.family_id, dsl.family_id)
        self.assertEqual(draft.name, dsl.name)
        self.assertEqual(draft.acronym, dsl.acronym)
        self.assertEqual(draft.status, "draft")

    def test_maintainers_live_on_family_and_propagate_to_versions(self):
        user = new_test_user(
            self.env,
            login="dsl_family_maintainer",
            groups="base.group_portal,itlingo_core.group_itlingo_member",
        )
        dsl = self.env["itlingo.dsl"].create({
            "name": "Maintained Family",
            "acronym": "MFL",
            "version": "1.0",
        })

        dsl.family_id.write({"maintainer_ids": [(6, 0, [user.id])]})
        self.assertIn(user, dsl.maintainer_ids)
        self.assertIn(user, dsl.family_id.maintainer_ids)

        dsl.write({"maintainer_ids": [(3, user.id)]})
        self.assertNotIn(user, dsl.family_id.maintainer_ids)
    def test_validate_draft_does_not_publish(self):
        dsl = self.env["itlingo.dsl"].create({
            "name": "Validation Family",
            "acronym": "VFL",
            "version": "1.0",
        })

        self.assertTrue(dsl.action_validate_draft())
        self.assertEqual(dsl.status, "draft")

    def test_direct_status_changes_require_publish_action(self):
        dsl = self.env["itlingo.dsl"].create({
            "name": "Lifecycle Family",
            "acronym": "LFL",
            "version": "1.0",
        })

        with self.assertRaisesRegex(ValidationError, "Publish action"):
            dsl.write({"status": "active"})
        self.assertEqual(dsl.status, "draft")


    def test_version_without_family_requires_identity_for_migration_safety(self):
        with self.assertRaises(ValidationError):
            self.env["itlingo.dsl"].create({"version": "1.0"})

    def test_family_acronyms_are_case_insensitive(self):
        self.env["itlingo.dsl.family"].create({
            "name": "Canonical Family",
            "acronym": "CFL",
        })
        with self.assertRaises(ValidationError):
            self.env["itlingo.dsl.family"].create({
                "name": "Duplicate Family",
                "acronym": "cfl",
            })
