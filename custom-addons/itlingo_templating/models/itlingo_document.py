import base64


from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from odoo.addons.itlingo_templating.services.dsl_parser import (
    dsl_label,
    is_templatable_dsl,
)
from odoo.addons.itlingo_templating.services.rendering import template_format

TEMPLATE_TYPE_CODE = "template"

class ItlingoDocument(models.Model):
    _inherit = "itlingo.document"

    def _templating_generation_dsl(self):
        """Return the family target used by template authoring metadata."""
        self.ensure_one()
        family = self.dsl_family_id.sudo()
        if not family:
            return self.env["itlingo.dsl"].browse()
        return self.env["itlingo.dsl"].search([
            ("family_id", "=", family.id),
            ("status", "=", "active"),
        ], order="id", limit=1)
    def _templating_generation_context(self, target=None):
        """Build the authorized generation target context for portal pages."""
        self.ensure_one()
        empty = self.env["itlingo.dsl"].browse()
        family = self.dsl_family_id.sudo()
        if not family or not family.active:
            target = empty
            choices = empty
            active = empty
            can_select = False
        else:
            Dsl = self.env["itlingo.dsl"].sudo()
            active = Dsl.search([
                ("family_id", "=", family.id),
                ("status", "=", "active"),
            ], order="id", limit=1)
            can_select = (
                self.env.user.has_group(
                    "itlingo_organizations.group_itlingo_admin",
                )
                or self.env.user.id in family.sudo().maintainer_ids.ids
            )
            choices = active
            if can_select:
                choices |= Dsl.search([
                    ("family_id", "=", family.id),
                    ("status", "=", "draft"),
                ], order="version desc, id")
            target = target or active
            if (
                not target
                or target.family_id != family
                or target.status not in ("active", "draft")
                or target.id not in choices.ids
            ):
                target = active
        authored_version = self.dsl_version_id.sudo()
        states = dict(
            self.env["itlingo.dsl"]._fields["status"].selection,
        )
        extensions = []
        for raw_extension in (target.file_extensions or "").split(","):
            extension = raw_extension.strip().lower()
            if extension and not extension.startswith("."):
                extension = "." + extension
            if extension:
                extensions.append(extension)
        if target and not extensions:
            extensions = [".%s" % extension for extension in target._extensions()]
        return {
            "generation_active_target": active,
            "generation_target": target,
            "generation_target_choices": choices,
            "generation_target_can_select": can_select,
            "generation_target_label": (
                "%s - %s" % (
                    target.version or "",
                    states.get(target.status, target.status),
                )
                if target else "No active version"
            ),
            "generation_target_supported": is_templatable_dsl(
                self.env, target,
            ),
            "generation_source_label": (
                dsl_label(target) if target else "DSL specification"
            ),
            "generation_source_accept": ",".join(extensions),
            "generation_variable_groups": (
                target._templating_variable_groups() if target else {}
            ),
            "generation_authored_version_label": (
                authored_version.version
                if authored_version and (
                    not target or authored_version != target
                )
                else False
            ),
        }


    is_template = fields.Boolean(
        string="Is Template",
        compute="_compute_is_template",
        store=True,
        help="Derived from the document type: a document is a template when its "
             "type is 'Template'. Templates are excluded from the "
             "knowledge pool and cannot be sent to ITOI.",
    )
    output_filename_pattern = fields.Char(
        string="Output Filename Pattern",
        help="Jinja2 pattern for the download name. Available variables: "
             "template_name (this template's name) and spec_name (uploaded "
             "specification name). DSL-specific template fields may also be "
             "used. Example: {{ spec_name }}_{{ template_name }}. Do not add "
             "an extension: generation appends the attached template's own "
             "extension, or .zip for a multi-output text template, whose "
             "member names come from its {# output: ... #} headers. "
             "Defaults to the template name.",
    )
    template_format_supported = fields.Boolean(
        string="Template Format Supported",
        compute="_compute_template_format_supported",
    )

    @api.depends("document_type_id", "document_type_id.type_code")
    def _compute_is_template(self):
        for doc in self:
            doc.is_template = doc.document_type_id.type_code == TEMPLATE_TYPE_CODE


    def _uploaded_template_format(self):
        self.ensure_one()
        content = base64.b64decode(self.document_file or b"")
        return template_format(self.file_name, content)

    @api.depends("file_name", "document_file")
    def _compute_template_format_supported(self):
        for doc in self:
            doc.template_format_supported = bool(
                doc.document_file and doc._uploaded_template_format()
            )


    @api.constrains(
        "document_type_id", "dsl_knowledge", "dsl_family_id",
        "dsl_version_id", "document_file", "file_name",
    )
    def _check_template_not_knowledge(self):
        for doc in self:
            if doc.is_template and not doc.dsl_family_id:
                raise ValidationError(_(
                    "A template must be associated with a DSL family "
                    "(document: %s).", doc.name,
                ))
            if (
                doc.is_template
                and doc.document_file
                and not doc._uploaded_template_format()
            ):
                raise ValidationError(_(
                    "Templates must be DOCX, XLSX, or UTF-8 text files "
                    "(document: %s).", doc.name,
                ))
            if doc.is_template and doc.dsl_knowledge:
                raise ValidationError(_(
                    "A template cannot be part of the knowledge pool "
                    "(document: %s).", doc.name,
                ))

    def _vals_make_template(self, vals):
        """True when *vals* set a document type whose code is 'template'."""
        dt_id = vals.get("document_type_id")
        if not dt_id:
            return False
        dt = self.env["itlingo.document.type"].browse(dt_id)
        return dt.type_code == TEMPLATE_TYPE_CODE

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if self._vals_make_template(vals):
                vals["dsl_knowledge"] = False
        return super().create(vals_list)

    def write(self, vals):
        if "document_type_id" in vals and self._vals_make_template(vals):
            vals = dict(vals, dsl_knowledge=False)
        return super().write(vals)
