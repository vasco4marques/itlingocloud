import base64
import io
import re
import zipfile

from odoo.tests import HttpCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestDslDownload(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = new_test_user(
            cls.env,
            login='download_admin',
            password='download_admin',
            groups=(
                'base.group_portal,'
                'itlingo_core.group_itlingo_admin'
            ),
        )
        cls.family = cls.env['itlingo.dsl.family'].create({
            'name': 'Download DSL',
            'acronym': 'DDL',
        })
        cls.dsl = cls.env['itlingo.dsl'].create({
            'family_id': cls.family.id,
            'version': '1.0',
            'status': 'draft',
        })
        cls.specification_a = b'specification one'
        cls.specification_b = b'specification two'
        cls.env['itlingo.dsl.file'].create([
            {
                'dsl_id': cls.dsl.id,
                'file_type': 'specification',
                'file_name': 'shared.txt',
                'file': base64.b64encode(cls.specification_a),
            },
            {
                'dsl_id': cls.dsl.id,
                'file_type': 'specification',
                'file_name': 'shared.txt',
                'file': base64.b64encode(cls.specification_b),
            },
            {
                'dsl_id': cls.dsl.id,
                'file_type': 'examples',
                'file_name': 'disabled.txt',
                'file': base64.b64encode(b'disabled example'),
                'is_enabled': False,
            },
            {
                'dsl_id': cls.dsl.id,
                'file_type': 'examples',
                'file_name': 'enabled.txt',
                'file': base64.b64encode(b'enabled example'),
            },
        ])

    def test_download_contains_expected_zip_members(self):
        self.authenticate('download_admin', 'download_admin')
        response = self.url_open('/dsl/%s/download' % self.dsl.id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get('Content-Type'), 'application/zip')
        self.assertIn('DDL-1.0.zip', response.headers.get('Content-Disposition', ''))

        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            members = set(archive.namelist())
            self.assertEqual(
                {
                    'grammar/',
                    'services/',
                    'validation/',
                    'examples/',
                    'specification/',
                },
                {name for name in members if name.endswith('/')},
            )
            self.assertIn('examples/enabled.txt', members)
            self.assertNotIn('examples/disabled.txt', members)

            specification_members = {
                name for name in members
                if name.startswith('specification/') and not name.endswith('/')
            }
            self.assertEqual(
                {
                    'specification/shared.txt',
                    'specification/shared-1.txt',
                },
                specification_members,
            )
            self.assertEqual(
                {
                    self.specification_a,
                    self.specification_b,
                },
                {archive.read(name) for name in specification_members},
            )

    def test_edit_page_multi_upload(self):
        self.authenticate('download_admin', 'download_admin')
        page = self.url_open('/dsl/%s' % self.dsl.id)

        self.assertEqual(page.status_code, 200)
        self.assertIn('/dsl/%s/download' % self.dsl.id, page.text)
        self.assertRegex(page.text, r'name="file"[^>]*multiple')

        token = re.search(
            r'name="csrf_token"[^>]*value="([^"]+)"', page.text,
        ).group(1)
        before = len(self.dsl.file_ids)
        upload = self.url_open(
            '/dsl/%s/files/add' % self.dsl.id,
            data={'csrf_token': token, 'file_type': 'specification'},
            files=[
                ('file', ('batch-a.txt', b'batch a')),
                ('file', ('batch-b.txt', b'batch b')),
            ],
        )

        self.assertEqual(upload.status_code, 200)
        self.dsl.invalidate_recordset()
        self.assertEqual(len(self.dsl.file_ids), before + 2)
        self.assertEqual(
            {'batch-a.txt', 'batch-b.txt'},
            {f.file_name for f in self.dsl.file_ids
             if f.file_name.startswith('batch-')},
        )
