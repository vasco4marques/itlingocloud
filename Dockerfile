FROM node:20-bookworm-slim AS services-compiler-deps

WORKDIR /services-compiler
COPY custom-addons/itlingo_dsl/services_compiler/package.json \
     custom-addons/itlingo_dsl/services_compiler/package-lock.json ./
RUN npm ci --omit=dev


FROM node:22-bookworm-slim AS templating-parser-deps

WORKDIR /templating-parser
COPY custom-addons/itlingo_templating/parser/package.json \
     custom-addons/itlingo_templating/parser/package-lock.json ./
RUN npm ci --omit=dev


FROM odoo:19

USER root
# Python deps required by itlingo_integration (cryptography ships with the base
# image) and itlingo_templating
RUN pip3 install --no-cache-dir --break-system-packages docxtpl openpyxl

COPY --chown=odoo:odoo custom-addons /mnt/extra-addons
COPY --from=services-compiler-deps --chown=odoo:odoo \
     /services-compiler/node_modules \
     /mnt/extra-addons/itlingo_dsl/services_compiler/node_modules
# Langium 4.3.1 pulls Chevrotain 12, whose runtime requires Node 22. Keep the
# parser subprocess independent from the Node version in the Odoo base image.
COPY --from=templating-parser-deps /usr/local/bin/node /usr/local/bin/node
COPY --from=templating-parser-deps --chown=odoo:odoo \
     /templating-parser/node_modules \
     /mnt/extra-addons/itlingo_templating/parser/node_modules

USER odoo
