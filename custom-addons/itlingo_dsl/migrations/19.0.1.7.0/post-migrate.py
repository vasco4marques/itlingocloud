"""Group existing DSL versions into stable families."""

import logging

_logger = logging.getLogger(__name__)


def _has_table(cr, table):
    cr.execute("SELECT to_regclass(%s)", (table,))
    return bool(cr.fetchone()[0])


def _has_columns(cr, table, columns):
    cr.execute(
        """
        SELECT column_name
          FROM information_schema.columns
         WHERE table_name = %s
           AND column_name = ANY(%s)
        """,
        (table, list(columns)),
    )
    return {row[0] for row in cr.fetchall()} == set(columns)


def migrate(cr, version):
    if not _has_table(cr, "itlingo_dsl") or not _has_table(
        cr, "itlingo_dsl_family"
    ):
        _logger.info("DSL family tables are unavailable; skipping migration")
        return

    cr.execute(
        """
        SELECT id, name, acronym, version
          FROM itlingo_dsl
         WHERE family_id IS NULL
         ORDER BY id
        """
    )
    versions = cr.fetchall()
    assigned = 0
    for dsl_id, name, acronym, version in versions:
        value = (acronym or "").strip()
        normalized = value.casefold() or "legacy:%s" % dsl_id
        cr.execute(
            """
            SELECT id
              FROM itlingo_dsl_family
             WHERE lower(btrim(acronym)) = %s
             ORDER BY id
             LIMIT 1
            """,
            (normalized,),
        )
        family = cr.fetchone()
        if family:
            family_id = family[0]
        else:
            family_name = (name or "").strip() or "Legacy DSL %s" % dsl_id
            family_acronym = value or "legacy-%s" % dsl_id
            cr.execute(
                """
                INSERT INTO itlingo_dsl_family (name, acronym, active)
                VALUES (%s, %s, TRUE)
                RETURNING id
                """,
                (family_name, family_acronym),
            )
            family_id = cr.fetchone()[0]
        candidate = version
        suffix = 0
        while True:
            cr.execute(
                """
                SELECT 1
                  FROM itlingo_dsl
                 WHERE family_id = %s
                   AND version = %s
                   AND id != %s
                 LIMIT 1
                """,
                (family_id, candidate, dsl_id),
            )
            if not cr.fetchone():
                break
            suffix += 1
            candidate = "%s-legacy-%s" % (version, dsl_id)
            if suffix > 1:
                candidate = "%s-legacy-%s-%s" % (version, dsl_id, suffix)
        cr.execute(
            "UPDATE itlingo_dsl SET family_id = %s, version = %s WHERE id = %s",
            (family_id, candidate, dsl_id),
        )
        assigned += 1

    old_rel = "itlingo_dsl_res_users_rel"
    family_rel = "itlingo_dsl_family_res_users_rel"
    if (
        _has_table(cr, old_rel)
        and _has_table(cr, family_rel)
        and _has_columns(cr, old_rel, ("itlingo_dsl_id", "res_users_id"))
        and _has_columns(
            cr, family_rel, ("itlingo_dsl_family_id", "res_users_id")
        )
    ):
        cr.execute(
            """
            INSERT INTO itlingo_dsl_family_res_users_rel
                (itlingo_dsl_family_id, res_users_id)
            SELECT DISTINCT d.family_id, rel.res_users_id
              FROM itlingo_dsl_res_users_rel rel
              JOIN itlingo_dsl d ON d.id = rel.itlingo_dsl_id
             WHERE d.family_id IS NOT NULL
            ON CONFLICT DO NOTHING
            """
        )

    _logger.info("Assigned %s DSL version(s) to stable families", assigned)
