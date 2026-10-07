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
    """Active la RLS en mode refus par defaut sur les tables publiques.

    Sans politique RLS, les roles PostgREST ``anon`` et ``authenticated`` ne
    peuvent lire, inserer, modifier ou supprimer aucune ligne. Le proprietaire
    PostgreSQL utilise par le backend Flask conserve son acces normal. Les tests
    SQLite ignorent volontairement cette migration specifique a PostgreSQL.
    """
    if dialect_name != "postgresql":
        return ()

    for table_name in PUBLIC_API_TABLES:
        session.execute(text(
            'ALTER TABLE public."{}" ENABLE ROW LEVEL SECURITY'.format(table_name)
        ))

    return PUBLIC_API_TABLES
