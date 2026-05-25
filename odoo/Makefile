CUSTOM_MODULES = itlingo_organizations,itlingo_workspace_access,itlingo_documents,itlingo_notifications,itlingo_integration,itlingo_website_portal

run:
	./odoo-bin -c ../config/odoo.config -d itlingo_dev

upgrade_all:
	./odoo-bin -c ../config/odoo.config -d itlingo_dev -u all --stop-after-init

upgrade_custom:
	./odoo-bin -c ../config/odoo.config -d itlingo_dev -u $(CUSTOM_MODULES) --stop-after-init

upgrade: upgrade_custom run
