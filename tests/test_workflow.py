import io
from concurrent.futures import ThreadPoolExecutor
import pytest
from PIL import Image
from app import create_app


@pytest.fixture
def app(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "DATABASE": str(tmp_path / "test.db"),
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
            "SECRET_KEY": "test-only",
            "DEMO": True,
        }
    )


def login(app, student="20240001"):
    c = app.test_client()
    r = c.post("/api/login", json={"student_id": student, "password": "Campus2026!"})
    assert r.status_code == 200, r.json
    c.environ_base["HTTP_X_CSRF_TOKEN"] = r.json["csrf_token"]
    return c


def upload(c):
    f = io.BytesIO()
    Image.new("RGB", (40, 50), "blue").save(f, "PNG")
    f.seek(0)
    r = c.post("/api/uploads", data={"file": (f, "book.png")})
    assert r.status_code == 201, r.json
    return r.json["url"]


def publish(c, **overrides):
    data = {
        "course_code": "SE301",
        "title": "软件工程",
        "edition": "第六版",
        "condition": 4,
        "price": "18.50",
        "notes": "少量笔记",
        "images": [upload(c)],
    }
    data.update(overrides)
    return c.post("/api/books", json=data)


def approved(app):
    seller = login(app)
    buyer = login(app, "20240002")
    admin = login(app, "admin")
    r = publish(seller)
    assert r.status_code == 201, r.json
    book = r.json["id"]
    assert (
        admin.post(f"/api/books/{book}/review", json={"approve": True}).status_code
        == 200
    )
    return seller, buyer, admin, book


def reserve(buyer, book):
    r = buyer.post(
        f"/api/books/{book}/reservations",
        json={
            "meeting_time": "2099-11-08T18:00",
            "place": "图书馆一楼",
            "message": "下课后见",
        },
    )
    assert r.status_code == 201, r.json
    return r.json["id"]


def test_account_validation_roles_password_and_csrf(app):
    c = app.test_client()
    assert (
        c.post(
            "/api/register",
            json={
                "student_id": "new123",
                "password": "123",
                "nickname": "同学",
                "college": "计算机学院",
                "class_name": "1班",
            },
        ).status_code
        == 400
    )
    r = c.post(
        "/api/register",
        json={
            "student_id": "new123",
            "password": "StrongPass12!",
            "nickname": "同学",
            "college": "计算机学院",
            "class_name": "1班",
            "role": "admin",
        },
    )
    assert r.status_code == 201
    assert (
        c.post(
            "/api/register",
            json={
                "student_id": "new123",
                "password": "StrongPass12!",
                "nickname": "同学",
                "college": "计算机学院",
                "class_name": "1班",
            },
        ).status_code
        == 409
    )
    c = login(app)
    assert c.get("/api/admin/stats").status_code == 403
    assert (
        c.post(
            "/api/password", json={"old_password": "wrong", "password": "NewPass123!"}
        ).status_code
        == 400
    )
    assert (
        c.post(
            "/api/password",
            json={"old_password": "Campus2026!", "password": "NewPass123!"},
        ).status_code
        == 200
    )
    assert (
        app.test_client()
        .post("/api/login", json={"student_id": "20240001", "password": "Campus2026!"})
        .status_code
        == 401
    )
    c.environ_base.pop("HTTP_X_CSRF_TOKEN")
    assert c.post("/api/logout").status_code == 403


def test_moderation_search_edit_and_upload_validation(app):
    s = login(app)
    a = login(app, "admin")
    assert publish(s, course_code="NOCOURSE").status_code == 400
    assert publish(s, price="-1").status_code == 400
    assert publish(s, images=[]).status_code == 400
    assert (
        s.post(
            "/api/uploads",
            data={"file": (io.BytesIO(b"<script>bad</script>"), "x.png")},
        ).status_code
        == 400
    )
    r = publish(s)
    book = r.json["id"]
    assert book not in [b["id"] for b in s.get("/api/books?q=SE3").json]
    assert (
        a.post(
            f"/api/books/{book}/review", json={"approve": False, "reason": "请补充版次"}
        ).status_code
        == 200
    )
    data = {
        "course_code": "SE301",
        "title": "软件工程修订版",
        "edition": "第六版",
        "condition": 4,
        "price": "18.50",
        "notes": "联系13812345678",
        "images": [upload(s)],
    }
    assert s.put(f"/api/books/{book}", json=data).status_code == 200
    assert (
        a.post(f"/api/books/{book}/review", json={"approve": True}).status_code == 200
    )
    found = s.get(
        "/api/books?q=SE3&college=计算机学院&condition=4&max_price=19&sort=price"
    ).json
    assert book in [b["id"] for b in found]
    assert "13812345678" not in str(found)
    assert book not in [b["id"] for b in s.get("/api/books?free=1").json]
    assert s.put(f"/api/books/{book}", json=data).status_code == 200
    assert book not in [b["id"] for b in s.get("/api/books").json]


