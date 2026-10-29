import base64
import hashlib
import json
import logging
import os
import re
from urllib.parse import urlencode

from werkzeug.utils import redirect as wz_redirect

from odoo import fields, http
from odoo.addons.itlingo_dsl.services.grammar_flattener import GrammarFlattenError
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request, Response

_logger = logging.getLogger(__name__)

WRITE_ROLES = ('ws_manager', 'doc_manager')
ADMIN_GROUP = 'itlingo_core.group_itlingo_admin'
_PACKAGE_NAMESPACE_RE = re.compile(
    r'^[ \t]*Package[ \t]+'
    r'([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\b',
    re.MULTILINE,
)


def _json_error(message, status):
    return Response(
        json.dumps({'error': message}),
        status=status, content_type='application/json',
    )


class ITLingoIntegrationAPI(http.Controller):

    # ------------------------------------------------------------------
    # ITOI redirect (replaces Django's generate-itoi-env/<project_id>)
    # ------------------------------------------------------------------

    def _redirect_to_itoi(self, user, project, write, public=False):
        settings = request.env['itlingo.integration.settings'].sudo()._get_settings()
        itoi_url = (settings.itoi_url or 'http://localhost:3000/').rstrip('/')
        iv_b64, ct_b64 = request.env[
            'itlingo.integration.token'
        ]._issue_launch_token(user, project, write, public=public)
        _logger.info(
            'ITOI launch: user=%s project=%s write=%s public=%s',
            user.login, project.id, write, public,
        )
        # Never log the target URL: its query string is the bearer token.
        qs = urlencode({'iv': iv_b64, 't': ct_b64})
        return wz_redirect(f'{itoi_url}/createTempWorkspace?{qs}', code=302)

    @http.route(
        '/itoi/launch/<int:project_id>',
        type='http', auth='user', website=True,
    )
    def itoi_launch(self, project_id, **kw):
        """Launch ITOI for a workspace member or platform admin.

        Write access in ITOI follows the member's accepted workspace role.
        Non-members of a public workspace are sent to the read-only launch.
        """
        project = request.env['itlingo.workspace'].sudo().browse(project_id)
        if not project.exists():
            return request.not_found()

        user = request.env.user
        role = project._itlingo_user_role(user)
        if not role and not user.has_group(ADMIN_GROUP):
            if project.is_public_workspace:
                return request.redirect(f'/itoi/launch/public/{project_id}')
            return request.not_found()
        return self._redirect_to_itoi(user, project, role.role in WRITE_ROLES)

    @http.route(
        '/itoi/launch/public/<int:project_id>',
        type='http', auth='public', website=True,
    )
    def itoi_launch_public(self, project_id, **kw):
        """Read-only ITOI launch of a public workspace.

        The token is public-scoped for every user, members included: it reads
        only the published documents of this workspace.
        """
        project = request.env['itlingo.workspace'].sudo().browse(project_id)
        if not project.exists() or not project.is_public_workspace:
            return request.not_found()
        return self._redirect_to_itoi(
            request.env.user, project, False, public=True)

    # ------------------------------------------------------------------
    # Token helpers (REST API and ITOI document import endpoints)
    # ------------------------------------------------------------------

    def _validate_token_header(self, kind):
        """Validate ``Authorization: Bearer <iv>:<ciphertext>``.

        Returns ``(token, payload, None)`` or ``(None, None, Response)``. The
        principal is ``token.user_id``; it is resolved from the persisted
        authorization, never from the request context or the payload.
        """
        auth_header = request.httprequest.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return None, None, _json_error(
                'Missing or invalid Authorization header', 401)
        parts = auth_header[7:].split(':', 1)
        if len(parts) != 2:
            return None, None, _json_error(
                'Token must be iv:ciphertext (base64url)', 401)
        try:
            token, payload = request.env[
                'itlingo.integration.token'
            ].sudo()._resolve_token(parts[0], parts[1], kind)
        except UserError as e:
            return None, None, _json_error(str(e), 401)
        return token, payload, None

    def _launch_documents(self, token, workspace_id):
        """Return ``(project, documents, None)`` for a launch token.

        *documents* (sudo) are the workspace and organization documents the
        token may read. A public-scoped token reads only the published
        documents of its (still public) workspace, whoever the user is. A
        private token reads what the ``itlingo.document`` access rules allow
        its user; ``_resolve_token`` already rechecked the user's role.
        """
        project = token.project_id
        if project.id != workspace_id:
            return None, None, _json_error('Workspace mismatch', 403)
        Document = request.env['itlingo.document']
        if token.public_scope:
            return project, Document.sudo().search([
                ('project_id', '=', project.id),
                ('status', '=', 'published'),
            ]), None
        org = project.organization_id
        domain = [('project_id', '=', project.id)]
        if org:
            domain = ['|', *domain, ('organization_id', '=', org.id)]
        Document = Document.with_user(token.user_id)
        try:
            Document.check_access('read')
        except AccessError:
            return project, Document.sudo().browse(), None
        return project, Document.search(domain).sudo(), None

    @staticmethod
    def _file_extension(file_name):
        """Return the lowercase extension (without dot) of *file_name*."""
        if not file_name:
            return ''
        return os.path.splitext(file_name)[1].lower().lstrip('.')

    # ------------------------------------------------------------------
    # REST API endpoints
    # ------------------------------------------------------------------

    @http.route('/api/itlingo/v1/whoami', type='http', auth='none',
                methods=['GET'], csrf=False)
    def api_whoami(self, **kw):
        token, payload, error_resp = self._validate_token_header('api')
        if error_resp:
            return error_resp
        return Response(
            json.dumps({
                'user_id': payload.get('user_id'),
                'user_login': payload.get('user_login'),
                'project_id': payload.get('project_id'),
                'expires_at': payload.get('expires_at'),
            }),
            content_type='application/json',
        )

    @http.route('/api/itlingo/v1/projects', type='http', auth='none',
                methods=['GET'], csrf=False)
    def api_projects(self, **kw):
        token, payload, error_resp = self._validate_token_header('api')
        if error_resp:
            return error_resp

        domain = [('workspace_role_ids', 'any', [
            ('user_id', '=', token.user_id.id),
            ('state', '=', 'accepted'),
        ])]
        if token.project_id:
            domain.append(('id', '=', token.project_id.id))
        projects = request.env['itlingo.workspace'].sudo().search(domain)

        data = [{
            'id': p.id,
            'name': p.name,
            'business_status': p.business_status,
        } for p in projects]

        return Response(json.dumps(data), content_type='application/json')

    @http.route('/api/itlingo/v1/token/generate', type='http', auth='user',
                methods=['POST'], csrf=False)
    def api_generate_token(self, **kw):
        """Authenticated endpoint for users to generate their own ITOI token."""
        project_id = kw.get('project_id')
        description = kw.get('description', 'API Token')

        try:
            token_rec = request.env['itlingo.integration.token'].create({
                'user_id': request.uid,
                'project_id': int(project_id) if project_id else False,
                'description': description,
            })
            token_rec.action_generate_token()
        except ValueError:
            return _json_error('Invalid project_id', 400)
        except AccessError as e:
            return _json_error(str(e), 403)

        return Response(
            json.dumps({
                'iv': token_rec.token_iv,
                'token': token_rec.token_ct,
                'expires_at': str(token_rec.expires_at),
            }),
            content_type='application/json',
        )

    # ------------------------------------------------------------------
    # ITOI document import endpoints (token_api)
    # ------------------------------------------------------------------

    @http.route('/token_api/validate-launch', type='http', auth='none',
                methods=['GET'], csrf=False)
    def token_api_validate_launch(self, **kw):
        """Revalidate a forwarded ITOI launch token.

        ITOI calls this before it creates a workspace and before each
        token-authorized write, because decrypting the token proves only
        that ITLingo Cloud issued it, not that it is still valid. The token
        must have a persisted, active, unexpired row and its user must still
        hold the access it was issued for (see ``_resolve_token``).

        200: the original launch payload ``{user, workspace, organization,
        write, wsid}`` plus ``public`` (public-scoped, read-only launch) and
        ``expires_at`` (UTC, ``YYYY-MM-DD HH:MM:SS``).
        401: ``{error}``; ITOI must refuse the operation and ask the user to
        relaunch from ITLingo Cloud.
        """
        # Access is rechecked on every call; never let a cache answer it.
        no_store = [
            ('Cache-Control', 'no-store'),
            ('Vary', 'Authorization'),
        ]
        token, payload, error_resp = self._validate_token_header('launch')
        if error_resp:
            error_resp.headers.extend(no_store)
            return error_resp
        return Response(
            json.dumps({
                'user': payload.get('user'),
                'workspace': payload.get('workspace'),
                'organization': payload.get('organization'),
                'write': token.launch_write,
                'wsid': token.project_id.id,
                'public': token.public_scope,
                'expires_at': fields.Datetime.to_string(token.expires_at),
            }),
            content_type='application/json',
            headers=no_store,
        )

    def _importable_workspace_documents(self, documents):
        """Return the *documents* that are importable (whitelisted
        extension and have file content)."""
        settings = request.env['itlingo.integration.settings'].sudo()._get_settings()
        allowed = settings._get_importable_extensions()

        return documents.filtered(
            lambda d: d.document_file
            and self._file_extension(d.file_name) in allowed
            and not getattr(d, "is_template", False)
        )

    @http.route('/token_api/get-file-list/<int:workspace_id>', type='http',
                auth='none', methods=['GET'], csrf=False)
    def token_api_get_file_list(self, workspace_id, **kw):
        """List the importable cloud documents for a workspace (and its org)."""
        token, payload, error_resp = self._validate_token_header('launch')
        if error_resp:
            return error_resp
        project, documents, error_resp = self._launch_documents(
            token, workspace_id)
        if error_resp:
            return error_resp

        documents = self._importable_workspace_documents(documents)
        namelist = [{
            'id': doc.id,
            'name': doc.file_name,
            'type': self._file_extension(doc.file_name)
            or (doc.document_type_id.name or ''),
            # Display title and origin scope, so ITOI can show the cloud
            # document name separately from the underlying binary filename.
            'title': doc.name,
            'scope': 'workspace' if doc.project_id else 'organization',
        } for doc in documents]

        _logger.info(
            'ITOI get-file-list: workspace=%s user=%s files=%d',
            workspace_id, token.user_id.login, len(namelist),
        )
        return Response(
            json.dumps({'namelist': namelist}),
            content_type='application/json',
        )

    @http.route('/token_api/get-dsl-sources/<int:dsl_id>', type='http',
                auth='none', methods=['GET'], csrf=False)
    def token_api_get_dsl_sources(self, dsl_id, **kw):
        """Return the scoped spec corpus used for cross-file DSL imports.

        This is deliberately narrower than a generic file API: only text from
        documents in the requested DSL family that the launch principal may
        see in the token's workspace/organization is exposed, regardless of
        version pins.
        """
        token, payload, error_resp = self._validate_token_header('launch')
        if error_resp:
            return error_resp
        project, visible, error_resp = self._launch_documents(
            token, token.project_id.id)
        if error_resp:
            return error_resp

        dsl = request.env['itlingo.dsl'].sudo().browse(dsl_id)
        if not dsl.exists() or dsl.status not in (
                'active', 'draft', 'deprecated'):
            return _json_error('DSL not found', 404)
        documents = request.env[
            'itlingo.document'
        ]._scoped_dsl_source_documents(
            dsl,
            project=project,
            organization=project.organization_id,
        ) & visible
        sources = []
        for document in documents:
            raw = base64.b64decode(document.document_file)
            try:
                text = raw.decode('utf-8')
            except UnicodeDecodeError:
                return _json_error(
                    'DSL source %s is not UTF-8'
                    % (document.file_name or document.name), 422)
            sources.append({
                'id': document.id,
                'name': document.file_name or document.name,
                'content': text,
                'digest': hashlib.sha256(raw).hexdigest(),
                'packages': _PACKAGE_NAMESPACE_RE.findall(text),
            })

        package_owners = {}
        for source in sources:
            for package in source['packages']:
                package_owners.setdefault(package, set()).add(source['id'])
        conflicts = sorted(
            package for package, owners in package_owners.items()
            if len(owners) > 1
        )

        _logger.info(
            'ITOI get-dsl-sources: workspace=%s user=%s dsl=%s sources=%d',
            project.id, token.user_id.login, dsl.id, len(sources),
        )
        return Response(
            json.dumps({'sources': sources, 'conflicting_packages': conflicts}),
            content_type='application/json',
        )

    @http.route('/token_api/download-file/<int:workspace_id>/<int:file_id>',
                type='http', auth='none', methods=['GET'], csrf=False)
    def token_api_download_file(self, workspace_id, file_id, **kw):
        """Return the binary content of an importable cloud document."""
        token, payload, error_resp = self._validate_token_header('launch')
        if error_resp:
            return error_resp
        project, visible, error_resp = self._launch_documents(
            token, workspace_id)
        if error_resp:
            return error_resp

        document = request.env['itlingo.document'].sudo().browse(file_id)
        if not document.exists():
            return _json_error('Document not found', 404)

        # The document must be visible to the launch principal in this
        # workspace (or its organization).
        if document not in visible:
            return _json_error(
                'Document does not belong to this workspace', 403)

        settings = request.env['itlingo.integration.settings'].sudo()._get_settings()
        allowed = settings._get_importable_extensions()
        if not document.document_file or \
                self._file_extension(document.file_name) not in allowed:
            return _json_error('File type is not importable', 403)

        content = base64.b64decode(document.document_file)
        _logger.info(
            'ITOI download-file: workspace=%s user=%s file_id=%s name=%s bytes=%d',
            workspace_id, token.user_id.login, file_id,
            document.file_name, len(content),
        )
        return request.make_response(
            content,
            headers=[
                ('Content-Type', 'application/octet-stream'),
                ('Content-Disposition',
                 'attachment; filename="%s"' % (document.file_name or 'document')),
                ('Content-Length', str(len(content))),
            ],
        )

    @staticmethod
    def _visible_dsls(user):
        """DSL versions in the registry that *user* may read.

        Users with registry access read through the ``itlingo.dsl`` record
        rules (drafts only for family maintainers and admins). Principals
        without registry access (the anonymous public user) see the public
        registry: active and deprecated versions of active families.
        """
        Dsl = request.env['itlingo.dsl'].with_user(user)
        try:
            Dsl.check_access('read')
        except AccessError:
            return Dsl.sudo().search([
                ('status', 'in', ['active', 'deprecated']),
                ('family_id.active', '=', True),
            ])
        return Dsl.search([
            ('status', 'in', ['active', 'draft', 'deprecated']),
        ]).sudo()

    @http.route('/token_api/get-dsls', type='http', auth='none',
                methods=['GET'], csrf=False)
    def token_api_get_dsls(self, **kw):
        """List DSLs (with grammar and optional services) for the ITOI LSP.

        Returns the ``active`` and ``draft`` DSLs with a grammar file that the
        launch principal may read in the registry, so maintainers can test
        their unpublished grammars in ITOI while other users only receive
        published ones. A visible ``deprecated`` DSL is included only when its
        family has no visible active or draft version, so a deprecated grammar
        is a fallback rather than a shadow of the current family grammar.
        Authenticated with the same forwarded launch token as
        ``get-file-list`` / ``download-file``.
        """
        token, payload, error_resp = self._validate_token_header('launch')
        if error_resp:
            return error_resp

        dsls = self._visible_dsls(token.user_id)
        current_families = {
            dsl.family_id.id
            for dsl in dsls
            if dsl.status in ('active', 'draft')
        }
        dsls = dsls.filtered(
            lambda dsl: (
                dsl.status != 'deprecated'
                or dsl.family_id.id not in current_families
            )
        )
        result = []
        for dsl in dsls:
            if not dsl._grammar_file():
                continue
            try:
                grammar_text = dsl._flattened_grammar_text()
            except (GrammarFlattenError, ValidationError) as err:
                _logger.warning(
                    'ITOI get-dsls: skipping DSL %s %s '
                    '(grammar cannot be flattened: %s)',
                    dsl.acronym, dsl.version, err,
                )
                continue
            result.append({
                'id': dsl.id,
                'acronym': dsl.acronym,
                'name': dsl.name,
                'version': dsl.version,
                'status': dsl.status,
                'file_extensions': dsl._extensions(),
                'grammar': grammar_text,
                'digest': dsl._grammar_digest(),
                'services': dsl.services_compiled or '',
                'services_digest': dsl.services_compiled_digest or '',
            })

        _logger.info(
            'ITOI get-dsls: user=%s dsls=%d',
            token.user_id.login, len(result),
        )
        return Response(
            json.dumps({'dsls': result}),
            content_type='application/json',
        )
