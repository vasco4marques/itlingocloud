from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ItlingoDslFamily(models.Model):
    _name = "itlingo.dsl.family"
    _description = "ITLingo Domain-Specific Language Family"
    _order = "acronym asc"

    name = fields.Char(string="Name", required=True)
    acronym = fields.Char(string="Acronym", required=True)
    maintainer_ids = fields.Many2many(
        "res.users",
        string="Maintainers",
        help="Users responsible for this DSL family and its versions.",
    )

    dsl_ids = fields.One2many(
        "itlingo.dsl",
        "family_id",
        string="Versions",
    )
    active = fields.Boolean(string="Active", default=True)

    _unique_acronym = models.Constraint(
        "unique(acronym)",
        "A DSL family with this acronym already exists.",
    )

    @api.constrains("acronym")
    def _check_normalized_acronym(self):
        for family in self:
            acronym = (family.acronym or "").strip()
            if not acronym:
                raise ValidationError(_("A DSL family requires an acronym."))
            duplicate = self.search([("id", "!=", family.id)]).filtered(
                lambda item: (item.acronym or "").strip().casefold()
                == acronym.casefold()
            )[:1]
            if duplicate:
                raise ValidationError(_(
                    "A DSL family with acronym '%s' already exists.", acronym,
                ))

    @api.model
    def _find_or_create_for_version(self, vals):
        acronym = (vals.get("acronym") or "").strip()
        name = (vals.get("name") or "").strip()
        if not acronym or not name:
            raise ValidationError(_(
                "A DSL version without a family requires both a name and an acronym."
            ))
        family = self.sudo().search([]).filtered(
            lambda item: (item.acronym or "").strip().casefold()
            == acronym.casefold()
        )[:1]
        if family:
            return family
        return self.create({"name": name, "acronym": acronym})

    def _sync_maintainer_group(self):
        dsl_model = self.env.get("itlingo.dsl")
        if dsl_model is not None:
            dsl_model._sync_maintainer_group()

    @api.model_create_multi
    def create(self, vals_list):
        families = super().create(vals_list)
        families._sync_maintainer_group()
        return families
    def write(self, vals):
        result = super().write(vals)
        if "maintainer_ids" in vals:
            self._sync_maintainer_group()
        if "active" in vals:
            self.dsl_ids._sync_kb_files()
        return result

    def unlink(self):
        result = super().unlink()
        self._sync_maintainer_group()
        return result
