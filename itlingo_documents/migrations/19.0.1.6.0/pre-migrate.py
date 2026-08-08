"""Clean legacy dual-owned documents before the ownership constraint is added."""


def migrate(cr, version):
    cr.execute(
        """
        UPDATE itlingo_document
           SET organization_id = NULL
         WHERE project_id IS NOT NULL
        """
    )
