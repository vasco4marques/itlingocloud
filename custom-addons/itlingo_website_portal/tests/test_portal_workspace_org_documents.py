from lxml import html

from odoo.tests import HttpCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestPortalWorkspaceOrgDocuments(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.member = new_test_user(
            cls.env,
            login='workspace_org_documents_member',
            password='workspace_org_documents_member',
            name='Workspace Organization Documents Member',
            groups=(
                'base.group_portal,'
                'itlingo_organizations.group_itlingo_member'
            ),
        )
        cls.organization = cls.env['itlingo.organization'].sudo().create({
            'name': 'Portal Workspace Organization Documents Test',
        })
        cls.workspace = cls.env['itlingo.workspace'].sudo().create({
            'name': 'Public Workspace Organization Documents Test',
            'organization_id': cls.organization.id,
            'is_public_workspace': True,
        })
        cls.env['itlingo.project.role'].sudo().create({
            'user_id': cls.member.id,
            'project_id': cls.workspace.id,
            'role': 'ws_member',
            'state': 'accepted',
        })
        cls.env['itlingo.organization.role'].sudo().create({
            'user_id': cls.member.id,
            'organization_id': cls.organization.id,
            'role': 'org_member',
            'state': 'accepted',
        })
        cls.document = cls.env['itlingo.document'].sudo().create({
            'name': 'Published Organization Workspace Document',
            'document_type_id': cls.env.ref(
                'itlingo_documents.doc_type_other',
            ).id,
            'organization_id': cls.organization.id,
            'project_id': False,
            'status': 'published',
        })

    def test_member_sees_organization_documents_on_public_workspace(self):
        self.authenticate(self.member.login, self.member.login)
        response = self.url_open(
            f'/my/workspaces/{self.workspace.id}/documents',
        )

        self.assertEqual(response.status_code, 200)
        document = html.fromstring(response.content)
        page_text = ' '.join(document.text_content().split())
        self.assertIn('Organization documents', page_text)
        self.assertTrue(document.xpath(
            "//a[@href=$href]",
            href=(
                f'/my/workspaces/{self.workspace.id}/documents/'
                f'organization/{self.document.id}'
            ),
        ))

    def test_public_visitor_does_not_see_organization_documents(self):
        self.authenticate(None, None)
        response = self.url_open(
            f'/public-workspaces/{self.workspace.id}/documents',
        )

        self.assertEqual(response.status_code, 200)
        document = html.fromstring(response.content)
        page_text = ' '.join(document.text_content().split())
        self.assertNotIn('Organization documents', page_text)
