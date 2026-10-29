"""Resync the DSL maintainer group, which now carries the authoring ACLs."""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["itlingo.dsl"]._sync_maintainer_group()
