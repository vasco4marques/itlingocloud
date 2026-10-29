from lxml import html

from odoo.tests import HttpCase, new_test_user, tagged
from odoo.tools.misc import mute_logger


@tagged('post_install', '-at_install')
class TestPortalOrganizationUsers(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        groups = (
            'base.group_portal,'
            'itlingo_organizations.group_itlingo_member'
        )
        cls.manager = new_test_user(
            cls.env,
            login='org_users_manager',
            password='org_users_manager',
            name='Portal Users Manager',
            groups=groups,
        )
        cls.member = new_test_user(
            cls.env,
            login='org_users_member',
            password='org_users_member',
            name='Portal Users Member',
            groups=groups,
        )
        cls.doc_manager = new_test_user(
            cls.env,
            login='org_users_doc_manager',
            password='org_users_doc_manager',
            name='Portal Users Document Manager',
            groups=groups,
        )
        cls.outsider = new_test_user(
            cls.env,
            login='org_users_outsider',
            password='org_users_outsider',
            name='Portal Users Outsider',
            groups=groups,
        )

        cls.organization = cls.env['itlingo.organization'].sudo().create({
            'name': 'Portal Organization Users Test',
        })
        cls.env['itlingo.organization.role'].sudo().create([
            {
                'organization_id': cls.organization.id,
                'user_id': cls.manager.id,
                'role': 'org_manager',
                'state': 'accepted',
            },
            {
                'organization_id': cls.organization.id,
                'user_id': cls.member.id,
                'role': 'org_member',
                'state': 'accepted',
            },
            {
                'organization_id': cls.organization.id,
                'user_id': cls.doc_manager.id,
                'role': 'doc_manager',
                'state': 'accepted',
            },
        ])
        cls.member_count = 3

    def _users_page(self, user):
        self.authenticate(user.login, user.login)
        response = self.url_open(
            f'/my/organizations/{self.organization.id}/users',
        )
        self.assertEqual(response.status_code, 200)
        return response

    def _member_rows(self, response):
        document = html.fromstring(response.content)
        return document.xpath("//table[contains(@class, 'table')]//tbody/tr")

    def _assert_own_row_only(self, response, user):
        rows = self._member_rows(response)
        self.assertEqual(len(rows), 1)
        self.assertIn(user.login, rows[0].text_content())
        for other in (self.manager, self.member, self.doc_manager):
            if other != user:
                self.assertNotIn(other.name, response.text)
                self.assertNotIn(other.login, response.text)
        document = html.fromstring(response.content)
        self.assertFalse(
            document.xpath("//p[normalize-space()='Member filters']")
        )
        self.assertFalse(
            document.xpath(
                "//div[contains(concat(' ', normalize-space(@class), ' '),"
                " ' o_portal_pager ')]"
            )
        )
        headers = document.xpath(
            "//h5[starts-with(normalize-space(.), 'Members (')]"
        )
        self.assertEqual(len(headers), 1)
        self.assertIn(
            f'Members ({self.member_count})',
            ' '.join(headers[0].text_content().split()),
        )

    def test_org_manager_sees_all_accepted_members(self):
        response = self._users_page(self.manager)
        self.assertEqual(len(self._member_rows(response)), 3)
        for member in (self.manager, self.member, self.doc_manager):
            self.assertIn(member.login, response.text)

    def test_org_member_sees_only_own_row_and_true_total(self):
        self._assert_own_row_only(self._users_page(self.member), self.member)

    def test_doc_manager_sees_only_own_row_and_true_total(self):
        self._assert_own_row_only(
            self._users_page(self.doc_manager), self.doc_manager,
        )

    def test_org_member_filters_cannot_probe_other_members(self):
        self.authenticate(self.member.login, self.member.login)
        response = self.url_open(
            f'/my/organizations/{self.organization.id}/users'
            f'?name={self.manager.login}&role_org_manager=1',
        )
        self.assertEqual(response.status_code, 200)
        self._assert_own_row_only(response, self.member)

    def test_user_without_accepted_role_is_denied(self):
        self.authenticate(self.outsider.login, self.outsider.login)
        with mute_logger('odoo.http'):
            response = self.url_open(
                f'/my/organizations/{self.organization.id}/users',
            )
        self.assertEqual(response.status_code, 403)