def test_handoff_privacy_exclusivity_reviews_credit_and_audit(app):
    s, b, a, book = approved(app)
    assert "contact" not in str(b.get(f"/api/books/{book}").json)
    rid = reserve(b, book)
    assert (
        b.post(
            f"/api/books/{book}/reservations",
            json={"meeting_time": "2099-11-08T18:00", "place": "图书馆"},
        ).status_code
        == 409
    )
    assert (
        b.post(f"/api/reservations/{rid}/action", json={"action": "accept"}).status_code
        == 403
    )
    assert (
        s.post(
            f"/api/reservations/{rid}/action", json={"action": "confirm"}
        ).status_code
        == 409
    )
    assert (
        s.post(f"/api/reservations/{rid}/action", json={"action": "accept"}).status_code
        == 200
    )
    assert b.get("/api/reservations").json[0]["contact"]
    assert (
        s.post(f"/api/reservations/{rid}/action", json={"action": "ready"}).status_code
        == 200
    )
    assert (
        s.post(f"/api/reservations/{rid}/action", json={"action": "confirm"}).json[
            "status"
        ]
        == "confirming"
    )
    assert (
        b.post(f"/api/reservations/{rid}/action", json={"action": "confirm"}).json[
            "status"
        ]
        == "completed"
    )
    assert (
        b.post(
            f"/api/reservations/{rid}/action", json={"action": "confirm"}
        ).status_code
        == 409
    )
    assert b.get("/api/me").json["user"]["credit"] == 102
    assert (
        b.post(
            f"/api/reservations/{rid}/rating",
            json={
                "punctuality": 5,
                "accuracy": 4,
                "communication": 5,
                "tags": "准时",
                "comment": "很棒",
            },
        ).status_code
        == 201
    )
    assert (
        b.post(
            f"/api/reservations/{rid}/rating",
            json={"punctuality": 5, "accuracy": 4, "communication": 5},
        ).status_code
        == 409
    )
    assert a.get("/api/admin/stats").json["completed"] == 1
    assert any(x["action"] == "confirm" for x in a.get("/api/admin/logs").json)


def test_cancel_report_appeal_and_admin_resolution(app):
    s, b, a, book = approved(app)
    rid = reserve(b, book)
    assert (
        b.post(
            f"/api/reservations/{rid}/action",
            json={"action": "cancel", "reason": "时间有冲突"},
        ).status_code
        == 200
    )
    assert b.get("/api/me").json["user"]["cancellations"] == 1
    rid = reserve(b, book)
    assert (
        s.post(f"/api/reservations/{rid}/action", json={"action": "accept"}).status_code
        == 200
    )
    assert (
        b.post(
            f"/api/reservations/{rid}/action",
            json={"action": "appeal", "reason": "对方爽约，请核实"},
        ).json["status"]
        == "disputed"
    )
    assert (
        a.post(
            f"/api/reservations/{rid}/resolve",
            json={
                "outcome": "no_show",
                "responsible_id": s.get("/api/me").json["user"]["id"],
                "reason": "核实聊天记录",
            },
        ).status_code
        == 200
    )
    assert s.get("/api/me").json["user"]["credit"] == 90
    r = b.post("/api/reports", json={"book_id": book, "reason": "教材信息不实"})
    assert r.status_code == 201
    assert (
        a.post(
            "/api/reports/" + str(r.json["id"]) + "/resolve",
            json={"upheld": True, "reason": "核实成立", "takedown": True},
        ).status_code
        == 200
    )
    assert s.get("/api/me").json["user"]["credit"] == 80
    assert book not in [x["id"] for x in b.get("/api/books").json]


def test_course_csv_config_profile_and_permissions(app):
    a = login(app, "admin")
    s = login(app)
    b = login(app, "20240002")
    assert (
        a.post(
            "/api/admin/courses/import",
            json={
                "csv": "code,name,college,textbook\nMA101,高等数学,理学院,高等数学第七版"
            },
        ).status_code
        == 200
    )
    assert any(c["code"] == "MA101" for c in s.get("/api/courses").json)
    assert (
        a.put(
            "/api/admin/settings",
            json={
                "min_credit": 101,
                "complete_bonus": 3,
                "report_penalty": 10,
                "no_show_penalty": 12,
                "confirm_hours": 48,
            },
        ).status_code
        == 200
    )
    assert publish(s).status_code == 403
    assert (
        s.put(
            "/api/profile",
            json={
                "nickname": "新昵称",
                "college": "理学院",
                "class_name": "数学1班",
                "contact": "wx-demo",
            },
        ).status_code
        == 200
    )
    assert s.get("/api/me").json["user"]["nickname"] == "新昵称"
    assert b.get("/api/admin/logs").status_code == 403
    assert a.get("/api/admin/export").status_code == 200


def test_concurrent_reservation_one_winner(app):
    s, b, a, book = approved(app)
    c = app.test_client()
    c.post(
        "/api/register",
        json={
            "student_id": "20240003",
            "password": "Campus2026!",
            "nickname": "第三位",
            "college": "计算机学院",
            "class_name": "1班",
        },
    )

    def attempt(student):
        client = login(app, student)
        return client.post(
            f"/api/books/{book}/reservations",
            json={"meeting_time": "2099-11-08T18:00", "place": "图书馆"},
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, ["20240002", "20240003"])) == [201, 409]
