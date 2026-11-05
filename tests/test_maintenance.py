import sqlite3
from pathlib import Path
import manage
from test_workflow import app


def test_backup_produces_consistent_database_and_upload_copy(app, tmp_path):
    backup = getattr(manage, "backup", lambda *args: None)(app, tmp_path / "backup")
    assert backup is not None, "maintenance backup is not implemented"
    with sqlite3.connect(Path(backup) / "campus.db") as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 3
    assert len(list((Path(backup) / "uploads").glob("*.jpg"))) == 6
    assert not (Path(backup) / ".secret").exists()


def test_admin_provision_is_explicit_and_password_hashed(app):
    provision = getattr(manage, "provision_admin", lambda *args: None)
    assert (
        provision(app, "admin-new", "AdminStrong123!", "新管理员") is not None
    ), "admin provisioning is not implemented"
    with app.app_context():
        user = (
            app.database()
            .execute("SELECT * FROM users WHERE student_id='admin-new'")
            .fetchone()
        )
        assert user["role"] == "admin"
        assert user["password"] != "AdminStrong123!"
