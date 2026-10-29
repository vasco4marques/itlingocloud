import json
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

# Issued by the server only: clients may neither supply nor change them.
_SERVER_FIELDS = frozenset({
    'token_iv', 'token_ct', 'expires_at', 'token_kind',
    'public_scope', 'launch_write',
})
_SCOPE_FIELDS = frozenset({'user_id', 'project_id'})
ADMIN_GROUP = 'itlingo_core.group_itlingo_admin'
WRITE_ROLES = ('ws_manager', 'doc_manager')


class ItlingoIntegrationToken(models.Model):
    """Persisted authorization behind every encrypted ITOI token.

    ``api`` rows back the REST bearer tokens a user generates for themselves.
    ``launch`` rows back the ``/createTempWorkspace`` launch payload that ITOI
    forwards to ``/token_api/*``. A token is valid only while its row exists,
    is active, is not expired, and its user still holds the access it was
    issued for; the ciphertext alone grants nothing.
    """
    _name = 'itlingo.integration.token'
    _description = 'ITLingo ITOI Token'
    _order = 'create_date desc'

    user_id = fields.Many2one(
        'res.users', string='User', required=True,
        default=lambda self: self.env.user, ondelete='cascade',
    )
    project_id = fields.Many2one(
        'itlingo.workspace', string='Workspace', ondelete='cascade',
    )
    token_kind = fields.Selection(
        [('api', 'API'), ('launch', 'ITOI launch')],
        string='Kind', default='api', required=True, readonly=True,
    )
    public_scope = fields.Boolean(
        string='Public launch', readonly=True,
        help='Issued by the public ITOI launch: it reads only the published '
             'documents of a public workspace, whoever the user is.',
    )
    launch_write = fields.Boolean(
        string='Launch write access', readonly=True,
        help='Write access granted in the launch payload.',
    )
    token_iv = fields.Char(string='Token IV (base64url)', readonly=True)
    token_ct = fields.Text(string='Token Ciphertext (base64url)', readonly=True)
    expires_at = fields.Datetime(string='Expires At', readonly=True)
    is_active = fields.Boolean(default=True)
    description = fields.Char()

    # ------------------------------------------------------------------
    # Ownership / scope guards
    # ------------------------------------------------------------------

    def _is_platform_admin(self, user=None):
        return (user or self.env.user).has_group(ADMIN_GROUP)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            ctx = self.env.context
            if any('default_' + name in ctx for name in _SERVER_FIELDS):
                raise AccessError(_(
                    "Token ciphertext, kind and expiry are issued by "
                    "the server."))
            admin = self._is_platform_admin()
            for vals in vals_list:
                if _SERVER_FIELDS & set(vals):
                    raise AccessError(_(
                        "Token ciphertext, kind and expiry are issued by "
                        "the server."))
                # Effective values as the ORM resolves them: explicit
                # values, then ``default_*`` context, then field defaults.
                user_id = vals['user_id'] if 'user_id' in vals else ctx.get(
                    'default_user_id', self.env.uid)
                project_id = vals['project_id'] if 'project_id' in vals \
                    else ctx.get('default_project_id')
                try:
                    user_id = int(user_id or 0)
                    project_id = int(project_id or 0)
                except (TypeError, ValueError):
                    raise AccessError(_("Invalid token user or workspace."))
                user = self.env['res.users'].browse(user_id or [])
                if user != self.env.user and not admin:
                    raise AccessError(_(
                        "You can only create tokens for yourself."))
                project = self.env['itlingo.workspace'].sudo().browse(
                    project_id or [])
                if project and not (
                        admin or project._itlingo_user_role(user)):
                    raise AccessError(_(
                        "You do not have access to this workspace."))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            if (_SERVER_FIELDS | _SCOPE_FIELDS) & set(vals):
                raise AccessError(_(
                    "Token scope, ciphertext and expiry cannot be changed. "
                    "Create a new token instead."))
            if vals.get('is_active'):
                raise AccessError(_(
                    "A revoked token cannot be reactivated. Create a new "
                    "token instead."))
        return super().write(vals)

    # ------------------------------------------------------------------
    # Issuing
    # ------------------------------------------------------------------

    def _expires_at(self, settings):
        return fields.Datetime.now() + timedelta(
            hours=settings.token_expiry_hours or 24)

    def action_generate_token(self):
        """Issue (or rotate) the ciphertext of the caller's own API token."""
        self.ensure_one()
        self.check_access('write')
        if self.token_kind != 'api':
            raise UserError(_("Launch tokens are issued by ITOI launch only."))
        if not self.is_active:
            raise UserError(_(
                "A revoked token cannot be regenerated. Create a new token "
                "instead."))
        if self.project_id and not (
                self._is_platform_admin(self.user_id)
                or self.project_id._itlingo_user_role(self.user_id)):
            raise AccessError(_("You do not have access to this workspace."))
        settings = self.env['itlingo.integration.settings']._get_settings()
        expires_at = self._expires_at(settings)

        payload = json.dumps({
            'user_id': self.user_id.id,
            'user_login': self.user_id.login,
            'project_id': self.project_id.id if self.project_id else None,
            'expires_at': fields.Datetime.to_string(expires_at),
        })

        iv_b64, ct_b64 = settings._aes_encrypt(payload)
        self.sudo().write({
            'token_iv': iv_b64,
            'token_ct': ct_b64,
            'expires_at': expires_at,
        })
        return True

    def action_revoke(self):
        self.check_access('write')
        self.write({'is_active': False})

    @api.model
    def _issue_launch_token(self, user, project, write, public=False):
        """Encrypt and persist an ITOI launch payload for *user*/*project*.

        The caller must already have authorized the launch. *public* marks a
        public-workspace launch (read-only, published workspace documents
        only). The wire payload is unchanged:
        ``{user, workspace, organization, write, wsid}``.
        """
        write = bool(write) and not public
        settings = self.env['itlingo.integration.settings'].sudo()._get_settings()
        payload = json.dumps({
            'user': user.login,
            'workspace': project.name,
            'organization': project.organization_id.name or '',
            'write': write,
            'wsid': project.id,
        })
        iv_b64, ct_b64 = settings._aes_encrypt(payload)
        self.sudo().create({
            'user_id': user.id,
            'project_id': project.id,
            'token_kind': 'launch',
            'public_scope': bool(public),
            'launch_write': write,
            'token_iv': iv_b64,
            'token_ct': ct_b64,
            'expires_at': self._expires_at(settings),
            'description': 'ITOI public launch' if public else 'ITOI launch',
        })
        return iv_b64, ct_b64

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @api.model
    def _resolve_token(self, iv_b64, ct_b64, kind):
        """Return ``(token_record, payload)`` for a valid token or raise.

        The principal is ``token_record.user_id``; the payload is returned
        unchanged for wire compatibility, but it must agree with the row.
        """
        settings = self.env['itlingo.integration.settings'].sudo()._get_settings()
        try:
            payload = json.loads(settings._aes_decrypt(iv_b64, ct_b64))
        except Exception:
            raise UserError(_("Invalid token."))
        if not isinstance(payload, dict):
            raise UserError(_("Invalid token."))

        token = self.sudo().search([
            ('token_iv', '=', iv_b64),
            ('token_ct', '=', ct_b64),
            ('token_kind', '=', kind),
        ], limit=1)
        if not token:
            if kind == 'launch':
                raise UserError(_(
                    "Launch token is not recognised. Relaunch ITOI from "
                    "ITLingo Cloud."))
            raise UserError(_("Token has been revoked."))
        if not token.is_active:
            raise UserError(_("Token has been revoked."))
        if not token.expires_at or token.expires_at < fields.Datetime.now():
            token.is_active = False
            raise UserError(_("Token has expired."))

        user = token.user_id
        if kind == 'launch':
            matches = (
                payload.get('user') == user.login
                and payload.get('wsid') == token.project_id.id
                and payload.get('write') is token.launch_write
            )
        else:
            matches = (
                payload.get('user_id') == user.id
                and payload.get('project_id') == (token.project_id.id or None)
            )
        if not matches:
            raise UserError(_("Invalid token."))
        # The public user is inactive by design; it is only ever the
        # principal of a public-workspace launch.
        if not user.active and not (token.public_scope and user._is_public()):
            raise UserError(_("Token user is inactive."))
        project = token.project_id
        if token.public_scope:
            if not project.is_public_workspace:
                raise UserError(_(
                    "This workspace is no longer public. Relaunch ITOI from "
                    "ITLingo Cloud."))
            return token, payload
        if not project:
            return token, payload
        admin = self._is_platform_admin(user)
        role = project._itlingo_user_role(user)
        if not (admin or role):
            raise UserError(_("You no longer have access to this workspace."))
        # A private launch keeps at most the write access the user holds now.
        if token.launch_write and not (role and role.role in WRITE_ROLES):
            raise UserError(_(
                "Your workspace access changed. Relaunch ITOI from "
                "ITLingo Cloud."))
        return token, payload

    @api.model
    def _validate_token(self, iv_b64, ct_b64):
        """Validate a REST API token. Returns the payload dict or raises."""
        return self._resolve_token(iv_b64, ct_b64, 'api')[1]

    @api.autovacuum
    def _gc_expired_launch_tokens(self):
        """Delete expired launch rows; a relaunch issues a new one.

        Every launch (also anonymous public ones) stores a row, so expired
        rows would otherwise accumulate. API tokens are kept as the user's
        own history.
        """
        self.sudo().search([
            ('token_kind', '=', 'launch'),
            ('expires_at', '<', fields.Datetime.now()),
        ]).unlink()
