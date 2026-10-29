from urllib.parse import urlencode

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, MissingError, ValidationError
from odoo.tools import email_normalize

from .itlingo_organization import _is_itlingo_admin, _strip_default_context


class ItlingoPendingInvitation(models.Model):
    _name = 'itlingo.pending.invitation'
    _description = 'Invitation that waits for proof of the invited mailbox'
    _order = 'create_date desc'

    email = fields.Char(required=True, index=True)
    organization_id = fields.Many2one(
        'itlingo.organization', ondelete='cascade',
    )
    project_id = fields.Many2one(
        'itlingo.workspace', string='Workspace', ondelete='cascade', index=True,
    )
    role = fields.Char(required=True)
    invited_by_id = fields.Many2one('res.users', string='Invited By')
    # Proof of invitation: auth_signup issues the signup token for this
    # contact and the invitation mail carries it. Only the holder of that
    # token claims the invitation (new account or signed-in account).
    partner_id = fields.Many2one(
        'res.partner', string='Invited Contact', ondelete='cascade', index=True,
    )

    _ORG_ROLES = ('org_manager', 'org_member', 'doc_manager')
    _WS_ROLES = ('ws_manager', 'doc_manager', 'ws_member')
    _SENDER_FIELDS = frozenset({'email', 'organization_id', 'project_id', 'role'})

    @api.constrains('organization_id', 'project_id', 'role')
    def _check_scope_role(self):
        for inv in self:
            if bool(inv.organization_id) == bool(inv.project_id):
                raise ValidationError(_('An invitation targets one organization or one workspace.'))
            allowed = self._ORG_ROLES if inv.organization_id else self._WS_ROLES
            if inv.role not in allowed:
                raise ValidationError(_('Invalid role for this invitation.'))

    @api.model_create_multi
    def create(self, vals_list):
        admin = _is_itlingo_admin(self.env)
        # Client default_* keys would fill the proof fields after the checks.
        self = _strip_default_context(self)
        for vals in vals_list:
            if not admin:
                if set(vals) - self._SENDER_FIELDS:
                    raise AccessError(_('Invitation proof fields are set by the system.'))
                self._check_sender_scope(vals)
            email = email_normalize(vals.get('email') or '')
            if not email:
                raise ValidationError(_('Enter a valid email address.'))
            vals['email'] = email
            if not admin or not vals.get('invited_by_id'):
                vals['invited_by_id'] = self.env.user.id
            if not vals.get('partner_id'):
                vals['partner_id'] = self._invitation_partner(email).id
        return super().create(vals_list)

    @api.model
    def _check_sender_scope(self, vals):
        """Only an accepted manager of the target invites into it. The create
        rule agrees; this check runs before any proof contact is created."""
        if vals.get('organization_id') and not vals.get('project_id'):
            org = self.env['itlingo.organization'].browse(vals['organization_id']).exists()
            if org and org._itlingo_user_role().role == 'org_manager':
                return
        elif vals.get('project_id') and not vals.get('organization_id'):
            workspace = self.env['itlingo.workspace'].browse(vals['project_id']).exists()
            if workspace and workspace._itlingo_user_role().role == 'ws_manager':
                return
        raise AccessError(_('Only managers of the target can invite members.'))

    def write(self, vals):
        if not self.env.su:
            raise AccessError(_('Invitations cannot be changed; send a new one.'))
        return super().write(vals)

    @api.model
    def _invitation_partner(self, email):
        """Contact that receives the signup token for ``email``. All open
        invitations of one address share it, so one proof claims them all.
        A dedicated contact is created: an existing contact with the same
        email could belong to somebody else."""
        other = self.sudo().search([
            ('email', '=', email), ('partner_id', '!=', False),
            ('partner_id.user_ids', '=', False),
        ], limit=1)
        if other:
            return other.partner_id
        return _strip_default_context(self.env['res.partner'].sudo()).create({
            'name': email.split('@')[0],
            'email': email,
        })

    def _scope_url(self):
        self.ensure_one()
        if self.organization_id:
            return f'/my/organizations/{self.organization_id.id}'
        return f'/my/workspaces/{self.project_id.id}'

    def _send_signup_email(self):
        """Mail the proof link: the auth_signup token of the invited contact.
        Every invitation and every resend uses it, also for an address that
        already has an account. Mail and token data are system data (sudo)."""
        company = self.env.company
        for inv in self.sudo():
            if not inv.partner_id or inv.partner_id.user_ids:
                inv.partner_id = self._invitation_partner(inv.email)
            inv.partner_id.signup_prepare()
            token = inv.partner_id._generate_signup_token()
            url = inv.partner_id.get_base_url() + '/itlingo/invitation?' + urlencode({'token': token})
            body = (
                '<div style="font-family: Arial, sans-serif; max-width: 600px;">'
                '<h2>You\'ve been invited to ITLingo Cloud</h2>'
                '<p>Hello,</p>'
                '<p>You have been invited to collaborate on '
                '<strong>ITLingo Cloud</strong>.</p>'
                '<p>Open this personal link to sign in with the account of '
                'this email address, or to create an account. The '
                'invitation is applied only when you confirm it there:</p>'
                '<p style="margin: 24px 0;">'
                f'<a href="{url}" '
                'style="background-color: #714B67; color: white; '
                'padding: 12px 24px; text-decoration: none; '
                'border-radius: 4px; display: inline-block;">'
                'Open Invitation</a></p>'
                '<p style="color: #666; font-size: 12px;">'
                'If the button doesn\'t work, copy and paste this link '
                f'into your browser:<br/>{url}</p>'
                '</div>'
            )
            self.env['mail.mail'].sudo().create({
                'subject': "You've been invited to join ITLingo Cloud",
                'body_html': body,
                'email_to': inv.email,
                'email_from': company.email_formatted or company.email or '',
            }).send()

    @api.model
    def _from_token(self, token):
        """Open invitations proven by ``token``, the native signup token of
        their invited contact. Empty for a bad, expired or used token, and
        for a contact that already has an account (claimed at signup)."""
        partner = None
        if token and isinstance(token, str):
            try:
                partner = self.env['res.partner'].sudo()._get_partner_from_token(token)
            except (ValueError, TypeError, MissingError):
                partner = None
        if not partner or partner.user_ids:
            return self.sudo().browse()
        return self.sudo().search([('partner_id', '=', partner.id)])

    @api.model
    def _account_email(self, user):
        """Normalized mailbox of ``user``: its email, the login only when the
        account has no email."""
        return email_normalize(user.email or user.login or '') or False

    @api.model
    def _proof_matches(self, invitations, user):
        email = self._account_email(user)
        return bool(invitations and email and set(invitations.mapped('email')) == {email})

    @api.model
    def _claim_with_token(self, token, user):
        """Claim for the signed-in ``user`` the invitations of ``token``. The
        token proves the mailbox; the account email must be that mailbox.
        Returns the URL of the first claimed scope, or False."""
        invitations = self._from_token(token)
        if user._is_public() or not self._proof_matches(invitations, user):
            return False
        url = invitations[0]._scope_url()
        self._claim_for_user(user, invitations)
        return url

    @api.model
    def _claim_for_user(self, user, invitations=None):
        """Turn proven invitations into accepted roles of ``user``. Without
        ``invitations``, the proof is the contact of a user created from the
        signup token: a signup that only claims the same email gets a new
        contact and claims nothing.

        A pending or rejected row (also a legacy row that needs mailbox proof)
        gets the invited role; an accepted membership never changes."""
        if invitations is None:
            invitations = self.sudo().search([
                ('partner_id', '=', user.partner_id.id),
            ]) if user.partner_id else self.sudo().browse()
        if not invitations:
            return False
        OrgRole = _strip_default_context(self.env['itlingo.organization.role'].sudo())
        WsRole = _strip_default_context(self.env['itlingo.project.role'].sudo())
        now = fields.Datetime.now()
        for inv in invitations:
            if inv.organization_id:
                Role, scope = OrgRole, {'organization_id': inv.organization_id.id}
            else:
                Role, scope = WsRole, {'project_id': inv.project_id.id}
            row = Role.search([('user_id', '=', user.id)] + [(k, '=', v) for k, v in scope.items()], limit=1)
            if row.state == 'accepted':
                continue
            vals = {'role': inv.role, 'state': 'accepted', 'response_date': now,
                    'mailbox_proof_required': False}
            if row:
                row.write(vals)
            else:
                row = Role.create(dict(vals, user_id=user.id, **scope))
            if inv.project_id:
                row._ensure_org_member(user, inv.project_id)
        partners = invitations.partner_id
        invitations.unlink()
        # One-time proof: the token of the contact stops working.
        partners.signup_cancel()
        return True
