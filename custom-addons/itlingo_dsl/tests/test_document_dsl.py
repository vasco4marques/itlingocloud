import base64
import unittest

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDocumentDslFamily(TransactionCase):
    def setUp(self):
        super().setUp()
        self.family_version = self.env['itlingo.dsl'].create({
            'name': 'Document Family Test',
            'acronym': 'DOCFAM',
            'version': '1.0',
            'status': 'active',
            'file_extensions': '.docfam',
        })
        self.family = self.family_version.family_id
        self.other_version = self.env['itlingo.dsl'].create({
            'name': 'Document Family Test',
            'acronym': 'DOCFAM',
            'version': '2.0',
            'status': 'draft',
            'family_id': self.family.id,
            'file_extensions': '.docfam',
        })
        self.organization = self.env['itlingo.organization'].create({
            'name': 'Document Family Test Org',
        })
        self.workspace = self.env['itlingo.workspace'].create({
            'name': 'Document Family Test Workspace',
            'organization_id': self.organization.id,
        })

    def test_version_requires_matching_family(self):
        with self.assertRaises(ValidationError):
            self.env['itlingo.document'].create({
                'name': 'Version Without Family',
                'dsl_version_id': self.family_version.id,
            })
        with self.assertRaises(ValidationError):
            self.env['itlingo.document'].create({
                'name': 'Cross Family Version',
                'dsl_family_id': self.env['itlingo.dsl.family'].create({
                    'name': 'Other Family',
                    'acronym': 'OTHER',
                }).id,
                'dsl_version_id': self.family_version.id,
            })

    def test_source_corpus_ignores_document_version_pins(self):
        documents = self.env['itlingo.document'].create([
            {
                'name': 'Active Version Source',
                'project_id': self.workspace.id,
                'dsl_family_id': self.family.id,
                'dsl_version_id': self.family_version.id,
                'file_name': 'active.docfam',
                'document_file': base64.b64encode(b'active'),
            },
            {
                'name': 'Draft Version Source',
                'project_id': self.workspace.id,
                'dsl_family_id': self.family.id,
                'dsl_version_id': self.other_version.id,
                'file_name': 'draft.docfam',
                'document_file': base64.b64encode(b'draft'),
            },
        ])
        corpus = self.env['itlingo.document']._scoped_dsl_source_documents(
            self.family_version,
            project=self.workspace,
        )
        self.assertEqual(set(corpus.ids), set(documents.ids))


@tagged('post_install', '-at_install')
class TestDocumentFormat(TransactionCase):

    def test_format_tracks_dsl_publication_and_deprecation(self):
        dsl = self.env['itlingo.dsl'].create({
            'name': 'Dynamic Format Test',
            'acronym': 'DFT',
            'version': 'test-1',
            'status': 'draft',
            'file_extensions': '.dynamicformat',
        })
        document = self.env['itlingo.document'].create({
            'name': 'Dynamic Format Source',
            'file_name': 'source.dynamicformat',
        })

        self.assertEqual(document.document_format, 'other')

        dsl.with_context(allow_dsl_lifecycle_write=True).write({'status': 'active'})
        self.assertEqual(document.document_format, 'text')

        dsl.with_context(allow_dsl_lifecycle_write=True).write({'status': 'deprecated'})
        self.assertEqual(document.document_format, 'text')

        dsl.unlink()
        self.assertEqual(document.document_format, 'other')


@tagged('post_install', '-at_install')
class TestDslDocumentKbSync(TransactionCase):

    def setUp(self):
        super().setUp()
        try:
            self.KBFile = self.env['itlingo.kb.file'].sudo()
        except KeyError as exc:
            raise unittest.SkipTest('itlingo.kb.file is not installed') from exc
        self.env.cr.execute("SELECT to_regclass('chatbot_kbfile')")
        if not self.env.cr.fetchone()[0]:
            raise unittest.SkipTest('chatbot_kbfile table is not installed')

        self.org = self.env['itlingo.organization'].create({
            'name': 'KB Sync Test Org',
        })
        self.workspace = self.env['itlingo.workspace'].create({
            'name': 'KB Sync Test Workspace',
            'organization_id': self.org.id,
        })
        self.doc_type = self.env.ref('itlingo_core.doc_type_specification')

    def test_registered_dsl_extension_is_text_and_syncs_to_kb(self):
        self.env['itlingo.dsl'].create({
            'name': 'Knowledge Extension Test',
            'acronym': 'KXT',
            'version': 'test-1',
            'status': 'active',
            'file_extensions': '.kxt',
        })
        doc = self.env['itlingo.document'].create({
            'name': 'Dynamic DSL Source',
            'document_type_id': self.doc_type.id,
            'project_id': self.workspace.id,
            'file_name': 'dynamic_source.kxt',
            'document_file': base64.b64encode(b'entity Dynamic'),
            'status': 'published',
            'dsl_knowledge': True,
        })

        self.assertEqual(doc.document_format, 'text')
        kb_file = self.KBFile.search([
            ('file_type', '=', 'other'),
            ('source_url', '=', 'odoo://itlingo.document/%s' % doc.id),
        ])
        self.assertEqual(len(kb_file), 1)
        self.assertEqual(kb_file.content, 'entity Dynamic')
