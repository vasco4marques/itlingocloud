from odoo.modules.module import load_script
from odoo.tests import TransactionCase, tagged
from odoo.tools.misc import file_path

SCRIPTS = 'itlingo_core/migrations/19.0.3.1.0/%s-migrate.py'


@tagged('post_install', '-at_install')
class TestLegacyCleanup(TransactionCase):
    """Run the 19.0.3.1.0 scripts on a database that carries the retired
    schema and metadata, inside the test transaction."""

    def _sql(self, query, params=()):
        self.env.cr.execute(query, params)
        return self.env.cr.fetchall() if self.env.cr.description else None

    def _xmlid(self, module, name, record):
        return self.env['ir.model.data'].create({
            'module': module, 'name': name, 'model': record._name, 'res_id': record.id,
        })

    def _exists(self, relation):
        return self._sql("SELECT to_regclass(%s)", [relation])[0][0] is not None

    def _columns(self, table):
        return {c for (c,) in self._sql(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s", [table])}

    def test_cleanup_keeps_data_and_removes_retired_schema(self):
        env = self.env
        self._sql("""
            CREATE TABLE itlingo_sprint (id serial PRIMARY KEY);
            CREATE TABLE itlingo_backlog_item (id serial PRIMARY KEY, sprint_id int REFERENCES itlingo_sprint);
            CREATE TABLE itlingo_library (id serial PRIMARY KEY);
            CREATE TABLE itlingo_document_library (id serial PRIMARY KEY,
                document_id int REFERENCES itlingo_document, library_id int REFERENCES itlingo_library);
            ALTER TABLE itlingo_document ADD COLUMN backlog_item_id int REFERENCES itlingo_backlog_item;
            ALTER TABLE itlingo_organization ADD COLUMN organization_type varchar NOT NULL DEFAULT 'academic';
            ALTER TABLE itlingo_workspace ADD COLUMN methodology varchar, ADD COLUMN planned_cost numeric,
                ADD COLUMN current_cost numeric;
            CREATE VIEW itlingo_burndown_report AS
                SELECT d.id, d.backlog_item_id FROM itlingo_document d;
        """)
        [(sprint_model_id,)] = self._sql("""
            INSERT INTO ir_model (model, name, "order", state)
            VALUES ('itlingo.sprint', '{"en_US": "Sprint"}', 'id', 'base') RETURNING id""")
        doc_model = env['ir.model']._get('itlingo.document')
        [(dead_field_id,)] = self._sql("""
            INSERT INTO ir_model_fields (model_id, model, name, field_description, ttype, state, relation, store)
            VALUES (%s, 'itlingo.document', 'backlog_item_id', '{"en_US": "Backlog Item"}', 'many2one',
                    'base', 'itlingo.backlog.item', true) RETURNING id""", [doc_model.id])

        agile = env['ir.module.module'].create({'name': 'itlingo_agile', 'state': 'uninstalled'})
        Imd = env['ir.model.data']
        live_field = env['ir.model.fields']._get('itlingo.document', 'name')
        organization = env['itlingo.organization'].create({'name': 'Legacy Org'})
        view = env['ir.ui.view'].create({
            'name': 'agile.document', 'model': 'itlingo.document', 'type': 'list',
            'arch': '<list><field name="name"/></list>',
        })
        self._xmlid('itlingo_agile', 'model_itlingo_sprint', env['ir.model'].browse(sprint_model_id))
        self._xmlid('itlingo_agile', 'model_itlingo_document', doc_model)
        self._xmlid('itlingo_agile', 'field_itlingo_document__name', live_field)
        self._xmlid('itlingo_agile', 'field_itlingo_document__backlog_item_id',
                    env['ir.model.fields'].browse(dead_field_id))
        self._xmlid('itlingo_agile', 'legacy_org', organization)
        self._xmlid('itlingo_agile', 'document_list', view)

        spec = env.ref('itlingo_core.doc_type_specification')
        Type = env['itlingo.document.type']
        rsl = Type.create({'name': 'Legacy RSL', 'type_code': 'specification'})
        self._xmlid('itlingo_core', 'doc_type_rsl', rsl)
        self._xmlid('itlingo_core', 'doc_type_psl', spec)  # alias of the canonical record
        user_type = Type.create({'name': 'Team Library', 'type_code': 'specification'})
        self._sql("UPDATE itlingo_document_type SET type_code = 'specification_library' WHERE id = %s",
                  [user_type.id])
        document = env['itlingo.document'].create({'name': 'Old RSL Spec', 'document_type_id': rsl.id})
        attachment = env['ir.attachment'].create({
            'name': 'spec.rsl', 'raw': b'Package x', 'res_model': 'itlingo.document', 'res_id': document.id,
        })
        notification = env['itlingo.notification']._notify(env.user, 'Sprint', '<p>s</p>')
        notification.write({'res_model': 'itlingo.sprint', 'res_id': 1})
        env.flush_all()

        pre = load_script(file_path(SCRIPTS % 'pre'), 'itlingo_core_test_pre_migrate')
        end = load_script(file_path(SCRIPTS % 'end'), 'itlingo_core_test_end_migrate')
        for _run in range(2):  # the second run must be a no-op
            pre.migrate(env.cr, '19.0.3.0.0')
            end.migrate(env.cr, '19.0.3.0.0')
        env.invalidate_all()

        for relation in ('itlingo_sprint', 'itlingo_backlog_item', 'itlingo_library',
                         'itlingo_document_library', 'itlingo_burndown_report'):
            self.assertFalse(self._exists(relation), relation)
        self.assertNotIn('backlog_item_id', self._columns('itlingo_document'))
        self.assertNotIn('organization_type', self._columns('itlingo_organization'))
        self.assertFalse({'methodology', 'planned_cost', 'current_cost'} & self._columns('itlingo_workspace'))

        self.assertEqual(document.document_type_id, spec)
        self.assertFalse(rsl.exists())
        self.assertTrue(spec.exists())
        self.assertFalse(Imd.search([('module', '=', 'itlingo_core'), ('name', 'in', ['doc_type_rsl', 'doc_type_psl'])]))
        self.assertEqual(user_type.type_code, 'specification')
        self.assertEqual((attachment.exists().res_model, attachment.res_id, attachment.raw),
                         ('itlingo.document', document.id, b'Package x'))

        self.assertTrue(notification.exists())
        self.assertFalse(notification.res_model)
        self.assertFalse(agile.exists())
        self.assertFalse(Imd.search([('module', '=', 'itlingo_agile')]))
        self.assertTrue(organization.exists() and doc_model.exists() and live_field.exists())
        self.assertFalse(env['ir.model'].browse(sprint_model_id).exists())
        self.assertFalse(env['ir.model.fields'].browse(dead_field_id).exists())
        self.assertFalse(view.exists())
