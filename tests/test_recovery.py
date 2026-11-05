import email
import email.policy
import re
from pathlib import Path

import pytest

from app import create_app


@pytest.fixture
def app(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "DATABASE": str(tmp_path / "test.db"),
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
            "OUTBOX": str(tmp_path / "outbox"),
            "SECRET_KEY": "test-only",
            "DEMO": True,
        }
    )


def login(app, student="20240001", password="Campus2026!"):
    c = app.test_client()
    r = c.post("/api/login", json={"student_id": student, "password": password})
    assert r.status_code == 200, r.json
    c.environ_base["HTTP_X_CSRF_TOKEN"] = r.json["csrf_token"]
    return c


def outbox(app):
    folder = Path(app.config["OUTBOX"])
    return [p.read_bytes() for p in sorted(folder.glob("*.eml"))]


def last_mail_body(app):
    return email.message_from_bytes(
        outbox(app)[-1], policy=email.policy.default
    ).get_content()


def mailed_code(app):
    return re.search(r"\b(\d{6})\b", last_mail_body(app)).group(1)


def bind_email(c, address="alice@example.com"):
    assert c.post("/api/email/request", json={"email": address}).status_code == 200
    r = c.post("/api/email/confirm", json={"email": address, "code": mailed_code(c.application)})
    assert r.status_code == 200, r.json
    return address


def test_email_binding_requires_the_mailed_code(app):
    c = login(app)
    assert c.get("/api/me").json["user"]["email_bound"] is False

    assert c.post("/api/email/request", json={"email": "not-an-email"}).status_code == 400
    r = c.post("/api/email/request", json={"email": "Alice@Example.com"})
    assert r.status_code == 200
    # No SMTP in tests: the mail lands in the outbox and the caller is told so.
    assert r.json["channel"] == "outbox"
    assert r.json["mail"].endswith(".eml")
    assert c.get("/api/me").json["user"]["email_bound"] is False

    r = c.post("/api/email/confirm", json={"email": "alice@example.com", "code": "000000"})
    assert r.status_code == 400
    assert r.json["error"] == "验证码不正确"

    r = c.post("/api/email/confirm", json={"email": "alice@example.com", "code": mailed_code(app)})
    assert r.status_code == 200, r.json
    me = c.get("/api/me").json["user"]
    assert me["email_bound"] is True
    assert me["email"] == "a****@example.com"


def test_password_reset_end_to_end(app):
    c = login(app)
    bind_email(c)
    assert len(outbox(app)) == 1

    # Unknown student: same reply, no mail, no account leak.
    assert c.post("/api/password/forgot", json={"student_id": "20999999"}).json == {"ok": True}
    assert len(outbox(app)) == 1

    assert c.post("/api/password/forgot", json={"student_id": "20240001"}).status_code == 200
    token = re.search(r"#reset/([\w\-]+)", last_mail_body(app)).group(1)

    r = c.post("/api/password/reset", json={"token": token, "password": "new-pass-2026"})
    assert r.status_code == 200, r.json

    # The session that asked for the reset is invalidated too.
    assert c.get("/api/me").json["user"] is None

    anonymous = app.test_client()
    assert anonymous.post(
        "/api/login", json={"student_id": "20240001", "password": "Campus2026!"}
    ).status_code == 401
    assert anonymous.post(
        "/api/login", json={"student_id": "20240001", "password": "new-pass-2026"}
    ).status_code == 200

    # One-shot: the same link cannot be replayed.
    assert anonymous.post(
        "/api/password/reset", json={"token": token, "password": "another-pass"}
    ).status_code == 400


def test_email_can_be_unbound_with_the_password(app):
    c = login(app)
    bind_email(c)

    assert c.post("/api/email/unbind", json={"password": "wrong-pass"}).status_code == 403
    assert c.post("/api/email/unbind", json={"password": "Campus2026!"}).status_code == 200
    me = c.get("/api/me").json["user"]
    assert me["email_bound"] is False
    assert me["email"] == ""

    # Unbound accounts get no reset mail, and the reply stays generic.
    before = len(outbox(app))
    assert c.post("/api/password/forgot", json={"student_id": "20240001"}).json == {"ok": True}
    assert len(outbox(app)) == before


def test_account_deletion_releases_the_student_id(app):
    c = login(app)
    bind_email(c)

    assert c.post("/api/account/delete", json={"password": "wrong-pass"}).status_code == 403
    r = c.post("/api/account/delete", json={"password": "Campus2026!"})
    assert r.status_code == 200, r.json
    assert c.get("/api/me").json["user"] is None

    anonymous = app.test_client()
    assert anonymous.post(
        "/api/login", json={"student_id": "20240001", "password": "Campus2026!"}
    ).status_code == 401

    # The student id is free again, while old rows stay as 已注销用户.
    r = anonymous.post(
        "/api/register",
        json={
            "student_id": "20240001",
            "password": "fresh-pass-2026",
            "nickname": "新同学",
            "college": "计算机学院",
            "class_name": "软工2301",
        },
    )
    assert r.status_code == 201, r.json
    assert anonymous.post(
        "/api/login", json={"student_id": "20240001", "password": "fresh-pass-2026"}
    ).status_code == 200
