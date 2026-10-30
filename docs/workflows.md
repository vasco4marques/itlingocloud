# Workflows

This guide describes the operations of ITLingo Cloud users. The labels are the labels in the portal pages.

## Accounts and access

Public signup at `/web/signup` is off on a new database. An administrator enables it first. See [local-development.md](local-development.md#accounts-and-access).

A user who signs up gets a portal account and the `ITLingo Member` group. After the first login, the page "Welcome to ITLingo Cloud" asks the user to create an organization. The user can skip this step.

Only active internal users in the `ITLingo Admin` group can use the Odoo backend (`/odoo`) and generic model RPC. All other users use the portal pages under `/my`.

## Organizations

Open `/my/organizations`. Any signed-in user can create an organization. The creator becomes its `Org Manager`.

Organization roles:

- `Org Manager`: invites members, changes roles, changes settings, and deletes the organization. An Org Manager is also `Workspace Manager` of every workspace of the organization.
- `Document Manager`: creates, edits, and deletes organization documents.
- `Org Member`: reads the published documents of the organization.

Odoo cannot delete an organization that has workspaces. If the last member leaves an organization without workspaces, Odoo deletes the organization. If the last Org Manager leaves, the portal asks for the promotion of another member first.

## Workspaces

Use "New workspace" to start the four-step wizard. You must be an accepted member of an organization. The creator becomes the `Workspace Manager`.

Workspace roles:

- `Workspace Manager`: invites members, changes roles, changes the workspace settings, and deletes the workspace.
- `Document Manager`: creates, edits, and deletes workspace documents.
- `Workspace Member`: reads the published documents of the workspace.

The workspace page has these sections: Home, Documents, Specifications, Users, Chatbot, and Settings.

The "Public workspace" option lists the workspace on `/public-workspaces`. All users and visitors can then read its published documents. Public access is read-only. It does not include organization documents.

## Invitations

Organization and workspace managers use "Invite member". They enter an email address and a role. Odoo sends an email with a proof link to that address. This also applies to an address that already has an account.

The invitee opens the link. Then the invitee signs in or creates an account with that email address. The link grants the role only to the account with the invited address. If you send the invitation again, Odoo keeps the role of the open invitation.

The invitation email requires an outgoing SMTP server, a company email address, and a correct `web.base.url`. See [configuration.md](configuration.md).

## Notifications

The bell in the website header and `/my/notifications` show invitations and membership events. Notification emails go to the Odoo mail queue. Odoo sends them only when the scheduler runs.

## Documents

Use "New document" in the Documents section of an organization or a workspace. Document types are Specification, Template, Technical Document, Dataset, Tutorial, Prompt Template, and Other.

The status is Draft, In Review, Approved, Published, or Archived. Editors set the status in the edit form of the document. Readers who are not editors see only Published documents.

"Grounding Knowledge" marks a document as knowledge for the chatbot. Only a Published document can have this mark.

## DSLs

The DSL catalogue is at `/dsl`. Visitors see the active DSLs.

- An `ITLingo Admin` uses "New DSL" to create a DSL. The admin also adds maintainers ("Add maintainer") and publishes versions ("Publish").
- A maintainer edits the grammar and services files of a Draft version in the Grammar Editor ("Open editor"). The maintainer uses "Validate" to check the grammar and "Create draft version" to start a new version.
- "Publish" validates the grammar again on the server. The previous active version becomes Deprecated.

The allowed DSLs of an organization or a workspace are set in the Odoo backend only.

## Templates and document generation

1. Create a document with the type Template.
2. Link the document to a DSL and upload a `.docx`, `.xlsx`, or UTF-8 text file.
3. On the document page, find "Generate a document".
4. Upload a specification file and click "Generate and download".

The DSL must be active and have a valid published grammar. Odoo does not keep the generated file. All users who can read the template can generate a document. The template reference for each DSL is at `/dsl/template-reference`.

## ITOI

Use "Launch ITOI" on the Specifications page of a workspace. ITOI opens in a new tab.

- A `Workspace Manager` or `Document Manager` gets write access.
- Other workspace members get read-only access.
- A non-member of a public workspace gets read-only access to the published documents of that workspace only.

## Chatbot

Use "Chatbot" in the workspace menu. Users without write access and visitors of public workspaces get read-only access. Org Managers configure the language models on the "LLM Settings" page of the organization. The chatbot service and its database tables must exist. See [architecture.md](architecture.md).
