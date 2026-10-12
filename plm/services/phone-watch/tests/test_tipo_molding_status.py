from phone_watch import db


class CountingConnection:
    def __init__(self, conn):
        self.conn = conn
        self.select_count = 0
        self.queries = []

    def execute(self, sql, params=()):
        if "FROM molding_tipo_records" in sql:
            self.select_count += 1
            self.queries.append(sql)
        return self.conn.execute(sql, params)


def test_tipo_constants():
    assert db.TIPO_PENDING_STATUS in db.VALID_TIPO_STATUSES
    assert db.TIPO_DONE_STATUS in db.VALID_TIPO_STATUSES
    assert len(db.VALID_TIPO_STATUSES) == 2


def test_tipo_table_exists():
    db.init_db()
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='molding_tipo_records'"
        ).fetchall()
        assert len(rows) == 1


def test_upsert_and_query_molding_tipo():
    db.init_db()
    with db.connect() as conn:
        db.upsert_molding_tipo(
            conn,
            brand="MOTOROLA",
            normalized_model="edge50pro",
            source_table="phones",
            source_id=1,
            tipo_name="Tipo Alpha",
            status=db.TIPO_PENDING_STATUS,
        )
        tips = db.molding_tipos_for_model(conn, "MOTOROLA", "edge50pro")
        assert len(tips) == 1
        assert tips[0]["tipo_name"] == "Tipo Alpha"
        assert tips[0]["status"] == db.TIPO_PENDING_STATUS


def test_upsert_molding_tipo_update():
    db.init_db()
    with db.connect() as conn:
        db.upsert_molding_tipo(
            conn,
            brand="MOTOROLA",
            normalized_model="edge50pro",
            source_table="phones",
            source_id=1,
            tipo_name="Tipo Alpha",
            status=db.TIPO_PENDING_STATUS,
        )
        db.upsert_molding_tipo(
            conn,
            brand="MOTOROLA",
            normalized_model="edge50pro",
            source_table="phones",
            source_id=1,
            tipo_name="Tipo Alpha",
            status=db.TIPO_DONE_STATUS,
        )
        tips = db.molding_tipos_for_model(conn, "MOTOROLA", "edge50pro")
        assert len(tips) == 1
        assert tips[0]["status"] == db.TIPO_DONE_STATUS


def test_invalid_tipo_status_raises():
    db.init_db()
    with db.connect() as conn:
        try:
            db.upsert_molding_tipo(
                conn,
                brand="MOTOROLA",
                normalized_model="x",
                source_table="phones",
                source_id=1,
                tipo_name="test",
                status="invalid",
            )
            assert False, "should have raised"
        except ValueError:
            pass


def test_compute_molding_status_no_tipos():
    db.init_db()
    with db.connect() as conn:
        status = db.compute_molding_status(conn, "MOTOROLA", "nonexistent")
        assert status == db.DEFAULT_STATUS


def test_compute_molding_status_partial():
    db.init_db()
    with db.connect() as conn:
        db.upsert_molding_tipo(
            conn,
            brand="MOTOROLA",
            normalized_model="partialtest",
            source_table="phones",
            source_id=1,
            tipo_name="Tipo Alpha",
            status=db.TIPO_DONE_STATUS,
        )
        db.upsert_molding_tipo(
            conn,
            brand="MOTOROLA",
            normalized_model="partialtest",
            source_table="phones",
            source_id=1,
            tipo_name="Tipo Beta",
            status=db.TIPO_PENDING_STATUS,
        )
        status = db.compute_molding_status(conn, "MOTOROLA", "partialtest")
        assert status == db.PARTIAL_MOLDING_STATUS


def test_compute_molding_status_all_done_with_confirm():
    db.init_db()
    with db.connect() as conn:
        db.upsert_molding_tipo(
            conn,
            brand="MOTOROLA",
            normalized_model="alldone",
            source_table="phones",
            source_id=1,
            tipo_name="Tipo Alpha",
            status=db.TIPO_DONE_STATUS,
        )
        status = db.compute_molding_status(
            conn, "MOTOROLA", "alldone", all_required_tipos_done=True
        )
        assert status == db.TIPO_DONE_STATUS


def test_compute_molding_status_no_confirm():
    db.init_db()
    with db.connect() as conn:
        db.upsert_molding_tipo(
            conn,
            brand="MOTOROLA",
            normalized_model="noconfirm",
            source_table="phones",
            source_id=1,
            tipo_name="Tipo Alpha",
            status=db.TIPO_DONE_STATUS,
        )
        status = db.compute_molding_status(conn, "MOTOROLA", "noconfirm")
        assert status == db.PARTIAL_MOLDING_STATUS


def test_molding_tipos_for_models_fetches_many_models_by_brand():
    db.init_db()
    with db.connect() as conn:
        db.upsert_molding_tipo(
            conn,
            brand="MOTOROLA",
            normalized_model="modela",
            source_table="phones",
            source_id=1,
            tipo_name="Tipo A",
            status=db.TIPO_PENDING_STATUS,
        )
        db.upsert_molding_tipo(
            conn,
            brand="SAMSUNG",
            normalized_model="modelb",
            source_table="phones",
            source_id=2,
            tipo_name="Tipo B",
            status=db.TIPO_DONE_STATUS,
        )
        counting = CountingConnection(conn)

        grouped = db.molding_tipos_for_models(
            counting,
            [
                {"brand": "MOTOROLA", "normalized_model": "modela"},
                {"brand": "SAMSUNG", "normalized_model": "modelb"},
            ],
        )

    assert counting.select_count == 2
    assert grouped[("MOTOROLA", "modela")][0]["tipo_name"] == "Tipo A"
    assert grouped[("SAMSUNG", "modelb")][0]["status"] == db.TIPO_DONE_STATUS


def test_molding_tipos_for_models_groups_queries_by_brand_with_in_clause():
    db.init_db()
    with db.connect() as conn:
        for source_id, model in enumerate(("modela", "modelb"), start=1):
            db.upsert_molding_tipo(
                conn,
                brand="VIVO",
                normalized_model=model,
                source_table="phones",
                source_id=source_id,
                tipo_name=f"Tipo {source_id}",
                status=db.TIPO_PENDING_STATUS,
            )
        counting = CountingConnection(conn)

        grouped = db.molding_tipos_for_models(
            counting,
            [
                {"brand": "VIVO", "normalized_model": "modela"},
                {"brand": "VIVO", "normalized_model": "modelb"},
            ],
        )

    assert counting.select_count == 1
    assert "normalized_model IN" in counting.queries[0]
    assert " OR " not in counting.queries[0]
    assert grouped[("VIVO", "modela")][0]["tipo_name"] == "Tipo 1"
    assert grouped[("VIVO", "modelb")][0]["tipo_name"] == "Tipo 2"
