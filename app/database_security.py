"""Durcissement de la base PostgreSQL exposee par Supabase/PostgREST."""

from sqlalchemy import text


# Liste explicite : les identifiants SQL ne proviennent jamais d'une entree externe.
PUBLIC_API_TABLES = (
    "audit_logs",
    "bonuses",
    "bot_sessions",
    "depots",
    "difficulties",
    "mfa_recovery_codes",
    "notifications",
    "password_reset_tokens",
    "performances",
    "processed_messages",
    "product_targets",
    "products",
    "sale_lines",
    "sales",
    "stocks",
    "users",
    "vendors",
)


def enable_row_level_security(session, dialect_name):
    """Active la RLS et autorise uniquement le role SQL du backend.

    Sans politique RLS, les roles PostgREST ``anon`` et ``authenticated`` ne
    peuvent lire, inserer, modifier ou supprimer aucune ligne. Une politique
    explicite redonne l'acces complet au role ``current_user`` de Flask, y
    compris lorsque ce role ne possede pas l'attribut BYPASSRLS. Les tests
    SQLite ignorent volontairement cette migration specifique a PostgreSQL.
    """
    if dialect_name != "postgresql":
        return ()

    backend_role = session.execute(text("SELECT current_user")).scalar_one()
    quoted_role = '"{}"'.format(str(backend_role).replace('"', '""'))

    for table_name in PUBLIC_API_TABLES:
        quoted_table = 'public."{}"'.format(table_name)
        session.execute(text(
            "ALTER TABLE {} ENABLE ROW LEVEL SECURITY".format(quoted_table)
        ))
        session.execute(text(
            "DROP POLICY IF EXISTS fanmilk_backend_full_access ON {}".format(
                quoted_table
            )
        ))
        session.execute(text(
            "CREATE POLICY fanmilk_backend_full_access ON {} "
            "FOR ALL TO {} USING (true) WITH CHECK (true)".format(
                quoted_table,
                quoted_role,
            )
        ))

    return PUBLIC_API_TABLES
