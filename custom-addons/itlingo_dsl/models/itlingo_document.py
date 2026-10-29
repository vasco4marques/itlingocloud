from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ItlingoDocument(models.Model):
    _inherit = 'itlingo.document'

    dsl_family_id = fields.Many2one(
        'itlingo.dsl.family', string='DSL Family', tracking=True,
        help='Stable ITLingo DSL family this document relates to (if any).',
    )
    dsl_version_id = fields.Many2one(
        'itlingo.dsl', string='DSL Version', tracking=True,
        help='Optional ITLingo DSL version provenance for this document.',
    )

    @api.onchange('dsl_family_id')
    def _onchange_dsl_family_id(self):
        for document in self:
            if (
                document.dsl_version_id
                and document.dsl_version_id.family_id != document.dsl_family_id
            ):
                document.dsl_version_id = False

    @api.constrains('dsl_family_id', 'dsl_version_id')
    def _check_dsl_family_version(self):
        for document in self:
            if document.dsl_version_id and not document.dsl_family_id:
                raise ValidationError(_(
                    'A DSL version requires a DSL family.',
                ))
            if (
                document.dsl_version_id
                and document.dsl_version_id.family_id != document.dsl_family_id
            ):
                raise ValidationError(_(
                    'The selected DSL version must belong to the selected family.',
                ))

    @api.model
    def _extra_text_extensions(self):
        """Registered DSL file extensions are text-like documents."""
        return super()._extra_text_extensions() | frozenset(
            self.env['itlingo.dsl']._all_extensions()
        )

    @api.model
    def _scoped_dsl_source_documents(
        self, dsl, project=None, organization=None,
    ):
        """Return the trusted same-family specification corpus.

        Scope is applied before ``sudo`` results are returned. A version
        argument is accepted for existing callers, but its pinned version is
        deliberately ignored when resolving imports.
        """
        if not dsl or (not project and not organization):
            return self.browse()
        family = (
            dsl.family_id
            if getattr(dsl, '_name', None) == 'itlingo.dsl'
            else dsl
        )
        if not family:
            return self.browse()
        scope = []
        if project:
            scope.append(('project_id', '=', project.id))
            organization = organization or project.organization_id
        if organization:
            scope.append(('organization_id', '=', organization.id))
        domain = [
            ('dsl_family_id', '=', family.id),
            ('document_file', '!=', False),
        ]
        if len(scope) == 1:
            domain += scope
        elif len(scope) > 1:
            domain += ['|', *scope]
        documents = self.sudo().search(domain, order='id')
        # ``is_template`` is supplied by itlingo_templating, so keep the base
        # document model independent from that optional extension.
        if 'is_template' in self._fields:
            documents = documents.filtered(lambda document: not document.is_template)
        return documents
