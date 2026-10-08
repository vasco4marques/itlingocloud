CUSTOM_MODULES = itlingo_organizations,itlingo_workspace_access,itlingo_documents,itlingo_notifications,itlingo_integration,itlingo_website_portal,itlingo_dsl,itlingo_chatbot_integration,itlingo_templating

SQL_DUMP ?= ../itlingo_cloud_20260521_030001.sql

.PHONY: run upgrade_all upgrade_custom upgrade deploy migrate_itlingo_cloud_dry migrate_itlingo_cloud

# Build + push the docker image and deploy it to the droplet (incl. module
# upgrade there). Local targets below are unaffected.
deploy:
	../deploy.sh

run:
	./odoo-bin -c ../config/odoo.config -d itlingo_dev

upgrade_all:
	./odoo-bin -c ../config/odoo.config -d itlingo_dev -u all --stop-after-init

upgrade_custom:
	./odoo-bin -c ../config/odoo.config -d itlingo_dev -u $(CUSTOM_MODULES) --stop-after-init

upgrade: upgrade_custom run

migrate_itlingo_cloud_dry:
	ITLINGO_MIGRATE_ARGS="--sql-file $(SQL_DUMP) --dry-run" \
	  ./odoo-bin shell -c ../config/odoo.config -d itlingo_dev --no-http \
	  --shell-interface=python < ../scripts/migrate_itlingo_cloud.py

migrate_itlingo_cloud:
	ITLINGO_MIGRATE_ARGS="--sql-file $(SQL_DUMP)" \
	  ./odoo-bin shell -c ../config/odoo.config -d itlingo_dev --no-http \
	  --shell-interface=python < ../scripts/migrate_itlingo_cloud.py
