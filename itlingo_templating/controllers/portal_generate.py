import base64
import logging
import mimetypes
import os

from odoo import _, http
from odoo.exceptions import AccessError, MissingError
from odoo.http import content_disposition, request
from odoo.addons.itlingo_website_portal.controllers.portal import ITLingoPortal

from odoo.addons.itlingo_templating.services import (
    canonical_model, docx_renderer, multi_output, rendering, template_linter,
    text_renderer, xlsx_renderer,
)
from odoo.addons.itlingo_templating.services.dsl_parser import (
    DslParseError,
    dsl_label,
    is_templatable_dsl,
    parse_dsl,
)

_logger = logging.getLogger(__name__)

# extension -> (renderer callable, MIME type)
_FORMATS = {
    "docx": (
        docx_renderer.render_docx,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    "xlsx": (
        xlsx_renderer.render_xlsx,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
    "txt": (text_renderer.render_text, "text/plain; charset=utf-8"),
    "md": (text_renderer.render_text, "text/markdown; charset=utf-8"),
    "rst": (text_renderer.render_text, "text/x-rst; charset=utf-8"),
    "html": (text_renderer.render_text, "text/html; charset=utf-8"),
    "htm": (text_renderer.render_text, "text/html; charset=utf-8"),
    "json": (text_renderer.render_text, "application/json; charset=utf-8"),
    "xml": (text_renderer.render_text, "application/xml; charset=utf-8"),
    "yaml": (text_renderer.render_text, "application/yaml; charset=utf-8"),
    "yml": (text_renderer.render_text, "application/yaml; charset=utf-8"),
    "toml": (text_renderer.render_text, "application/toml; charset=utf-8"),
    "ini": (text_renderer.render_text, "text/plain; charset=utf-8"),
    "cfg": (text_renderer.render_text, "text/plain; charset=utf-8"),
    "properties": (text_renderer.render_text, "text/plain; charset=utf-8"),
    "sql": (text_renderer.render_text, "application/sql; charset=utf-8"),
    "csv": (text_renderer.render_text, "text/csv; charset=utf-8"),
    "tsv": (text_renderer.render_text, "text/tab-separated-values; charset=utf-8"),
    "css": (text_renderer.render_text, "text/css; charset=utf-8"),
    "js": (text_renderer.render_text, "text/javascript; charset=utf-8"),
    "ts": (text_renderer.render_text, "text/plain; charset=utf-8"),
    "sh": (text_renderer.render_text, "text/plain; charset=utf-8"),
}


def _split_extensions(value):
    extensions = []
    for raw in (value or "").split(","):
        ext = raw.strip().lower()
        if not ext:
            continue
        if not ext.startswith("."):
            ext = "." + ext
        extensions.append(ext)
    return extensions


class ItlingoTemplatingPortal(http.Controller):

    @staticmethod
    def _detail_url(base_url, document_id):
        return f"{base_url}/{document_id}"

    def _render_detail(self, document, base_url, project_id=None, org_id=None,
                       error=None, diagnostics=None, lint_result=None,
                       target=None):
        """Render generation feedback in the normal scoped document page."""
        portal = ITLingoPortal()
        values = portal._prepare_portal_layout_values()
        if org_id is not None:
            organization, user_role, scoped_document = (
                portal._portal_org_document_or_404(org_id, document.id)
            )
            if not scoped_document:
                raise MissingError(_("Document not found."))
            values.update({
                "organization": organization,
                "user_role": user_role,
                "organization_hub": True,
                "org_hub_page": "documentation",
                "document_scope": "organization",
                "can_edit_document": (
                    user_role.role in portal._DOC_EDIT_ORG_ROLES
                ),
                "page_name": "organization_document_detail",
            })
        else:
            project, user_role, scoped_document = (
                portal._portal_ws_document_or_404(project_id, document.id)
            )
            if not scoped_document:
                raise MissingError(_("Document not found."))
            values.update({
                "project": project,
                "user_role": user_role,
                "document_scope": "workspace",
                "can_edit_document": (
                    user_role.role in portal._DOC_EDIT_WS_ROLES
                ),
                "page_name": "workspace_document_detail",
                **portal._portal_workspace_hub_common(
                    project, "documentation", public_hub=False,
                ),
            })
        target = target or scoped_document._templating_generation_dsl()
        values.update({
            "document": scoped_document,
            "doc_base_url": base_url,
            "doc_message": None,
            "doc_error": None,
            "generation_error": error,
            "generation_diagnostics": diagnostics or [],
            "template_lint_result": lint_result,
            **self._generation_values(scoped_document, target),
        })
        return request.render("itlingo_documents.portal_document_detail", values)

    def _get_template_document(self, document_id):
        """Return a readable template document or raise."""
        document = request.env["itlingo.document"].browse(document_id)
        if not document.exists():
            raise MissingError(_("Document not found."))
        try:
            document.check_access("read")
        except AccessError:
            raise AccessError(_("You do not have access to this document."))
        if not document.is_template:
            raise MissingError(_("This document is not a template."))
        return document

    @staticmethod
    def _template_format(document):
        content = base64.b64decode(document.document_file or b"")
        return rendering.template_format(document.file_name, content)

    @staticmethod
    def _source_extensions(dsl):
        return _split_extensions(dsl.file_extensions) or [".dsl"]

    def _resolve_generation_target(self, document, posted_id=None):
        context = document._templating_generation_context()
        family = document.dsl_family_id
        if not family:
            return request.env["itlingo.dsl"].browse(), _(
                "This template is not associated with a DSL family."
            )
        active = context["generation_active_target"]
        target = active
        if posted_id:
            try:
                target_id = int(posted_id)
            except (TypeError, ValueError):
                target_id = 0
            target = request.env["itlingo.dsl"].sudo().browse(target_id)
            if (
                target.exists()
                and target.family_id == family
                and target.status == "deprecated"
            ):
                return target, _(
                    "The active DSL version changed. Refresh the page and try again."
                )
            if (
                not target.exists()
                or target.family_id != family
                or target.status not in ("active", "draft")
            ):
                return target, _(
                    "The selected DSL version is no longer available for this "
                    "template family. Refresh the page and try again."
                )
            if target.status == "draft" and target.id not in context[
                "generation_target_choices"
            ].ids:
                return target, _("Draft DSL versions are not available to you.")
            if target.status == "active" and target.id != active.id:
                return target, _(
                    "The active DSL version changed. Refresh the page and try again."
                )
        if not target:
            return target, _(
                "This template family has no active DSL version. "
                "Ask a platform administrator to publish one."
            )
        return target, None
    def _generation_values(self, document, target):
        return document.with_user(request.env.user)._templating_generation_context(
            target,
        )
    @staticmethod
    def _build_context(dsl, ast):
        model = canonical_model.build_generic_model(
            ast, dsl._templating_profile(),
        )
        model["dsl"] = dsl.acronym or ""
        return model

    @http.route(
        "/my/workspaces/<int:project_id>/documents/<int:document_id>/generate",
        type="http", auth="user", website=True, methods=["GET", "POST"],
    )
    def portal_generate_workspace(self, project_id, document_id, **post):
        base_url = f"/my/workspaces/{project_id}/documents"
        return self._portal_generate(
            document_id, base_url, project_id=project_id, **post,
        )

    @http.route(
        "/my/organizations/<int:org_id>/documents/<int:document_id>/generate",
        type="http", auth="user", website=True, methods=["GET", "POST"],
    )
    def portal_generate_organization(self, org_id, document_id, **post):
        base_url = f"/my/organizations/{org_id}/documents"
        return self._portal_generate(
            document_id, base_url, org_id=org_id, **post,
        )

    @http.route(
        "/my/workspaces/<int:project_id>/documents/<int:document_id>/check",
        type="http", auth="user", website=True, methods=["POST"],
    )
    def portal_check_workspace(self, project_id, document_id, **post):
        return self._portal_check(
            document_id, f"/my/workspaces/{project_id}/documents",
            project_id=project_id, **post,
        )

    @http.route(
        "/my/organizations/<int:org_id>/documents/<int:document_id>/check",
        type="http", auth="user", website=True, methods=["POST"],
    )
    def portal_check_organization(self, org_id, document_id, **post):
        return self._portal_check(
            document_id, f"/my/organizations/{org_id}/documents",
            org_id=org_id, **post,
        )

    def _portal_check(self, document_id, base_url, project_id=None, org_id=None,
                      **post):
        document = self._get_template_document(document_id)
        if project_id is not None and document.project_id.id != project_id:
            raise MissingError(_("Document not found."))
        if org_id is not None and document.organization_id.id != org_id:
            raise MissingError(_("Document not found."))
        target, target_error = self._resolve_generation_target(
            document, post.get("target_dsl_id") or post.get("dsl_version_id")
        )
        if target_error:
            return self._render_detail(
                document, base_url, project_id=project_id, org_id=org_id,
                error=target_error, target=target,
            )
        if not is_templatable_dsl(request.env, target):
            return self._render_detail(
                document, base_url, project_id=project_id, org_id=org_id,
                error=_("This DSL version is not ready for template checking."),
                target=target,
            )
        fmt = self._template_format(document)
        if not fmt or not document.document_file:
            return self._render_detail(
                document, base_url, project_id=project_id, org_id=org_id,
                error=_("Only supported template files with an attached file can be checked."),
                target=target,
            )
        try:
            result = template_linter.lint_template(
                base64.b64decode(document.document_file), fmt,
                target._template_reference_context(),
            )
        except (ImportError, UnicodeDecodeError) as err:
            result = {
                "skipped": True, "degraded": False, "findings": [],
                "message": str(err),
            }
        except Exception as err:
            _logger.exception("Template check failed for document %s", document.id)
            result = {
                "skipped": True, "degraded": False, "findings": [],
                "message": _("Template checking failed: %s") % err,
            }
        return self._render_detail(
            document, base_url, project_id=project_id, org_id=org_id,
            lint_result=result, target=target,
        )

    def _portal_generate(self, document_id, base_url, project_id=None,
                         org_id=None, **post):
        document = self._get_template_document(document_id)
        if project_id is not None and document.project_id.id != project_id:
            raise MissingError(_("Document not found."))
        if org_id is not None and document.organization_id.id != org_id:
            raise MissingError(_("Document not found."))
        fmt = self._template_format(document)
        if not fmt or not document.document_file:
            return self._render_detail(
                document, base_url, project_id=project_id, org_id=org_id,
                error=_(
                    "Only supported template files with an attached file can be generated."
                ),
            )

        target, target_error = self._resolve_generation_target(
            document,
            post.get("target_dsl_id") or post.get("dsl_version_id"),
        )
        if target_error:
            return self._render_detail(
                document, base_url, project_id=project_id, org_id=org_id,
                error=target_error, target=target,
            )
        if not is_templatable_dsl(request.env, target):
            return self._render_detail(
                document, base_url, project_id=project_id, org_id=org_id,
                error=_(
                    "This DSL version does not have a current, valid grammar "
                    "and compiled services module."
                ),
                target=target,
            )

        source_extensions = self._source_extensions(target)

        if request.httprequest.method != "POST":
            return request.redirect(self._detail_url(base_url, document.id) + "#generate")


        upload = request.httprequest.files.get("source_file")
        if not upload or not upload.filename:
            return self._render_detail(
                document, base_url, project_id=project_id, org_id=org_id,
                error=_("Please upload a %s file.") % dsl_label(target),
                target=target,
            )
        filename_lower = upload.filename.lower()
        if source_extensions and not any(
            filename_lower.endswith(ext) for ext in source_extensions
        ):
            return self._render_detail(
                document, base_url, project_id=project_id, org_id=org_id,
                error=_("Please upload a %s file (%s).") % (
                    dsl_label(target),
                    ", ".join(source_extensions),
                ),
                target=target,
            )

        source_bytes = upload.read()
        try:
            ast = parse_dsl(
                request.env,
                target,
                source_bytes,
                scope_document=document,
                source_name=upload.filename,
            )
        except DslParseError as err:
            return self._render_detail(
                document, base_url, project_id=project_id, org_id=org_id,
                error=str(err), diagnostics=err.diagnostics, target=target,
            )
        except RuntimeError as err:
            _logger.exception(
                "%s parsing failed for document %s",
                target.acronym or "DSL", document.id,
            )
            return self._render_detail(
                document, base_url, project_id=project_id, org_id=org_id,
                error=str(err), target=target,
            )

        try:
            context = self._build_context(target, ast)
        except Exception as err:
            _logger.exception(
                "%s context building failed for document %s",
                target.acronym or "DSL", document.id,
            )
            return self._render_detail(
                document, base_url, project_id=project_id, org_id=org_id,
                error=_(
                    "The generation context could not be built from the "
                    "parsed specification: %s"
                ) % err,
                target=target,
            )

        # Extra variables available only to output filenames.
        template_name = os.path.splitext(document.file_name or document.name or "template")[0]
        spec_name = os.path.splitext(upload.filename or "spec")[0]
        filename_context = dict(
            context, template_name=template_name, spec_name=spec_name,
        )
        fallback = document.name or "generated"

        renderer, mime = _FORMATS.get(fmt, (
            text_renderer.render_text,
            "%s; charset=utf-8" % (
                mimetypes.guess_type(document.file_name or "")[0] or "text/plain"
            ),
        ))
        try:
            template_bytes = base64.b64decode(document.document_file)
            outputs = None if fmt in ("docx", "xlsx") else (
                multi_output.render_outputs(template_bytes, filename_context)
            )
            if outputs is not None:
                archive = multi_output.build_zip(outputs)
                archive_name = rendering.render_filename(
                    document.output_filename_pattern, filename_context,
                    fallback, extension=".zip",
                )
                return request.make_response(archive, headers=[
                    ("Content-Type", "application/zip"),
                    ("Content-Disposition", content_disposition(archive_name)),
                    ("Content-Length", str(len(archive))),
                ])
            output = renderer(template_bytes, context)
        except UnicodeDecodeError:
            return self._render_detail(
                document, base_url, project_id=project_id, org_id=org_id,
                error=_("Text template files must be encoded as UTF-8."),
                target=target,
            )
        except ImportError:
            return self._render_detail(
                document, base_url, project_id=project_id, org_id=org_id,
                error=_(
                    "The Python package required to render %s files is not "
                    "installed on the server." % fmt.upper()
                ),
                target=target,
            )
        except Exception as err:
            _logger.exception("%s rendering failed for document %s", fmt, document.id)
            return self._render_detail(
                document, base_url, project_id=project_id, org_id=org_id,
                error=_("Document generation failed: %s") % err,
                target=target,
            )

        filename = rendering.render_filename(
            document.output_filename_pattern, filename_context, fallback,
            extension="." + fmt,
        )
        return request.make_response(output, headers=[
            ("Content-Type", mime),
            ("Content-Disposition", content_disposition(filename)),
            ("Content-Length", str(len(output))),
        ])
