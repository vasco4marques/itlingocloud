"""Move document DSL pins from versions to stable families."""


def _has_column(cr, table, column):
    cr.execute(
        """
        SELECT 1
          FROM information_schema.columns
         WHERE table_name = %s AND column_name = %s
        """,
        (table, column),
    )
    return bool(cr.fetchone())


def migrate(cr, version):
    if not _has_column(cr, 'itlingo_document', 'dsl_id'):
        return
    if not _has_column(cr, 'itlingo_document', 'dsl_version_id'):
        return
    if not _has_column(cr, 'itlingo_document', 'dsl_family_id'):
        return

    # Keep the old version pin exactly; rerunning this migration never changes
    # an explicitly migrated value.
    cr.execute(
        """
        UPDATE itlingo_document
           SET dsl_version_id = dsl_id
         WHERE dsl_version_id IS NULL AND dsl_id IS NOT NULL
        """
    )
    cr.execute(
        """
        UPDATE itlingo_document document
           SET dsl_family_id = dsl.family_id
          FROM itlingo_dsl dsl
         WHERE document.dsl_family_id IS NULL
           AND document.dsl_version_id = dsl.id
           AND dsl.family_id IS NOT NULL
        """
    )
