CUSTOM_MODULES = itlingo_core,itlingo_dsl,itlingo_integration,itlingo_website_portal,itlingo_chatbot_integration,itlingo_templating

.PHONY: run upgrade_all upgrade_custom upgrade deploy

# Build + push the docker image and deploy it to the droplet (incl. module
# upgrade there). Local targets below are unaffected.
deploy:
	../deploy.sh

run:
	./odoo-bin -c ../config/odoo.config -d itlingo_dev

upgrade_all:
	./odoo-bin -c ../config/odoo.config -d itlingo_dev -u all --pre-upgrade-scripts=../custom-addons/itlingo_core/upgrade.py --stop-after-init

upgrade_custom:
	./odoo-bin -c ../config/odoo.config -d itlingo_dev -u $(CUSTOM_MODULES) --pre-upgrade-scripts=../custom-addons/itlingo_core/upgrade.py --stop-after-init

upgrade: upgrade_custom run
