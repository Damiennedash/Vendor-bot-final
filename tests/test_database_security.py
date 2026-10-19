from app.database_security import PUBLIC_API_TABLES, enable_row_level_security


class RecordingSession:
    def __init__(self, current_user="fanmilk_backend"):
        self.statements = []
        self.current_user = current_user

    def execute(self, statement):
        self.statements.append(str(statement))
        return RecordingResult(self.current_user)


class RecordingResult:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value


def test_rls_is_enabled_for_every_public_api_table():
    session = RecordingSession()

    protected = enable_row_level_security(session, "postgresql")

    assert protected == PUBLIC_API_TABLES
    assert session.statements[0] == "SELECT current_user"
    assert len(session.statements) == 1 + (len(PUBLIC_API_TABLES) * 3)
    for index, table_name in enumerate(PUBLIC_API_TABLES):
        offset = 1 + (index * 3)
        assert session.statements[offset] == (
            f'ALTER TABLE public."{table_name}" ENABLE ROW LEVEL SECURITY'
        )
        assert session.statements[offset + 1] == (
            f'DROP POLICY IF EXISTS fanmilk_backend_full_access '
            f'ON public."{table_name}"'
        )
        assert session.statements[offset + 2] == (
            f'CREATE POLICY fanmilk_backend_full_access ON public."{table_name}" '
            f'FOR ALL TO "fanmilk_backend" USING (true) WITH CHECK (true)'
        )


def test_backend_role_is_quoted_as_an_identifier():
    session = RecordingSession('postgres.project"name')

    enable_row_level_security(session, "postgresql")

    assert 'TO "postgres.project""name"' in session.statements[3]


def test_non_postgresql_databases_are_untouched():
    session = RecordingSession()

    protected = enable_row_level_security(session, "sqlite")

    assert protected == ()
    assert session.statements == []
