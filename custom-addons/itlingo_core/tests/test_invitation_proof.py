import re
from urllib.parse import parse_qs, urlparse

from odoo.addons.mail.tests.common import MockEmail
from odoo.exceptions import AccessError, UserError
from odoo.modules.module import load_script
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools.misc import file_path

PORTAL = 'base.group_portal,itlingo_core.group_itlingo_member'


@tagged('post_install', '-at_install')
class TestInvitationProof(TransactionCase, MockEmail):
    """Email invitations are granted only to the holder of the mailed native
    signup token: a new account from it, or the signed-in account of that
    email. Real tokens, real mails (SMTP gateway mocked only)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.manager = new_test_user(env, login='ip_manager', email='ip_manager@example.com', groups=PORTAL)
        cls.invitee = new_test_user(env, login='ip_invitee', email='Invitee@Example.com', groups=PORTAL)
        cls.other = new_test_user(env, login='ip_other', email='ip_other@example.com', groups=PORTAL)
        cls.org = env['itlingo.organization'].create({'name': 'IP Org'})
        cls.other_org = env['itlingo.organization'].create({'name': 'IP Other Org'})
        cls.ws = env['itlingo.workspace'].create({'name': 'IP WS', 'organization_id': cls.org.id})
        env['itlingo.organization.role'].create({
            'organization_id': cls.org.id, 'user_id': cls.manager.id,
            'role': 'org_manager', 'state': 'accepted'})
        # Valid sender, so the mocked gateway captures the invitation mails.
        env.company.email = 'ip-noreply@example.com'

    def _invite(self, email, role='doc_manager', scope=None):
        """Invite as the manager and return (invitation, token of the mail)."""
        Pending = self.env['itlingo.pending.invitation'].with_user(self.manager)
        with self.mock_mail_gateway():
            inv = Pending.create(dict(scope or {'organization_id': self.org.id}, email=email, role=role))
            inv._send_signup_email()
        return inv.sudo(), self._mailed_token(inv.sudo().email)

    def _mailed_token(self, email):
        mail = self.env['mail.mail'].sudo().search([('email_to', '=', email)], order='id desc', limit=1)
        link = re.search(r'href="([^"]+)"', mail.body_html).group(1)
        self.assertIn('/itlingo/invitation?', link)
        return parse_qs(urlparse(link).query)['token'][0]

    def _org_role(self, user, org=None):
        return self.env['itlingo.organization.role'].search([
            ('organization_id', '=', (org or self.org).id), ('user_id', '=', user.id)])

    def test_pending_create_ignores_default_context(self):
        Pending = self.env['itlingo.pending.invitation'].with_user(self.manager).with_context(
            default_partner_id=self.invitee.partner_id.id,
            default_invited_by_id=self.other.id,
            default_parent_id=self.other.partner_id.id,
            default_project_id=self.ws.id,
        )
        inv = Pending.create({'email': ' Victim@Example.COM ', 'organization_id': self.org.id,
                              'role': 'org_member'}).sudo()
        self.assertEqual(inv.email, 'victim@example.com')
        self.assertEqual(inv.invited_by_id, self.manager)
        self.assertFalse(inv.project_id)
        self.assertNotEqual(inv.partner_id, self.invitee.partner_id)
        self.assertFalse(inv.partner_id.user_ids)
        self.assertFalse(inv.partner_id.parent_id)
        with self.assertRaises(AccessError):
            Pending.create({'email': 'x@example.com', 'organization_id': self.org.id,
                            'role': 'org_member', 'partner_id': self.invitee.partner_id.id})
        with self.assertRaises(AccessError):
            self.env['itlingo.pending.invitation'].with_user(self.manager).create({
                'email': 'x@example.com', 'organization_id': self.other_org.id, 'role': 'org_member'})
        with self.assertRaises(AccessError):
            self.env['itlingo.pending.invitation'].with_user(self.other).create({
                'email': 'x@example.com', 'project_id': self.ws.id, 'role': 'ws_manager'})

    def test_existing_account_claims_only_with_mailed_token(self):
        inv, token = self._invite('invitee@example.com', role='doc_manager')
        Pending = self.env['itlingo.pending.invitation']
        self.assertFalse(Pending._claim_with_token('not-a-token', self.invitee))
        self.assertFalse(Pending._claim_with_token(token[:-2] + 'xx', self.invitee))
        # The token holder must use the account of the invited email.
        self.assertFalse(Pending._claim_with_token(token, self.other))
        self.assertTrue(inv.exists())
        self.assertFalse(self._org_role(self.other))
        url = Pending._claim_with_token(token, self.invitee)
        self.assertEqual(url, f'/my/organizations/{self.org.id}')
        role = self._org_role(self.invitee)
        self.assertEqual((role.role, role.state), ('doc_manager', 'accepted'))
        self.assertFalse(inv.exists())
        # One-time: the token of the contact is cancelled.
        self.assertFalse(Pending._from_token(token))
        self.assertFalse(Pending._claim_with_token(token, self.invitee))

    def test_unverified_signup_and_resend_give_no_bell_invitation(self):
        squatter = self.env['res.users'].sudo().with_context(no_reset_password=True).create({
            'name': 'Squatter', 'login': 'victim@example.com', 'email': 'victim@example.com',
            'group_ids': [(6, 0, self.env.ref('base.group_portal').ids)]})
        inv, _token = self._invite('victim@example.com', role='org_manager')
        with self.mock_mail_gateway():
            inv.with_user(self.manager)._send_signup_email()  # manager resends
        self.assertFalse(self._org_role(squatter))
        self.assertFalse(self.env['itlingo.notification'].sudo().search([
            ('user_id', '=', squatter.id), ('notification_type', '=', 'invite')]))
        self.assertNotEqual(inv.partner_id, squatter.partner_id)
        self.assertTrue(inv.exists())

    def test_native_token_signup_claims_frozen_role(self):
        inv, token = self._invite('newcomer@example.com', role='ws_member', scope={'project_id': self.ws.id})
        Users = self.env['res.users'].sudo()
        login, _pw = Users.signup({'login': 'newcomer-login@example.com', 'name': 'Newcomer',
                                   'password': 'Ip-Strong-Pass-1'}, token)
        user = Users.search([('login', '=', login)])
        ws_role = self.env['itlingo.project.role'].search([
            ('project_id', '=', self.ws.id), ('user_id', '=', user.id)])
        self.assertEqual((ws_role.role, ws_role.state), ('ws_member', 'accepted'))
        self.assertEqual(self._org_role(user).state, 'accepted')
        self.assertFalse(inv.exists())
        with self.assertRaises(UserError):
            Users.signup({'login': 'replay@example.com', 'name': 'Replay',
                          'password': 'Ip-Strong-Pass-1'}, token)

    def test_duplicate_invite_keeps_accepted_membership(self):
        self.env['itlingo.organization.role'].create({
            'organization_id': self.org.id, 'user_id': self.invitee.id,
            'role': 'org_member', 'state': 'accepted'})
        inv, token = self._invite('invitee@example.com', role='org_manager')
        self.assertTrue(self.env['itlingo.pending.invitation']._claim_with_token(token, self.invitee))
        self.assertEqual(self._org_role(self.invitee).role, 'org_member')
        self.assertFalse(inv.exists())

    def test_legacy_pending_role_needs_mailbox_proof(self):
        legacy = self.env['itlingo.organization.role'].create({
            'organization_id': self.org.id, 'user_id': self.invitee.id,
            'role': 'org_manager', 'state': 'pending'})
        accepted = self._org_role(self.manager)
        post = load_script(file_path('itlingo_core/migrations/19.0.3.2.0/post-migrate.py'),
                           'itlingo_core_test_invitation_post_migrate')
        self.env.flush_all()
        post.migrate(self.env.cr, '19.0.3.1.0')
        self.env.invalidate_all()
        self.assertTrue(legacy.mailbox_proof_required)
        self.assertFalse(accepted.mailbox_proof_required)
        with self.assertRaises(AccessError):
            legacy.with_user(self.invitee).action_accept()
        self.assertEqual(legacy.state, 'pending')
        # The manager resends; the proof link accepts the same row with the
        # role of the new invitation.
        _inv, token = self._invite('invitee@example.com', role='doc_manager')
        self.assertTrue(self.env['itlingo.pending.invitation']._claim_with_token(token, self.invitee))
        self.assertEqual((legacy.state, legacy.role, legacy.mailbox_proof_required),
                         ('accepted', 'doc_manager', False))
