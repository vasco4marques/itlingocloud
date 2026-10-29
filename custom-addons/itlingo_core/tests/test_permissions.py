from odoo.exceptions import AccessError, UserError
from odoo.modules.module import load_script
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools.misc import file_path

PORTAL = 'base.group_portal,itlingo_core.group_itlingo_member'


@tagged('post_install', '-at_install')
class TestCorePermissions(TransactionCase):
    """ORM policy without HTTP: per-record roles, no client-side bypass."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        user = lambda login: new_test_user(env, login=login, groups=PORTAL)  # noqa: E731
        cls.manager = user('perm_org_manager')
        cls.doc_manager = user('perm_doc_manager')
        cls.member = user('perm_member')
        cls.pending = user('perm_pending')
        cls.outsider = user('perm_outsider')
        Org = env['itlingo.organization']
        cls.org = Org.create({'name': 'Perm Org'})
        cls.other_org = Org.create({'name': 'Perm Other Org'})
        OrgRole = env['itlingo.organization.role']
        cls.role_manager = OrgRole.create({'organization_id': cls.org.id, 'user_id': cls.manager.id,
                                           'role': 'org_manager', 'state': 'accepted'})
        cls.role_doc = OrgRole.create({'organization_id': cls.org.id, 'user_id': cls.doc_manager.id,
                                       'role': 'doc_manager', 'state': 'accepted'})
        cls.role_member = OrgRole.create({'organization_id': cls.org.id, 'user_id': cls.member.id,
                                          'role': 'org_member', 'state': 'accepted'})
        cls.role_pending = OrgRole.create({'organization_id': cls.org.id, 'user_id': cls.pending.id,
                                           'role': 'org_manager', 'state': 'pending'})
        # The pending user is an accepted member elsewhere: a dotted rule
        # ("some row is mine" AND "some row is accepted") would match.
        OrgRole.create({'organization_id': cls.other_org.id, 'user_id': cls.pending.id,
                        'role': 'org_member', 'state': 'accepted'})
        Workspace = env['itlingo.workspace']
        cls.ws = Workspace.create({'name': 'Perm WS', 'organization_id': cls.org.id})
        cls.other_ws = Workspace.create({'name': 'Perm Other WS', 'organization_id': cls.other_org.id})
        cls.public_ws = Workspace.create({'name': 'Perm Public WS', 'organization_id': cls.other_org.id,
                                          'is_public_workspace': True})
        WsRole = env['itlingo.project.role']
        cls.ws_role_member = WsRole.create({'project_id': cls.ws.id, 'user_id': cls.member.id,
                                            'role': 'ws_member', 'state': 'accepted'})
        Doc = env['itlingo.document']
        cls.draft_doc = Doc.create({'name': 'Draft', 'organization_id': cls.org.id})
        cls.published_doc = Doc.create({'name': 'Published', 'organization_id': cls.org.id,
                                         'status': 'published'})
        cls.public_draft = Doc.create({'name': 'Public draft', 'project_id': cls.public_ws.id})
        cls.public_published = Doc.create({'name': 'Public published', 'project_id': cls.public_ws.id,
                                           'status': 'published'})

    def _as(self, user, records):
        return records.with_user(user)

    def _visible(self, user, records):
        return records.with_user(user).search([('id', 'in', records.ids)])

    def test_pending_row_does_not_combine_with_other_accepted_row(self):
        self.assertFalse(self._visible(self.pending, self.org))
        self.assertFalse(self._visible(self.pending, self.published_doc))
        with self.assertRaises(AccessError):
            self._as(self.pending, self.org).write({'name': 'Hijack'})
        self.role_pending.action_reject()
        self.assertFalse(self._visible(self.pending, self.org))

    def test_role_escalation_is_denied(self):
        with self.assertRaises(AccessError):
            self._as(self.member, self.role_member).write({'role': 'org_manager'})
        with self.assertRaises(AccessError):
            self._as(self.doc_manager, self.role_doc).write({'role': 'org_manager'})
        OrgRole = self.env['itlingo.organization.role']
        with self.assertRaises(AccessError):
            OrgRole.with_user(self.outsider).create({
                'organization_id': self.org.id, 'user_id': self.outsider.id,
                'role': 'org_manager', 'state': 'pending'})
        with self.assertRaises(AccessError):  # accepted rows are never sent
            OrgRole.with_user(self.manager).create({
                'organization_id': self.org.id, 'user_id': self.outsider.id,
                'role': 'org_member', 'state': 'accepted'})
        with self.assertRaises(AccessError):  # not a manager of that scope
            OrgRole.with_user(self.manager).create({
                'organization_id': self.other_org.id, 'user_id': self.outsider.id,
                'role': 'org_manager', 'state': 'pending'})
        with self.assertRaises(AccessError):  # scope reassignment
            self._as(self.manager, self.role_member).write({'organization_id': self.other_org.id})
        with self.assertRaises(AccessError):
            self.env['itlingo.project.role'].with_user(self.member).create({
                'project_id': self.ws.id, 'user_id': self.member.id, 'role': 'ws_manager'})
        with self.assertRaises(AccessError):
            self._as(self.member, self.ws_role_member).write({'role': 'ws_manager'})

    def test_manager_normal_crud_without_sudo(self):
        OrgRole = self.env['itlingo.organization.role'].with_user(self.manager)
        invite = OrgRole.create({'organization_id': self.org.id, 'user_id': self.outsider.id,
                                 'role': 'doc_manager'})
        self.assertEqual(invite.state, 'pending')
        with self.assertRaises(UserError):  # the granted role is frozen while pending
            invite.write({'role': 'org_manager'})
        self._as(self.manager, self.role_member).write({'role': 'doc_manager'})
        self.assertEqual(self.role_member.role, 'doc_manager')
        self._as(self.manager, self.org).write({'name': 'Perm Org Renamed'})
        with self.assertRaises(UserError):  # last manager protection
            self._as(self.manager, self.role_manager).write({'role': 'org_member'})
        with self.assertRaises(AccessError):  # state is admin data
            self._as(self.manager, self.org).write({'state': 'suspended'})
        self._as(self.manager, self.role_doc).unlink()
        self.assertFalse(self.role_doc.exists())

        doc = self.env['itlingo.document'].with_user(self.manager).create({
            'name': 'Manager Doc', 'organization_id': self.org.id})
        self.assertEqual(doc.creator_id, self.manager)
        # role_member is a doc_manager now; the pending invitee is no editor.
        with self.assertRaises(AccessError):
            self.env['itlingo.document'].with_user(self.pending).create({
                'name': 'Pending Doc', 'organization_id': self.org.id})
        with self.assertRaises(AccessError):
            self.env['itlingo.document'].with_user(self.manager).create({
                'name': 'Forged', 'organization_id': self.org.id, 'creator_id': self.member.id})

    def test_member_reads_published_only_and_public_is_read_only(self):
        docs = self.draft_doc | self.published_doc
        self.assertEqual(self._visible(self.member, docs), self.published_doc)
        self.assertEqual(self._visible(self.doc_manager, docs), docs)
        public = self.public_draft | self.public_published
        self.assertEqual(self._visible(self.outsider, public), self.public_published)
        self.assertEqual(self._visible(self.outsider, self.public_ws), self.public_ws)
        with self.assertRaises(AccessError):
            self._as(self.outsider, self.public_ws).write({'name': 'Defaced'})
        with self.assertRaises(AccessError):
            self._as(self.outsider, self.public_published).write({'name': 'Defaced'})

    def test_cross_scope_and_reparenting_fail(self):
        ws_manager = new_test_user(self.env, login='perm_ws_manager', groups=PORTAL)
        self.env['itlingo.organization.role'].create({
            'organization_id': self.org.id, 'user_id': ws_manager.id, 'role': 'org_member', 'state': 'accepted'})
        ws = self.env['itlingo.workspace'].with_user(ws_manager).create({
            'name': 'Own WS', 'organization_id': self.org.id})
        self.assertEqual(ws._itlingo_user_role(ws_manager).role, 'ws_manager')
        ws.write({'description': '<p>ok</p>'})
        with self.assertRaises(AccessError):
            ws.write({'organization_id': self.other_org.id})
        with self.assertRaises(AccessError):
            self._as(ws_manager, self.other_ws).write({'name': 'Not mine'})
        with self.assertRaises(AccessError):
            self.env['itlingo.workspace'].with_user(ws_manager).create({
                'name': 'Foreign', 'organization_id': self.other_org.id})
        doc = self.env['itlingo.document'].with_user(ws_manager).create({'name': 'WS Doc', 'project_id': ws.id})
        with self.assertRaises(AccessError):
            doc.write({'project_id': self.other_ws.id})

    def test_org_creator_bootstraps_manager_role(self):
        org = self.env['itlingo.organization'].with_user(self.outsider).create({'name': 'Self Org'})
        self.assertEqual(org._itlingo_user_role(self.outsider).role, 'org_manager')
        with self.assertRaises(AccessError):
            self.env['itlingo.organization'].with_user(self.outsider).create({
                'name': 'Forged', 'partner_id': self.manager.partner_id.id})

    def test_notification_recipient_lock(self):
        Notif = self.env['itlingo.notification']
        own = Notif._notify(self.member, 'Hello', '<p>x</p>')
        with self.assertRaises(AccessError):
            Notif.with_user(self.member).create({'user_id': self.manager.id, 'title': 'Spoof'})
        with self.assertRaises(AccessError):
            own.with_user(self.member).write({'user_id': self.manager.id})
        with self.assertRaises(AccessError):
            own.with_user(self.member).write({'title': 'Edited'})
        own.with_user(self.member).action_mark_read()
        self.assertTrue(own.is_read)

    def test_invitation_response_validates_actor(self):
        with self.assertRaises(AccessError):
            self._as(self.manager, self.role_pending).action_accept()
        self.assertEqual(self.role_pending.state, 'pending')
        self._as(self.pending, self.role_pending).action_accept()
        self.assertEqual(self.role_pending.state, 'accepted')
        with self.assertRaises(UserError):
            self._as(self.pending, self.role_pending).action_accept()

    def test_org_manager_cascade_is_revoked(self):
        # An explicit workspace manager keeps the workspace managed.
        self.env['itlingo.project.role'].create({
            'project_id': self.ws.id, 'user_id': self.outsider.id,
            'role': 'ws_manager', 'state': 'accepted'})
        self.assertEqual(self.ws_role_member.role, 'ws_member')
        self.role_member.write({'role': 'org_manager'})
        self.assertEqual((self.ws_role_member.role, self.ws_role_member.grant_source),
                         ('ws_manager', 'org_manager'))
        self._as(self.manager, self.role_member).write({'role': 'org_member'})
        self.assertEqual((self.ws_role_member.role, self.ws_role_member.grant_source),
                         ('ws_member', 'explicit'))
        self.role_doc.write({'role': 'org_manager'})
        cascade = self.env['itlingo.project.role'].search([
            ('user_id', '=', self.doc_manager.id), ('project_id', '=', self.ws.id)])
        self.assertEqual(cascade.grant_source, 'org_manager')
        self._as(self.manager, self.role_doc).unlink()
        self.assertFalse(cascade.exists())

    def test_cascade_revocation_keeps_a_workspace_manager(self):
        """A is the explicit workspace manager, B inherits it from the org
        manager role, A leaves the workspace, then A demotes B."""
        WsRole = self.env['itlingo.project.role']
        # cls.ws inherited the org manager A at creation; make A's row the
        # explicit grant of this scenario.
        explicit = WsRole.search([('user_id', '=', self.manager.id), ('project_id', '=', self.ws.id)])
        explicit.write({'grant_source': 'explicit'})
        self.assertEqual((explicit.role, explicit.state), ('ws_manager', 'accepted'))
        self.role_doc.write({'role': 'org_manager'})
        inherited = WsRole.search([('user_id', '=', self.doc_manager.id), ('project_id', '=', self.ws.id)])
        self.assertEqual((inherited.role, inherited.grant_source), ('ws_manager', 'org_manager'))
        self._as(self.manager, explicit).unlink()
        with self.assertRaises(UserError):
            self._as(self.manager, self.role_doc).write({'role': 'org_member'})
        self.env.invalidate_all()  # read back the database, not the cache
        self.assertEqual(self.role_doc.role, 'org_manager')
        self.assertEqual((inherited.role, inherited.state), ('ws_manager', 'accepted'))
        with self.assertRaises(UserError):
            self._as(self.manager, self.role_doc).unlink()
        self.env.invalidate_all()
        self.assertTrue(self.role_doc.exists() and inherited.exists())
        # With an explicit successor, the demotion goes through.
        self._as(self.doc_manager, self.ws_role_member).write({'role': 'ws_manager'})
        self._as(self.manager, self.role_doc).write({'role': 'org_member'})
        self.assertFalse(inherited.exists())

    def test_cascade_revocation_bypass_needs_admin_group(self):
        WsRole = self.env['itlingo.project.role']
        # cls.ws inherited the org manager at creation; remove that row so B
        # becomes the only workspace manager (superuser setup, admin group).
        WsRole.search([('user_id', '=', self.manager.id), ('project_id', '=', self.ws.id)]).unlink()
        self.role_doc.write({'role': 'org_manager'})
        inherited = WsRole.search([
            ('user_id', '=', self.doc_manager.id), ('project_id', '=', self.ws.id)])
        self.assertEqual(inherited.role, 'ws_manager')
        self.assertEqual(WsRole.search_count([
            ('project_id', '=', self.ws.id), ('role', '=', 'ws_manager'), ('state', '=', 'accepted'),
        ]), 1)  # the only workspace manager
        # Scoped sudo in a non-admin's name does not skip the rule.
        with self.assertRaises(UserError):
            self.role_doc.with_user(self.manager).sudo().write({'role': 'org_member'})
        self.env.invalidate_all()
        self.assertEqual((self.role_doc.role, inherited.exists().role), ('org_manager', 'ws_manager'))
        # A platform administrator may repair it (recovery).
        admin = new_test_user(self.env, login='perm_platform_admin',
                              groups='base.group_user,itlingo_core.group_itlingo_admin')
        self.role_doc.with_user(admin).write({'role': 'org_member'})
        self.assertEqual(self.role_doc.role, 'org_member')
        self.assertFalse(inherited.exists())

    def test_new_workspace_inherits_org_managers_only(self):
        WsRole = self.env['itlingo.project.role']
        # A workspace manager removed the org manager's inherited row here;
        # creating another workspace must not grant it back.
        self.role_doc.write({'role': 'org_manager'})
        removed = WsRole.search([('user_id', '=', self.doc_manager.id), ('project_id', '=', self.ws.id)])
        WsRole.create({'project_id': self.ws.id, 'user_id': self.outsider.id,
                       'role': 'ws_manager', 'state': 'accepted'})
        removed.unlink()
        ws = self.env['itlingo.workspace'].with_user(self.member).create({
            'name': 'After promotion', 'organization_id': self.org.id})
        managers = WsRole.search([('project_id', '=', ws.id), ('role', '=', 'ws_manager')])
        self.assertEqual(managers.user_id, self.member | self.manager | self.doc_manager)
        self.assertEqual(managers.filtered(lambda r: r.user_id == self.manager).grant_source, 'org_manager')
        self.assertEqual(managers.filtered(lambda r: r.user_id == self.member).grant_source, 'explicit')
        self.assertFalse(WsRole.search([('user_id', '=', self.doc_manager.id), ('project_id', '=', self.ws.id)]))
        self.assertFalse(WsRole.search([('user_id', '=', self.doc_manager.id), ('project_id', '=', self.other_ws.id)]))

    def test_scoped_sudo_cannot_orphan_organization(self):
        with self.assertRaises(UserError):
            self.role_manager.with_user(self.manager).sudo().unlink()
        self.env.invalidate_all()
        self.assertTrue(self.role_manager.exists())
        with self.assertRaises(UserError):
            self.role_manager.with_user(self.manager).sudo().write({'role': 'org_member'})
        self.env.invalidate_all()
        self.assertEqual(self.role_manager.role, 'org_manager')

    def test_context_defaults_cannot_bypass_create_guards(self):
        OrgRole = self.env['itlingo.organization.role'].with_user(self.manager)
        invite = OrgRole.with_context(default_state='accepted', default_response_date='2020-01-01').create({
            'organization_id': self.org.id, 'user_id': self.outsider.id, 'role': 'org_member'})
        self.assertEqual(invite.state, 'pending')
        with self.assertRaises(AccessError):  # target scope from context, not vals
            OrgRole.with_context(default_organization_id=self.other_org.id).create({
                'user_id': self.outsider.id, 'role': 'org_member'})
        with self.assertRaises(AccessError):
            self.env['itlingo.project.role'].with_user(self.member).with_context(
                default_project_id=self.ws.id, default_state='accepted', default_role='ws_manager',
            ).create({'user_id': self.member.id})
        doc = self.env['itlingo.document'].with_user(self.manager).with_context(
            default_creator_id=self.member.id, default_creation_date='2000-01-01',
        ).create({'name': 'Ctx Doc', 'organization_id': self.org.id})
        self.assertEqual(doc.creator_id, self.manager)
        self.assertNotEqual(str(doc.creation_date)[:4], '2000')
        with self.assertRaises(AccessError):
            self.env['itlingo.document'].with_user(self.manager).with_context(
                default_organization_id=self.other_org.id).create({'name': 'Ctx Foreign'})
        org = self.env['itlingo.organization'].with_user(self.outsider).with_context(
            default_state='suspended', default_partner_id=self.manager.partner_id.id,
        ).create({'name': 'Ctx Org'})
        self.assertEqual(org.state, 'active')
        self.assertNotEqual(org.partner_id, self.manager.partner_id)
        self.env['itlingo.organization.role'].create({
            'organization_id': self.other_org.id, 'user_id': self.member.id,
            'role': 'org_member', 'state': 'accepted'})
        ws = self.env['itlingo.workspace'].with_user(self.member).with_context(
            default_creator_id=self.manager.id, default_workspace_key='forged-key',
        ).create({'name': 'Ctx WS', 'organization_id': self.other_org.id})
        self.assertEqual(ws.creator_id, self.member)
        self.assertNotEqual(ws.workspace_key, 'forged-key')

    def test_failed_document_write_keeps_file_and_status(self):
        import base64
        payload = base64.b64encode(b'original')
        doc = self.env['itlingo.document'].with_user(self.manager).create({
            'name': 'Upload', 'organization_id': self.org.id,
            'file_name': 'original.txt', 'document_file': payload})
        try:
            # Grounding knowledge needs a published, text-like file.
            doc.write({'status': 'published', 'dsl_knowledge': True,
                       'file_name': 'replaced.docx',
                       'document_file': base64.b64encode(b'PK\x03\x04binary')})
        except Exception:  # noqa: BLE001 - the caller catches, as the portal does
            pass
        else:
            self.fail('The invalid grounding upload was accepted.')
        doc.invalidate_recordset()
        self.assertEqual((doc.status, doc.file_name, doc.document_file, doc.dsl_knowledge),
                         ('draft', 'original.txt', payload, False))

    def test_pending_invitation_needs_signup_proof(self):
        Pending = self.env['itlingo.pending.invitation']
        with self.assertRaises(AccessError):
            Pending.with_user(self.member).create({
                'email': 'Victim@Example.com', 'organization_id': self.org.id, 'role': 'org_manager'})
        invitation = Pending.with_user(self.manager).create({
            'email': 'Victim@Example.com', 'organization_id': self.org.id, 'role': 'doc_manager'})
        self.assertEqual(invitation.invited_by_id, self.manager)
        self.assertTrue(invitation.partner_id)
        with self.assertRaises(AccessError):
            invitation.with_user(self.manager).write({'role': 'org_manager'})
        invitation.with_user(self.manager)._send_signup_email()
        self.assertIn('token=', invitation.partner_id.sudo()._get_signup_url())

        Users = self.env['res.users'].with_context(no_reset_password=True)
        portal = self.env.ref('base.group_portal')
        # Public signup with the invited address: a new contact, no grant.
        squatter = Users.create({'name': 'Squatter', 'login': 'victim@example.com',
                                 'group_ids': [(6, 0, portal.ids)]})
        self.assertFalse(self.org._itlingo_user_role(squatter))
        self.assertTrue(invitation.exists())
        # Token signup: the user gets the invited contact and the role.
        invited = Users.create({'name': 'Invited', 'login': 'invited@example.com',
                                'partner_id': invitation.partner_id.id,
                                'group_ids': [(6, 0, portal.ids)]})
        self.assertEqual(self.org._itlingo_user_role(invited).role, 'doc_manager')
        self.assertFalse(invitation.exists())

    def test_migration_marks_ambiguous_ws_manager_grants(self):
        creator_row = self.ws._itlingo_user_role(self.ws.creator_id)
        self.ws_role_member.write({'role': 'ws_manager'})
        post = load_script(file_path('itlingo_core/migrations/19.0.3.2.0/post-migrate.py'),
                           'itlingo_core_test_perm_post_migrate')
        self.env.flush_all()
        post.migrate(self.env.cr, '19.0.3.1.0')
        self.env.invalidate_all()
        self.assertEqual(self.ws_role_member.grant_source, 'legacy')
        self.assertEqual(self.ws_role_member.role, 'ws_manager')  # kept for review
        if creator_row:
            self.assertEqual(creator_row.grant_source, 'explicit')
