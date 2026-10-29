import base64

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestDslPermissions(TransactionCase):
    """Maintainer authoring rights come from the ORM, not from portal sudo."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        groups = 'base.group_portal,itlingo_core.group_itlingo_member'
        cls.maintainer = new_test_user(
            cls.env, login='perm_dsl_maintainer', groups=groups,
        )
        cls.other_maintainer = new_test_user(
            cls.env, login='perm_dsl_other_maintainer', groups=groups,
        )
        cls.reader = new_test_user(
            cls.env, login='perm_dsl_reader', groups=groups,
        )
        cls.admin = new_test_user(
            cls.env, login='perm_dsl_admin',
            groups='base.group_portal,itlingo_core.group_itlingo_admin',
        )
        Dsl = cls.env['itlingo.dsl']
        cls.draft = Dsl.create({
            'name': 'Permission Own', 'acronym': 'PERMOWN',
            'version': '1.0', 'status': 'draft',
            'maintainer_ids': [(6, 0, cls.maintainer.ids)],
        })
        cls.family = cls.draft.family_id
        cls.active = Dsl.create({
            'family_id': cls.family.id, 'version': '0.9', 'status': 'active',
            'notes': 'Internal maintainer note',
        })
        cls.other_draft = Dsl.create({
            'name': 'Permission Other', 'acronym': 'PERMOTHER',
            'version': '1.0', 'status': 'draft',
            'maintainer_ids': [(6, 0, cls.other_maintainer.ids)],
        })
        cls.other_family = cls.other_draft.family_id
        cls.other_active = Dsl.create({
            'family_id': cls.other_family.id, 'version': '0.9',
            'status': 'active',
        })
        File = cls.env['itlingo.dsl.file']
        cls.grammar = File._create_grammar_text(
            cls.draft, 'own.langium', 'grammar Own\n',
        )
        cls.other_grammar = File._create_grammar_text(
            cls.other_draft, 'other.langium', 'grammar Other\n',
        )
        cls.examples = File.create({
            'dsl_id': cls.draft.id,
            'file_type': 'examples',
            'file_name': 'examples.txt',
            'file': base64.b64encode(b'example'),
        })

    def test_maintainer_authors_own_family(self):
        draft = self.draft.with_user(self.maintainer)
        draft.write({'description': '<p>Own</p>', 'file_extensions': '.permown'})
        self.active.with_user(self.maintainer).write({'documentation_url': 'https://x'})

        File = self.env['itlingo.dsl.file'].with_user(self.maintainer)
        extra = File._create_grammar_text(draft, 'extra.langium', 'grammar Extra\n')
        extra.write({'relative_path': 'shared/extra.langium'})
        extra.unlink()
        self.assertEqual(draft.file_ids, self.grammar | self.examples)

        fork = self.active.with_user(self.maintainer).action_create_draft_version('2.0')
        self.assertEqual((fork.status, fork.family_id), ('draft', self.family))
        self.assertEqual(fork.sudo().notes, 'Internal maintainer note')

    def test_outsiders_cannot_author_other_families(self):
        File = self.env['itlingo.dsl.file']
        for user in (self.maintainer, self.reader):
            with self.subTest(user=user.login):
                with self.assertRaises(AccessError):
                    self.other_active.with_user(user).write({'description': 'x'})
                with self.assertRaises(AccessError):
                    self.other_draft.with_user(user).write({'description': 'x'})
                with self.assertRaises(AccessError):
                    File.with_user(user)._create_grammar_text(
                        self.other_draft, 'intruder.langium', 'grammar X\n',
                    )
                with self.assertRaises(AccessError):
                    self.other_grammar.with_user(user).unlink()
                with self.assertRaises(AccessError):
                    self.other_active.with_user(user).action_create_draft_version('9.0')
                with self.assertRaises(AccessError):
                    self.other_draft.with_user(user).action_validate_draft()

    def test_drafts_and_files_stay_with_maintainers(self):
        Dsl = self.env['itlingo.dsl']
        File = self.env['itlingo.dsl.file']
        families = [('family_id', 'in', (self.family | self.other_family).ids)]
        self.assertEqual(
            Dsl.with_user(self.reader).search(families),
            self.active | self.other_active,
        )
        self.assertEqual(
            Dsl.with_user(self.maintainer).search(families),
            self.draft | self.active | self.other_active,
        )
        files = [('id', 'in', (self.grammar | self.other_grammar).ids)]
        self.assertFalse(File.with_user(self.reader).search(files))
        self.assertEqual(File.with_user(self.maintainer).search(files), self.grammar)

        # Public metadata and compiled artifacts stay readable.
        public = self.active.with_user(self.reader)
        public.read(['version', 'grammar_validation_result', 'services_compiled'])

    def test_internal_fields_need_admin_or_assigned_family(self):
        diagnostics = '[{"severity": "error", "message": "internal"}]'
        (self.active | self.other_active).write({
            'grammar_validation_diagnostics': diagnostics,
        })
        # Maintainer group membership alone never reveals internal fields.
        for user in (self.reader, self.maintainer):
            for field_name in (
                'notes', 'grammar_validation_diagnostics',
                'services_compile_diagnostics', 'services_audit_ids',
            ):
                with self.subTest(user=user.login, field=field_name), \
                        self.assertRaises(AccessError):
                    self.active.with_user(user).read([field_name])
        # Assigned maintainers read their own family's diagnostics only.
        self.assertEqual(
            self.active.with_user(self.maintainer)._authoring_diagnostics(
                'grammar_validation_diagnostics',
            ),
            diagnostics,
        )
        with self.assertRaises(AccessError):
            self.other_active.with_user(self.maintainer)._authoring_diagnostics(
                'grammar_validation_diagnostics',
            )
        self.assertEqual(
            self.active.with_user(self.admin).notes, 'Internal maintainer note',
        )

    def test_maintainer_cannot_tamper_with_identity_or_associations(self):
        draft = self.draft.with_user(self.maintainer)
        family = self.family.with_user(self.maintainer)
        with self.assertRaises(AccessError):
            draft.write({'maintainer_ids': [(4, self.reader.id)]})
        with self.assertRaises(AccessError):
            family.write({'maintainer_ids': [(4, self.reader.id)]})
        with self.assertRaises(AccessError):
            family.write({'name': 'Renamed'})
        with self.assertRaises(AccessError):
            draft.write({'active': False})
        with self.assertRaises(ValidationError):
            draft.write({'family_id': self.other_family.id})
        with self.assertRaises(AccessError):
            self.examples.with_user(self.maintainer).write({
                'dsl_id': self.other_active.id,
            })
        with self.assertRaises(AccessError):
            draft.write({'services_compiled': 'export default () => ({});'})
        with self.assertRaises(AccessError):
            self.env['itlingo.dsl'].with_user(self.maintainer).create({
                'family_id': self.other_family.id, 'version': '9.0',
            })
        self.assertEqual(self.family.maintainer_ids, self.maintainer)
        self.assertEqual(self.examples.dsl_id, self.draft)

    def test_client_context_cannot_bypass_lifecycle_or_audit(self):
        for user in (self.maintainer, self.admin):
            with self.subTest(user=user.login):
                with self.assertRaisesRegex(ValidationError, 'Publish action'):
                    self.draft.with_user(user).with_context(
                        allow_dsl_lifecycle_write=True,
                    ).write({'status': 'deprecated'})
                with self.assertRaises(AccessError):
                    self.env['itlingo.dsl.services.audit'].with_user(
                        user,
                    ).with_context(allow_services_audit_create=True).create({
                        'dsl_id': self.draft.id,
                        'operation': 'create',
                        'relative_path': 'forged.ts',
                        'actor_id': user.id,
                    })
        with self.assertRaises(AccessError):
            self.env['itlingo.dsl'].with_user(self.maintainer).create({
                'family_id': self.family.id, 'version': '3.0', 'status': 'active',
            })
        self.assertEqual(self.draft.status, 'draft')

    def test_publication_and_deletion_stay_admin_only(self):
        deprecated = self.env['itlingo.dsl'].create({
            'family_id': self.family.id, 'version': '0.5', 'status': 'deprecated',
        })
        for dsl in (self.draft, deprecated):
            with self.subTest(status=dsl.status):
                with self.assertRaisesRegex(AccessError, 'platform administrators'):
                    dsl.with_user(self.maintainer).action_publish()
        with self.assertRaises(AccessError):
            self.draft.with_user(self.maintainer).unlink()
        self.assertEqual(deprecated.status, 'deprecated')

    def test_context_defaults_cannot_bypass_create_guards(self):
        Dsl = self.env['itlingo.dsl'].with_user(self.maintainer)
        # Authorized maintainer creates keep working, including plain defaults.
        own = Dsl.with_context(default_version='4.0').create({
            'family_id': self.family.id,
        })
        self.assertEqual((own.status, own.version), ('draft', '4.0'))

        with self.assertRaises(AccessError):
            Dsl.with_context(default_status='active').create({
                'family_id': self.family.id, 'version': '5.0',
            })
        with self.assertRaises(AccessError):
            Dsl.with_context(
                default_services_compiled='export default () => ({});',
            ).create({'family_id': self.family.id, 'version': '6.0'})
        with self.assertRaises(AccessError):
            Dsl.with_context(default_family_id=self.other_family.id).create({
                'version': '7.0',
            })
        with self.assertRaises(AccessError):
            Dsl.with_context(default_notes='Internal note').create({
                'family_id': self.family.id, 'version': '8.0',
            })
        # default_dsl_id must not skip the draft-only structural file guard.
        with self.assertRaisesRegex(ValidationError, 'draft status'):
            self.env['itlingo.dsl.file'].with_user(self.maintainer).with_context(
                default_dsl_id=self.active.id,
            ).create({
                'file_type': 'grammar',
                'file_name': 'bypass.langium',
                'file': base64.b64encode(b'grammar Bypass\n'),
            })
        self.assertFalse(self.env['itlingo.dsl'].search([
            ('family_id', 'in', (self.family | self.other_family).ids),
            ('version', 'in', ['5.0', '6.0', '7.0', '8.0']),
        ]))


@tagged('post_install', '-at_install')
class TestOrgResourcePermissions(TransactionCase):
    """Public visibility grants read only, never cross-organization writes."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        groups = 'base.group_portal,itlingo_core.group_itlingo_member'
        cls.member = new_test_user(
            cls.env, login='perm_org_resource_member', groups=groups,
        )
        cls.editor = new_test_user(
            cls.env, login='perm_org_resource_editor', groups=groups,
        )
        cls.colleague = new_test_user(
            cls.env, login='perm_org_resource_colleague', groups=groups,
        )
        Organization = cls.env['itlingo.organization']
        cls.org_a = Organization.create({'name': 'Resource Org A'})
        cls.org_b = Organization.create({'name': 'Resource Org B'})
        Role = cls.env['itlingo.organization.role']
        Role.create([
            {'user_id': cls.member.id, 'organization_id': cls.org_a.id,
             'role': 'org_member', 'state': 'accepted'},
            {'user_id': cls.editor.id, 'organization_id': cls.org_a.id,
             'role': 'doc_manager', 'state': 'accepted'},
            # A pending editor invitation plus someone else's accepted role
            # must not combine into write access (correlated role check).
            {'user_id': cls.editor.id, 'organization_id': cls.org_b.id,
             'role': 'doc_manager', 'state': 'pending'},
            {'user_id': cls.colleague.id, 'organization_id': cls.org_b.id,
             'role': 'org_manager', 'state': 'accepted'},
        ])
        Resource = cls.env['itlingo.org.resource']
        cls.own = Resource.create({
            'name': 'Own resource', 'organization_id': cls.org_a.id,
        })
        cls.public_other = Resource.create({
            'name': 'Public other', 'organization_id': cls.org_b.id,
            'visibility': 'public',
        })

    def test_public_resource_of_other_org_is_read_only(self):
        for user in (self.member, self.editor):
            with self.subTest(user=user.login):
                resource = self.public_other.with_user(user)
                self.assertEqual(resource.name, 'Public other')
                with self.assertRaises(AccessError):
                    resource.write({'name': 'Hijacked'})
                with self.assertRaises(AccessError):
                    resource.unlink()
        self.assertEqual(self.public_other.name, 'Public other')

    def test_plain_org_member_reads_but_cannot_edit(self):
        own = self.own.with_user(self.member)
        self.assertEqual(own.name, 'Own resource')
        with self.assertRaises(AccessError):
            own.write({'description': 'Member edit'})
        with self.assertRaises(AccessError):
            self.env['itlingo.org.resource'].with_user(self.member).create({
                'name': 'Member created', 'organization_id': self.org_a.id,
            })

    def test_editor_writes_own_org_but_cannot_move_resources(self):
        Resource = self.env['itlingo.org.resource'].with_user(self.editor)
        self.own.with_user(self.editor).write({'description': 'Updated'})
        Resource.create({'name': 'Created', 'organization_id': self.org_a.id})
        with self.assertRaises(AccessError):
            self.own.with_user(self.editor).write({'organization_id': self.org_b.id})
        with self.assertRaises(AccessError):
            Resource.create({'name': 'Foreign', 'organization_id': self.org_b.id})
        self.assertEqual(self.own.organization_id, self.org_a)


