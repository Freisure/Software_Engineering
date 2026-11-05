"""Explicit admin provisioning, transaction-safe backup and timeout maintenance."""

import argparse
import getpass
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from werkzeug.security import generate_password_hash
from app import create_app


def backup(app, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    # SQLite online backup captures a consistent committed snapshot, including WAL.
    with sqlite3.connect(app.config["DATABASE"]) as source:
        with sqlite3.connect(destination / "campus.db") as target:
            source.backup(target)
    shutil.copytree(app.config["UPLOAD_FOLDER"], destination / "uploads")
    (destination / "RESTORE.txt").write_text(
        "Stop the app. Copy campus.db and uploads into instance/. Keep the existing .secret or allow generation of a new one (all sessions will be invalidated). Do not restore over an active database. Remove obsolete campus.db-wal and campus.db-shm only after the server is stopped.\n",
        encoding="utf-8",
    )
    return destination


def provision_admin(app, student_id, password, nickname):
    if (
        not re.fullmatch(r"[A-Za-z0-9_-]{4,24}", student_id)
        or not 8 <= len(password) <= 128
        or not nickname.strip()
    ):
        raise ValueError("Invalid ID, password length (8-128), or nickname.")
    with app.app_context():
        db = app.database()
        db.execute("BEGIN IMMEDIATE")
        try:
            uid = db.execute(
                "INSERT INTO users(student_id,password,nickname,college,class_name,role) VALUES(?,?,?,'管理员','管理员','admin')",
                (student_id, generate_password_hash(password), nickname.strip()),
            ).lastrowid
            db.execute(
                "INSERT INTO logs(action,entity,entity_id,detail) VALUES('provision_admin','user',?,'Explicit local maintenance command')",
                (str(uid),),
            )
            db.commit()
            return uid
        except Exception:
            db.rollback()
            raise


def main():
    parser = argparse.ArgumentParser(description="Campus textbook maintenance")
    commands = parser.add_subparsers(dest="command", required=True)
    admin = commands.add_parser("create-admin")
    admin.add_argument("student_id")
    admin.add_argument("--name", default="学院管理员")
    backup_parser = commands.add_parser("backup")
    backup_parser.add_argument("--output")
    commands.add_parser("expire")
    args = parser.parse_args()
    app = create_app()
    if args.command == "create-admin":
        password = getpass.getpass("New admin password (8+ characters): ")
        if password != getpass.getpass("Repeat password: "):
            raise SystemExit("Passwords do not match")
        print(
            "Created administrator ID:",
            provision_admin(app, args.student_id, password, args.name),
        )
    elif args.command == "backup":
        destination = args.output or str(
            Path(__file__).parent
            / "backups"
            / datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        )
        print("Backup saved:", backup(app, destination))
    else:
        with app.app_context():
            db = app.database()
            db.execute("BEGIN IMMEDIATE")
            try:
                app.process_timeouts()
                db.commit()
            except Exception:
                db.rollback()
                raise
        print("Timeout processing complete")


if __name__ == "__main__":
    main()
