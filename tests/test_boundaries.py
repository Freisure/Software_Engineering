from test_workflow import app, login, approved, reserve, publish


def test_timeout_is_audited_and_can_be_resolved_once(app):
    s, b, a, bid = approved(app)
    rid = reserve(b, bid)
    s.post(f"/api/reservations/{rid}/action", json={"action": "accept"})
    s.post(f"/api/reservations/{rid}/action", json={"action": "ready"})
    s.post(f"/api/reservations/{rid}/action", json={"action": "confirm"})
    with app.app_context():
        app.database().execute(
            "UPDATE reservations SET updated_at='2000-01-01 00:00:00' WHERE id=?",
            (rid,),
        )
    assert b.get("/api/reservations").json[0]["status"] == "disputed"
    assert (
        a.post(
            f"/api/reservations/{rid}/resolve",
            json={"outcome": "completed", "reason": "核实已交接"},
        ).status_code
        == 200
    )
    assert (
        a.post(
            f"/api/reservations/{rid}/resolve",
            json={"outcome": "completed", "reason": "再次确认"},
        ).status_code
        == 409
    )
    assert b.get("/api/me").json["user"]["credit"] == 102
    assert any(x["action"] == "timeout" for x in a.get("/api/admin/logs").json)


def test_import_rolls_back_all_rows_and_upload_ownership(app):
    s, b, a, bid = approved(app)
    result = a.post(
        "/api/admin/courses/import",
        json={
            "csv": "code,name,college,textbook\nNEW01,新课程,理学院,新书\nBAD!,错误课程,理学院,书"
        },
    )
    assert result.status_code == 400
    assert not any(c["code"] == "NEW01" for c in a.get("/api/courses").json)
    images = s.get(f"/api/books/{bid}").json["images"]
    assert publish(b, images=images).status_code == 400
    assert b.post(f"/api/books/{bid}/withdraw").status_code == 403


def test_login_lockout_and_password_invalidates_other_sessions(app):
    first = login(app)
    second = login(app)
    first.post(
        "/api/password", json={"old_password": "Campus2026!", "password": "NewPass123!"}
    )
    assert second.get("/api/me").json["user"] is None
    c = app.test_client()
    for _ in range(10):
        assert (
            c.post(
                "/api/login", json={"student_id": "20240002", "password": "wrongpass"}
            ).status_code
            == 401
        )
    assert (
        c.post(
            "/api/login", json={"student_id": "20240002", "password": "Campus2026!"}
        ).status_code
        == 429
    )


def test_report_appeal_reverses_credit_only_once(app):
    s, b, a, bid = approved(app)
    report = b.post(
        "/api/reports", json={"book_id": bid, "reason": "疑似描述不符"}
    ).json["id"]
    a.post(
        f"/api/reports/{report}/resolve",
        json={"upheld": True, "reason": "初步核实", "takedown": True},
    )
    assert s.get("/api/me").json["user"]["credit"] == 90
    assert (
        s.post(
            f"/api/reports/{report}/appeal", json={"reason": "补充完整原始照片，请复核"}
        ).status_code
        == 201
    )
    appeal = a.get("/api/reports").json[0]["id"]
    assert (
        a.post(
            f"/api/reports/{appeal}/resolve",
            json={"upheld": True, "reason": "新证据成立，撤销原处罚"},
        ).status_code
        == 200
    )
    assert s.get("/api/me").json["user"]["credit"] == 100
    assert (
        a.post(
            f"/api/reports/{appeal}/resolve", json={"upheld": True, "reason": "重复"}
        ).status_code
        == 409
    )
    assert (
        s.post(f"/api/reports/{report}/appeal", json={"reason": "再退款"}).status_code
        == 409
    )
