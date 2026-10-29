import base64
import unittest

from psycopg2 import IntegrityError

from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestDocumentOwnership(TransactionCase):

    def setUp(self):
        super().setUp()
        self.organization = self.env['itlingo.organization'].create({
            'name': 'Document Ownership Test Org',
        })
        self.workspace = self.env['itlingo.workspace'].create({
            'name': 'Document Ownership Test Workspace',
            'organization_id': self.organization.id,
        })

    def test_document_rejects_dual_ownership(self):
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.env['itlingo.document'].create({
                'name': 'Dual-Owned Document',
                'project_id': self.workspace.id,
                'organization_id': self.organization.id,
            })

    def test_review_workflow_needs_no_library(self):
        payload = base64.b64encode(b'Requirement: login')
        doc = self.env['itlingo.document'].create({
            'name': 'Workflow Document',
            'document_type_id': self.env.ref('itlingo_core.doc_type_specification').id,
            'project_id': self.workspace.id,
            'file_name': 'workflow.rsl',
            'document_file': payload,
        })

        doc.action_submit_review()
        self.assertEqual(doc.status, 'in_review')
        doc.action_approve()
        self.assertEqual(doc.status, 'approved')
        doc.action_publish()
        self.assertEqual(doc.status, 'published')
        self.assertEqual(doc.document_file, payload)


@tagged('post_install', '-at_install')
class TestDocumentKbSync(TransactionCase):

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

    def test_published_grounding_document_creates_stable_kb_file(self):
        doc = self.env['itlingo.document'].create({
            'name': 'Grounding Source',
            'document_type_id': self.doc_type.id,
            'project_id': self.workspace.id,
            'file_name': 'grounding_source.txt',
            'document_file': base64.b64encode(b'Glossary term: actor'),
            'status': 'published',
            'dsl_knowledge': True,
        })

        source_url = 'odoo://itlingo.document/%s' % doc.id
        kb_file = self.KBFile.search([
            ('file_type', '=', 'other'),
            ('source_url', '=', source_url),
        ])
        self.assertEqual(len(kb_file), 1)
        self.assertEqual(kb_file.content, 'Glossary term: actor')

        doc.write({'file_name': 'renamed_grounding_source.txt'})
        kb_file = self.KBFile.search([
            ('file_type', '=', 'other'),
            ('source_url', '=', source_url),
        ])
        self.assertEqual(len(kb_file), 1)
        self.assertEqual(kb_file.file_name, 'renamed_grounding_source.txt')

    def test_binary_file_cannot_be_grounding_knowledge(self):
        with self.env.cr.savepoint(), self.assertRaises(ValidationError):
            self.env['itlingo.document'].create({
                'name': 'Binary Source',
                'document_type_id': self.doc_type.id,
                'project_id': self.workspace.id,
                'file_name': 'binary_source.docx',
                'document_file': base64.b64encode(b'PK\x03\x04binary'),
                'status': 'published',
                'dsl_knowledge': True,
            })

    def test_refused_unlink_keeps_document_and_kb_file(self):
        doc = self.env['itlingo.document'].create({
            'name': 'Protected Grounding Source',
            'document_type_id': self.doc_type.id,
            'project_id': self.workspace.id,
            'file_name': 'protected_source.txt',
            'document_file': base64.b64encode(b'Glossary term: system'),
            'status': 'published',
            'dsl_knowledge': True,
        })
        member = new_test_user(
            self.env, login='kb_unlink_member',
            groups='base.group_portal,itlingo_core.group_itlingo_member',
        )
        self.env['itlingo.project.role'].create({
            'project_id': self.workspace.id, 'user_id': member.id,
            'role': 'ws_member', 'state': 'accepted',
        })
        source_url = 'odoo://itlingo.document/%s' % doc.id
        try:
            doc.with_user(member).unlink()
        except AccessError:
            pass  # the portal catches errors the same way
        else:
            self.fail('A plain workspace member deleted a document.')
        self.env.invalidate_all()
        self.assertTrue(doc.exists())
        self.assertEqual(len(self.KBFile.search([
            ('file_type', '=', 'other'), ('source_url', '=', source_url),
        ])), 1)
