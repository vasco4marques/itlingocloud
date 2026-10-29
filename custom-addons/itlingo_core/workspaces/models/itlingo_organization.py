from odoo import fields, models


class ItlingoOrganization(models.Model):
    _inherit = 'itlingo.organization'

    workspace_ids = fields.One2many(
        'itlingo.workspace', 'organization_id', string='Workspaces',
    )
