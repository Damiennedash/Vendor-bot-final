from app.database_security import PUBLIC_API_TABLES, enable_row_level_security


class RecordingSession:
    def __init__(self):
        self.statements = []

    def execute(self, statement):
        self.statements.append(str(statement))


def test_rls_is_enabled_for_every_public_api_table():
    session = RecordingSession()

    protected = enable_row_level_security(session, "postgresql")

    assert protected == PUBLIC_API_TABLES
    assert len(session.statements) == 17
    for table_name, statement in zip(PUBLIC_API_TABLES, session.statements):
        assert statement == (
            f'ALTER TABLE public."{table_name}" ENABLE ROW LEVEL SECURITY'
        )


def test_non_postgresql_databases_are_untouched():
    session = RecordingSession()

    protected = enable_row_level_security(session, "sqlite")

    assert protected == ()
    assert session.statements == []
