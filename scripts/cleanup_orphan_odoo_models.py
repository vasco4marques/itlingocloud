"""Remove metadata left by the retired itlingo_agile/itlingo_reports modules.

Run through Odoo shell:

    ../venv/bin/python odoo/odoo-bin shell \
      -c config/odoo.config -d itlingo_dev --no-http \
      < scripts/cleanup_orphan_odoo_models.py

The default is a rollback-only preview. Set
``ITLINGO_ORPHAN_CLEANUP_APPLY=1`` to commit the cleanup.

Production (run from /opt/odoo on the Docker host):

    sudo docker exec -i itlingo-odoo \
      odoo shell -c /etc/odoo/odoo.conf -d itlingo_cloud --no-http \
      < scripts/cleanup_orphan_odoo_models.py

After reviewing the dry-run counts, apply with:

    sudo docker exec -e ITLINGO_ORPHAN_CLEANUP_APPLY=1 -i itlingo-odoo \
      odoo shell -c /etc/odoo/odoo.conf -d itlingo_cloud --no-http \
      < scripts/cleanup_orphan_odoo_models.py
"""

import os


TARGET_MODULES = ("itlingo_agile", "itlingo_reports")
TARGET_MODELS = (
    "itlingo.sprint",
    "itlingo.sprint.user",
    "itlingo.backlog.item",
    "itlingo.task.day.effort",
    "itlingo.sprint.plan.backlog",
    "itlingo.burndown.report",
    "itlingo.velocity.report",
    "itlingo.backlog.export.wizard",
    "itlingo.backlog.import.wizard",
)
APPLY = os.getenv("ITLINGO_ORPHAN_CLEANUP_APPLY", "").strip() == "1"


def xmlid_records(model_name):
    ids = env["ir.model.data"].search([
        ("module", "in", TARGET_MODULES),
        ("model", "=", model_name),
    ]).mapped("res_id")
    return env[model_name].browse(ids).exists()


orphan_models = env["ir.model"].search([
    ("model", "in", TARGET_MODELS),
])
orphan_model_ids = orphan_models.ids

window_actions = (
    env["ir.actions.act_window"].search([
        ("res_model", "in", TARGET_MODELS),
    ])
    | xmlid_records("ir.actions.act_window")
)
action_references = [
    "ir.actions.act_window,%s" % action_id
    for action_id in window_actions.ids
]
menus = xmlid_records("ir.ui.menu")
if action_references:
    menus |= env["ir.ui.menu"].search([
        ("action", "in", action_references),
    ])

views = (
    env["ir.ui.view"].search([("model", "in", TARGET_MODELS)])
    | xmlid_records("ir.ui.view")
)
accesses = env["ir.model.access"].search([
    ("model_id", "in", orphan_model_ids),
])
rules = env["ir.rule"].search([
    ("model_id", "in", orphan_model_ids),
])
server_actions = env["ir.actions.server"].search([
    ("model_id", "in", orphan_model_ids),
])
module_xmlids = env["ir.model.data"].search([
    ("module", "in", TARGET_MODULES),
])

counts = {
    "models": len(orphan_models),
    "model_access": len(accesses),
    "rules": len(rules),
    "views": len(views),
    "window_actions": len(window_actions),
    "server_actions": len(server_actions),
    "menus": len(menus),
    "xmlids": len(module_xmlids),
}
print("Orphan metadata cleanup (%s)" % ("APPLY" if APPLY else "DRY RUN"))
for label, count in counts.items():
    print("  %-16s %s" % (label + ":", count))

if APPLY:
    # Remove consumers before model metadata. _force_unlink is Odoo's module
    # uninstall context and safely clears non-manual ir.model fields.
    menus.unlink()
    server_actions.unlink()
    window_actions.unlink()
    views.unlink()
    rules.unlink()
    accesses.unlink()
    orphan_models.with_context(_force_unlink=True).unlink()
    module_xmlids.exists().unlink()
    env.cr.commit()
    print("Cleanup committed.")
else:
    env.cr.rollback()
    print("Dry run rolled back. Set ITLINGO_ORPHAN_CLEANUP_APPLY=1 to apply.")
