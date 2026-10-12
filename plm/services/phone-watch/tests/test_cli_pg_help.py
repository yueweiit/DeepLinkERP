from phone_watch.cli import build_parser


def test_top_level_help_describes_sqlite_and_postgres_backends():
    help_text = build_parser().format_help()

    assert "SQLite/PostgreSQL" in help_text
    assert "SQLite 入库" not in help_text


def test_db_argument_help_is_limited_to_sqlite_mode():
    help_text = build_parser().format_help()

    assert "--db DB" in help_text
    assert "仅 SQLite 后端使用" in help_text
