import re

from odoo.tests import HttpCase, new_test_user, tagged
from odoo.tools.misc import mute_logger


@tagged('post_install', '-at_install')
class TestDslPortalPermissions(HttpCase):
    """DSL portal routes run with the maintainer's own ORM rights."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.maintainer = new_test_user(
            cls.env,
            login='portal_perm_maintainer',
            password='portal_perm_maintainer',
            groups='base.group_portal,itlingo_core.group_itlingo_member',
        )
        cls.other = new_test_user(
            cls.env,
            login='portal_perm_other',
            password='portal_perm_other',
            groups='base.group_portal,itlingo_core.group_itlingo_member',
        )
        Dsl = cls.env['itlingo.dsl']
        cls.draft = Dsl.create({
            'name': 'Portal Permission Own', 'acronym': 'PPOWN',
            'version': '1.0', 'status': 'draft',
            'maintainer_ids': [(6, 0, cls.maintainer.ids)],
        })
        cls.other_draft = Dsl.create({
            'name': 'Portal Permission Other', 'acronym': 'PPOTHER',
            'version': '1.0', 'status': 'draft',
            'maintainer_ids': [(6, 0, cls.other.ids)],
        })
        cls.other_active = Dsl.create({
            'family_id': cls.other_draft.family_id.id,
            'version': '0.9', 'status': 'active',
        })

    def setUp(self):
        super().setUp()
        self.authenticate('portal_perm_maintainer', 'portal_perm_maintainer')
        page = self.url_open(f'/dsl/{self.draft.id}')
        self.token = re.search(
            r'name="csrf_token"[^>]*value="([^"]+)"', page.text,
        ).group(1)

    def _post(self, url, **data):
        with mute_logger('odoo.http'):
            return self.url_open(url, data={'csrf_token': self.token, **data})

    def test_maintainer_saves_own_draft_and_uploads_files(self):
        response = self._post(
            f'/dsl/{self.draft.id}',
            name='ignored', acronym='IGNORED', version='1.0', status='draft',
            description='<p>Maintainer text</p>',
        )
        self.assertIn('message=saved', response.url)
        self.draft.invalidate_recordset()
        self.assertIn('Maintainer text', self.draft.description)
        self.assertEqual(self.draft.acronym, 'PPOWN')

        with mute_logger('odoo.http'):
            upload = self.url_open(
                f'/dsl/{self.draft.id}/files/add',
                data={'csrf_token': self.token, 'file_type': 'specification'},
                files=[('file', ('spec.txt', b'spec'))],
            )
        self.assertIn('message=file_added', upload.url)
        self.draft.invalidate_recordset()
        self.assertEqual(self.draft.file_ids.mapped('file_name'), ['spec.txt'])

    def test_maintainer_cannot_modify_other_family_through_portal(self):
        attempts = [
            (f'/dsl/{self.other_active.id}', {
                'name': 'x', 'acronym': 'x', 'version': '0.9',
                'status': 'active', 'description': 'Hijacked',
            }),
            (f'/dsl/{self.other_active.id}/files/add', {
                'file_type': 'specification',
            }),
            (f'/dsl/{self.other_active.id}/create-draft', {'version': '5.0'}),
            (f'/dsl/{self.other_draft.id}/validate-draft', {}),
        ]
        for url, data in attempts:
            with self.subTest(url=url):
                self.assertIn(self._post(url, **data).status_code, (403, 404))
        self.other_active.invalidate_recordset()
        self.assertFalse(self.other_active.description)
        self.assertEqual(
            self.env['itlingo.dsl'].search_count([
                ('family_id', '=', self.other_draft.family_id.id),
            ]),
            2,
        )

    def test_maintainer_cannot_manage_maintainers_or_delete(self):
        family = self.draft.family_id
        add = self._post(
            f'/dsl/{self.draft.id}/maintainers/add', email=self.other.login,
        )
        remove = self._post(
            f'/dsl/{self.draft.id}/maintainers/{self.maintainer.id}/remove',
        )
        delete = self._post(f'/dsl/{self.draft.id}/delete')
        publish = self._post(f'/dsl/{self.draft.id}/publish')

        for response in (add, remove, delete, publish):
            self.assertEqual(response.status_code, 403)
        family.invalidate_recordset()
        self.assertEqual(family.maintainer_ids, self.maintainer)
        self.assertTrue(self.draft.exists())
        self.assertEqual(self.draft.status, 'draft')
