import re
from urllib.parse import parse_qs, urlparse

from odoo import http
from odoo.addons.mail.tests.common import MockEmail
from odoo.tests import HttpCase, new_test_user, tagged
from odoo.tools.misc import mute_logger

PORTAL = 'base.group_portal,itlingo_core.group_itlingo_member'


@tagged('post_install', '-at_install')
class TestInvitationProofPortal(HttpCase, MockEmail):
    """Every emailed invitation goes through /itlingo/invitation: GET shows,
    a CSRF POST by the account of the invited email accepts, and a visitor
    signs in or signs up with the native token."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login='ipp_manager', password='ipp_manager',
                                    email='ipp_manager@example.com', groups=PORTAL)
        cls.invitee = new_test_user(cls.env, login='ipp_invitee', password='ipp_invitee',
                                    email='IPP.Invitee@Example.com', groups=PORTAL)
        cls.other = new_test_user(cls.env, login='ipp_other', password='ipp_other',
                                  email='ipp_other@example.com', groups=PORTAL)
        cls.org = cls.env['itlingo.organization'].create({'name': 'IPP Org'})
        cls.env['itlingo.organization.role'].create({
            'organization_id': cls.org.id, 'user_id': cls.manager.id,
            'role': 'org_manager', 'state': 'accepted'})
        # Test preconditions: public signup open on the test websites, and a
        # valid sender so the mocked gateway captures the invitation mails.
        cls.env['website'].search([]).write({'auth_signup_uninvited': 'b2c'})
        cls.env.company.email = 'ipp-noreply@example.com'

    def _login(self, user):
        if user:
            self.authenticate(user.login, user.login)
        else:
            self.authenticate(None, None)

    def _post(self, url, **data):
        data['csrf_token'] = http.Request.csrf_token(self)
        response = self.url_open(url, data=data, allow_redirects=False)
        self.env.invalidate_all()  # the request changed rows of this cursor
        return response

    def _invite(self, email, role='doc_manager'):
        """Manager invites through the portal; returns the mailed link."""
        self._login(self.manager)
        with self.mock_mail_gateway():
            response = self._post(f'/my/organizations/{self.org.id}/users/invite', email=email, role=role)
        self.assertEqual(response.status_code, 303)
        mail = self.env['mail.mail'].sudo().search([('email_to', '=', email.lower())],
                                                   order='id desc', limit=1)
        link = re.search(r'href="([^"]+)"', mail.body_html).group(1)
        parsed = urlparse(link)
        self.assertEqual(parsed.path, '/itlingo/invitation')
        return f'{parsed.path}?{parsed.query}', parse_qs(parsed.query)['token'][0]

    def _org_role(self, user):
        return self.env['itlingo.organization.role'].search([
            ('organization_id', '=', self.org.id), ('user_id', '=', user.id)])

    def test_existing_account_accepts_by_email_link(self):
        link, token = self._invite('ipp.invitee@example.com')
        # No role row (and no bell shortcut) before the proof.
        self.assertFalse(self._org_role(self.invitee))
        self._login(self.invitee)
        page = self.url_open(link)
        self.assertEqual(page.status_code, 200)
        self.assertIn('Accept invitation', page.text)
        self.assertFalse(self._org_role(self.invitee), 'GET must not grant')
        response = self._post('/itlingo/invitation/accept', token=token)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers['Location'].endswith(f'/my/organizations/{self.org.id}'))
        role = self._org_role(self.invitee)
        self.assertEqual((role.role, role.state), ('doc_manager', 'accepted'))
        # Replay: the link is consumed.
        with mute_logger('odoo.http'):
            self.assertEqual(self._post('/itlingo/invitation/accept', token=token).status_code, 403)
        self.assertIn('not valid', self.url_open(link).text)

    def test_wrong_account_bad_token_and_missing_csrf_are_denied(self):
        link, token = self._invite('ipp.invitee@example.com')
        self._login(self.other)
        self.assertIn('does not use this', self.url_open(link).text)
        with mute_logger('odoo.http'):
            self.assertEqual(self._post('/itlingo/invitation/accept', token=token).status_code, 403)
            self._login(self.invitee)
            self.assertEqual(
                self._post('/itlingo/invitation/accept', token=token[:-2] + 'xx').status_code, 403)
            no_csrf = self.url_open('/itlingo/invitation/accept', data={'token': token},
                                    allow_redirects=False)
        self.assertNotEqual(no_csrf.status_code, 303)
        self.assertFalse(self._org_role(self.other))
        self.assertFalse(self._org_role(self.invitee))

    def test_unverified_signup_then_resend_cannot_accept_via_bell(self):
        # Native public signup (no token) with somebody else's address.
        self.env['res.users'].sudo().signup({
            'login': 'ipp.victim@example.com', 'name': 'Squatter', 'password': 'Ipp-Strong-Pass-1'})
        squatter = self.env['res.users'].sudo().search([('login', '=', 'ipp.victim@example.com')])
        self._invite('ipp.victim@example.com', role='org_manager')
        self._login(self.manager)
        with self.mock_mail_gateway():
            response = self._post(f'/my/organizations/{self.org.id}/users/invite',
                                  email='IPP.Victim@example.com', role='org_manager')
        self.assertIn('invite_resent', response.headers['Location'])
        self.assertFalse(self._org_role(squatter))
        self.assertFalse(self.env['itlingo.notification'].sudo().search([
            ('user_id', '=', squatter.id), ('notification_type', '=', 'invite')]))

    def test_visitor_signs_up_with_native_token(self):
        link, token = self._invite('ipp.newcomer@example.com', role='org_member')
        self._login(None)
        page = self.url_open(link)
        self.assertIn('Create account', page.text)
        self.assertIn('/web/signup?token=', page.text)
        self.assertIn('/web/login?redirect=', page.text)
        self._post('/web/signup', token=token, login='ipp.newcomer@example.com', name='Newcomer',
                   password='Ipp-Strong-Pass-1', confirm_password='Ipp-Strong-Pass-1',
                   terms_accepted='on', redirect=f'/my/organizations/{self.org.id}')
        user = self.env['res.users'].sudo().search([('login', '=', 'ipp.newcomer@example.com')])
        self.assertTrue(user)
        role = self._org_role(user)
        self.assertEqual((role.role, role.state), ('org_member', 'accepted'))
        self.assertFalse(self.env['itlingo.pending.invitation'].sudo()._from_token(token))

    def test_legacy_pending_role_cannot_be_accepted_from_bell(self):
        legacy = self.env['itlingo.organization.role'].create({
            'organization_id': self.org.id, 'user_id': self.invitee.id,
            'role': 'org_manager', 'state': 'pending'})
        legacy.sudo().write({'mailbox_proof_required': True})  # as the 19.0.3.2.0 migration does
        notif = self.env['itlingo.notification'].sudo().search([
            ('res_model', '=', 'itlingo.organization.role'), ('res_id', '=', legacy.id)])
        self.assertTrue(notif)
        self._login(self.invitee)
        with mute_logger('odoo.http'):
            self._post(f'/my/notifications/{notif.id}/respond', action='accept')
        self.assertEqual(legacy.state, 'pending')
        # Resend + proof link accepts the same row.
        _link, token = self._invite('ipp.invitee@example.com', role='org_member')
        self._login(self.invitee)
        self._post('/itlingo/invitation/accept', token=token)
        self.assertEqual((legacy.state, legacy.role, legacy.mailbox_proof_required),
                         ('accepted', 'org_member', False))