@tagged('post_install', '-at_install')
class TestDslResourceVisibility(TransactionCase):
    """DSL resources follow resource visibility and DSL draft privacy."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        groups = 'base.group_portal,itlingo_core.group_itlingo_member'
        cls.maintainer = new_test_user(
            cls.env, login='perm_dsl_resource_maintainer', groups=groups,
        )
        cls.reader = new_test_user(
            cls.env, login='perm_dsl_resource_reader', groups=groups,
        )
        Dsl = cls.env['itlingo.dsl']
        cls.active = Dsl.create({
            'name': 'Resource DSL', 'acronym': 'RESDSL',
            'version': '1.0', 'status': 'active',
            'maintainer_ids': [(6, 0, cls.maintainer.ids)],
        })
        cls.draft = Dsl.create({
            'family_id': cls.active.family_id.id, 'version': '2.0',
            'status': 'draft',
        })
        Resource = cls.env['itlingo.dsl.resource']
        cls.public = Resource.create({
            'name': 'Public', 'dsl_id': cls.active.id, 'visibility': 'public',
        })
        cls.protected = Resource.create({
            'name': 'Protected', 'dsl_id': cls.active.id,
            'visibility': 'protected',
        })
        cls.private = Resource.create({
            'name': 'Private', 'dsl_id': cls.active.id, 'visibility': 'private',
        })
        cls.draft_public = Resource.create({
            'name': 'Draft public', 'dsl_id': cls.draft.id,
            'visibility': 'public',
        })
        cls.all = cls.public | cls.protected | cls.private | cls.draft_public

    def _visible(self, user):
        return self.env['itlingo.dsl.resource'].with_user(user).search([
            ('id', 'in', self.all.ids),
        ])

    def test_signed_in_users_read_only_public_resources_of_public_dsls(self):
        self.assertEqual(self._visible(self.reader), self.public | self.protected)
        with self.assertRaises(AccessError):
            self.public.with_user(self.reader).write({'name': 'Changed'})

    def test_maintainers_read_private_and_draft_resources(self):
        self.assertEqual(self._visible(self.maintainer), self.all)
