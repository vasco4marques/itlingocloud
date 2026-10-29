from odoo import http
from odoo.tests import HttpCase, new_test_user, tagged
from odoo.tools.misc import mute_logger

PORTAL = 'base.group_portal,itlingo_core.group_itlingo_member'


@tagged('post_install', '-at_install')
class TestPortalCorePermissions(HttpCase):
    """Portal organization flows run as the user: allowed paths still work,
    and the model policy refuses what the route would not offer."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login='pcp_manager', password='pcp_manager', groups=PORTAL)
        cls.member = new_test_user(cls.env, login='pcp_member', password='pcp_member', groups=PORTAL)
        cls.org = cls.env['itlingo.organization'].create({'name': 'PCP Org'})
        Role = cls.env['itlingo.organization.role']
        Role.create({'organization_id': cls.org.id, 'user_id': cls.manager.id,
                     'role': 'org_manager', 'state': 'accepted'})
        cls.member_role = Role.create({'organization_id': cls.org.id, 'user_id': cls.member.id,
                                       'role': 'org_member', 'state': 'accepted'})

    def _post(self, user, url, **data):
        self.authenticate(user.login, user.login)
        data['csrf_token'] = http.Request.csrf_token(self)
        return self.url_open(url, data=data, allow_redirects=False)

    def test_manager_changes_roles(self):
        self._post(self.manager, f'/my/organizations/{self.org.id}/users/{self.member_role.id}/role',
                   role='doc_manager')
        self.assertEqual(self.member_role.role, 'doc_manager')

    def test_member_cannot_promote_self(self):
        with mute_logger('odoo.http'):
            response = self._post(
                self.member, f'/my/organizations/{self.org.id}/users/{self.member_role.id}/role',
                role='org_manager')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.member_role.role, 'org_member')

    def test_new_organization_makes_creator_manager(self):
        self._post(self.member, '/my/organizations/new', name='PCP Member Org', activity_type='it')
        org = self.env['itlingo.organization'].search([('name', '=', 'PCP Member Org')])
        self.assertEqual(org._itlingo_user_role(self.member).role, 'org_manager')
