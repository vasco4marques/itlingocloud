from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestCoreMemberScope(TransactionCase):
    """Core-only regression for merged ACLs, record rules and load order."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        groups = 'base.group_portal,itlingo_core.group_itlingo_member'
        cls.member = new_test_user(
            cls.env, login='core_scope_member', groups=groups,
        )
        cls.outsider = new_test_user(
            cls.env, login='core_scope_outsider', groups=groups,
        )
        Organization = cls.env['itlingo.organization']
        Workspace = cls.env['itlingo.workspace']
        cls.org_a = Organization.create({'name': 'Core Scope Org A'})
        cls.org_b = Organization.create({'name': 'Core Scope Org B'})
        cls.ws_a = Workspace.create({
            'name': 'Core Scope Workspace A', 'organization_id': cls.org_a.id,
        })
        cls.ws_b = Workspace.create({
            'name': 'Core Scope Workspace B', 'organization_id': cls.org_b.id,
        })
        cls.env['itlingo.organization.role'].create({
            'user_id': cls.member.id, 'organization_id': cls.org_a.id,
            'role': 'org_member', 'state': 'accepted',
        })
        cls.env['itlingo.project.role'].create({
            'user_id': cls.member.id, 'project_id': cls.ws_a.id,
            'role': 'ws_member', 'state': 'accepted',
        })
        Document = cls.env['itlingo.document']
        cls.doc_org_a = Document.create({
            'name': 'Org A Doc', 'organization_id': cls.org_a.id,
        })
        cls.doc_ws_a = Document.create({
            'name': 'Workspace A Doc', 'project_id': cls.ws_a.id,
        })
        cls.doc_org_b = Document.create({
            'name': 'Org B Doc', 'organization_id': cls.org_b.id,
        })
        cls.doc_ws_b = Document.create({
            'name': 'Workspace B Doc', 'project_id': cls.ws_b.id,
        })
        Notification = cls.env['itlingo.notification']
        cls.own_notification = Notification._notify(
            cls.member, 'Own', '<p>own</p>',
        )
        cls.other_notification = Notification._notify(
            cls.outsider, 'Other', '<p>other</p>',
        )

    def _visible(self, model, records):
        return self.env[model].with_user(self.member).search([
            ('id', 'in', records.ids),
        ])

    def test_member_sees_only_own_scope(self):
        self.assertEqual(
            self._visible('itlingo.organization', self.org_a | self.org_b),
            self.org_a,
        )
        self.assertEqual(
            self._visible('itlingo.workspace', self.ws_a | self.ws_b),
            self.ws_a,
        )
        documents = self.doc_org_a | self.doc_ws_a | self.doc_org_b | self.doc_ws_b
        self.assertEqual(
            self._visible('itlingo.document', documents),
            self.doc_org_a | self.doc_ws_a,
        )

    def test_member_reads_only_own_notifications(self):
        notifications = self.own_notification | self.other_notification
        self.assertEqual(
            self._visible('itlingo.notification', notifications),
            self.own_notification,
        )
        self.own_notification.with_user(self.member).action_mark_read()
        self.assertTrue(self.own_notification.is_read)

        other = self.other_notification.with_user(self.member)
        with self.assertRaises(AccessError):
            other.read(['title'])
        with self.assertRaises(AccessError):
            other.action_mark_read()
        self.assertFalse(self.other_notification.is_read)
