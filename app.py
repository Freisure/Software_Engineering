"""书循环：transaction-backed campus textbook exchange."""

import csv
import io
import json
import os
import re
import secrets
import sqlite3
import time
import warnings
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps
from pathlib import Path
from flask import Flask, g, jsonify, request, session, send_from_directory, Response
from PIL import Image, UnidentifiedImageError
from werkzeug.exceptions import HTTPException
from werkzeug.security import generate_password_hash, check_password_hash

ROOT = Path(__file__).parent
DEFAULTS = {
    "min_credit": 60,
    "complete_bonus": 2,
    "report_penalty": 10,
    "no_show_penalty": 10,
    "confirm_hours": 48,
}


class BusinessError(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


def require(condition, message, status=400):
    if not condition:
        raise BusinessError(message, status)


def data():
    d = request.get_json(silent=True)
    require(isinstance(d, dict), "请提交有效的表单数据")
    return d


def field(d, name, label=None, maximum=200, optional=False):
    v = d.get(name, "")
    require(isinstance(v, str), f"{label or name}格式不正确")
    v = v.strip()
    require(
        (optional or bool(v)) and len(v) <= maximum,
        f"{label or name}不能为空且不能超过{maximum}字",
    )
    return v


def integer(v, low, high, label):
    require(not isinstance(v, bool) and str(v).isdigit(), f"{label}必须为整数")
    v = int(v)
    require(low <= v <= high, f"{label}须在{low}至{high}之间")
    return v


def redact(text):
    text = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[联系方式已隐藏]", text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[联系方式已隐藏]", text)
    return re.sub(
        r"(?i)(微信|wechat|wx|QQ|电话|手机|联系)\s*[:：]?\s*[a-zA-Z0-9_+\-]{4,}",
        "[联系方式已隐藏]",
        text,
    )


def create_app(config=None):
    app = Flask(__name__, static_folder="static")
    instance = ROOT / "instance"
    app.config.update(
        DATABASE=str(instance / "campus.db"),
        UPLOAD_FOLDER=str(instance / "uploads"),
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        DEMO=os.environ.get("CAMPUS_DEMO") == "1",
        MAX_CONTENT_LENGTH=6 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    )
    app.config.update(config or {})
    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    if not app.config["SECRET_KEY"]:
        key = Path(app.config["DATABASE"]).parent / ".secret"
        if not key.exists():
            key.write_text(secrets.token_hex(32), encoding="utf-8")
        app.config["SECRET_KEY"] = key.read_text(encoding="utf-8")

    def db():
        if "db" not in g:
            g.db = sqlite3.connect(
                app.config["DATABASE"], timeout=15, isolation_level=None
            )
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys=ON")
        return g.db

    def row(sql, args=()):
        r = db().execute(sql, args).fetchone()
        return dict(r) if r else None

    def rows(sql, args=()):
        return [dict(r) for r in db().execute(sql, args).fetchall()]

    def log(action, entity, eid, detail=""):
        db().execute(
            "INSERT INTO logs(actor_id,action,entity,entity_id,detail) VALUES(?,?,?,?,?)",
            (g.user["id"] if g.get("user") else None, action, entity, str(eid), detail),
        )

    def notify(uid, message):
        db().execute(
            "INSERT INTO notifications(user_id,message) VALUES(?,?)", (uid, message)
        )

    def settings():
        return {r["key"]: r["value"] for r in rows("SELECT * FROM settings")}

    def auth(admin=False):
        def decorate(fn):
            @wraps(fn)
            def wrapped(*args, **kwargs):
                require(g.user is not None, "请先登录", 401)
                require(
                    not admin or g.user["role"] == "admin", "仅管理员可执行此操作", 403
                )
                return fn(*args, **kwargs)

            return wrapped

        return decorate

    @app.before_request
    def begin():
        g.user = None
        if not request.path.startswith("/api/"):
            return
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            db().execute("BEGIN IMMEDIATE")
        if session.get("uid"):
            g.user = row("SELECT * FROM users WHERE id=?", (session["uid"],))
            if not g.user or session.get("version") != g.user["auth_version"]:
                g.user = None
                session.clear()
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get("Origin"):
                require(
                    request.headers["Origin"] == request.host_url.rstrip("/"),
                    "请求来源不匹配",
                    403,
                )
            if request.path not in ("/api/login", "/api/register"):
                require(g.user is not None, "请先登录", 401)
                token = request.headers.get("X-CSRF-Token", "")
                require(
                    bool(token)
                    and secrets.compare_digest(token, session.get("csrf", "")),
                    "页面凭证已过期，请刷新后重试",
                    403,
                )

    @app.after_request
    def finish(response):
        connection = g.get("db")
        if connection and connection.in_transaction:
            connection.commit() if response.status_code < 400 else connection.rollback()
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        )
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.teardown_appcontext
    def close(error):
        if "db" in g:
            g.db.close()

    @app.errorhandler(BusinessError)
    def business_error(e):
        return jsonify(error=e.message), e.status

    @app.errorhandler(sqlite3.IntegrityError)
    def conflict(e):
        return jsonify(error="信息重复或该教材已有有效预约，请刷新后重试"), 409

    @app.errorhandler(HTTPException)
    def http_error(e):
        return (
            jsonify(error="每张图片最多5MB" if e.code == 413 else e.description),
            e.code,
        )

    def public_user(user):
        return {
            k: v
            for k, v in user.items()
            if k not in ("password", "auth_version", "sso_id")
        }

    def establish(user):
        session.clear()
        session.update(
            uid=user["id"], version=user["auth_version"], csrf=secrets.token_hex(24)
        )
        session.permanent = True
        return {"user": public_user(user), "csrf_token": session["csrf"]}

    @app.get("/")
    def home():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/api/me")
    def me():
        return jsonify(
            user=public_user(g.user) if g.user else None,
            csrf_token=session.get("csrf"),
            demo=app.config["DEMO"],
        )

    @app.post("/api/register")
    def register():
        d = data()
        sid = field(d, "student_id", "学号", 24)
        require(
            re.fullmatch(r"[A-Za-z0-9_-]{4,24}", sid),
            "学号须为4至24位字母、数字或下划线",
        )
        password = field(d, "password", "密码", 128)
        require(len(password) >= 8, "密码至少8位")
        uid = (
            db()
            .execute(
                "INSERT INTO users(student_id,password,nickname,college,class_name) VALUES(?,?,?,?,?)",
                (
                    sid,
                    generate_password_hash(password),
                    field(d, "nickname", "昵称", 30),
                    field(d, "college", "学院", 50),
                    field(d, "class_name", "班级", 50),
                ),
            )
            .lastrowid
        )
        log("register", "user", uid)
        return jsonify(id=uid), 201

    @app.post("/api/login")
    def login():
        d = data()
        sid = field(d, "student_id", "学号", 24)
        password = field(d, "password", "密码", 128)
        identity = f"{request.remote_addr}:{sid}"
        attempt = row("SELECT * FROM login_attempts WHERE identity=?", (identity,))
        require(
            not attempt
            or attempt["failures"] < 10
            or time.time() - attempt["last_attempt"] > 600,
            "尝试过于频繁，请10分钟后重试",
            429,
        )
        user = row("SELECT * FROM users WHERE student_id=?", (sid,))
        if not user or not check_password_hash(user["password"], password):
            failures = (
                attempt["failures"] + 1
                if attempt and time.time() - attempt["last_attempt"] < 600
                else 1
            )
            db().execute(
                "INSERT OR REPLACE INTO login_attempts VALUES(?,?,?)",
                (identity, failures, time.time()),
            )
            db().commit()
            raise BusinessError("学号或密码错误", 401)
        db().execute("DELETE FROM login_attempts WHERE identity=?", (identity,))
        return jsonify(establish(user))

    @app.post("/api/logout")
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.put("/api/profile")
    @auth()
    def profile():
        d = data()
        db().execute(
            "UPDATE users SET nickname=?,college=?,class_name=?,contact=? WHERE id=?",
            (
                field(d, "nickname", "昵称", 30),
                field(d, "college", "学院", 50),
                field(d, "class_name", "班级", 50),
                field(d, "contact", "联系方式", 100, True),
                g.user["id"],
            ),
        )
        log("profile", "user", g.user["id"])
        return jsonify(ok=True)

    @app.post("/api/password")
    @auth()
    def password():
        d = data()
        require(
            check_password_hash(
                g.user["password"], field(d, "old_password", "原密码", 128)
            ),
            "原密码错误",
        )
        new = field(d, "password", "新密码", 128)
        require(len(new) >= 8, "密码至少8位")
        db().execute(
            "UPDATE users SET password=?,auth_version=auth_version+1 WHERE id=?",
            (generate_password_hash(new), g.user["id"]),
        )
        session["version"] = g.user["auth_version"] + 1
        log("password", "user", g.user["id"])
        return jsonify(ok=True)

    @app.get("/api/courses")
    def courses():
        return jsonify(rows("SELECT * FROM courses ORDER BY code"))

    @app.post("/api/uploads")
    @auth()
    def upload():
        file = request.files.get("file")
        require(file is not None, "请选择图片")
        content = file.read(5 * 1024 * 1024 + 1)
        require(len(content) <= 5 * 1024 * 1024, "每张图片最多5MB")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                picture = Image.open(io.BytesIO(content))
                require(
                    picture.format in ("JPEG", "PNG", "WEBP"),
                    "仅支持JPEG、PNG、WebP图片",
                )
                picture.load()
                picture = picture.convert("RGB")
                picture.thumbnail((1600, 1600))
        except (
            UnidentifiedImageError,
            OSError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ):
            raise BusinessError("文件不是有效图片")
        name = secrets.token_hex(16) + ".jpg"
        picture.save(Path(app.config["UPLOAD_FOLDER"]) / name, "JPEG", quality=85)
        url = "/uploads/" + name
        db().execute("INSERT INTO uploads VALUES(?,?)", (url, g.user["id"]))
        return jsonify(url=url), 201

    @app.get("/uploads/<name>")
    def image_file(name):
        return send_from_directory(app.config["UPLOAD_FOLDER"], name)

    def book_record(bid):
        b = row(
            "SELECT b.*,u.nickname,u.credit,c.name AS course_name,c.college,c.textbook FROM books b JOIN users u ON u.id=b.owner_id JOIN courses c ON c.code=b.course_code WHERE b.id=?",
            (bid,),
        )
        require(b, "教材不存在", 404)
        b["images"] = json.loads(b["images"])
        return b

    def can_manage(b):
        require(b["owner_id"] == g.user["id"], "只能修改自己发布的教材", 403)
        require(b["status"] != "completed", "已交接教材不能修改", 409)
        require(
            not row(
                "SELECT id FROM reservations WHERE book_id=? AND status IN ('pending','accepted','ready','confirming','disputed')",
                (b["id"],),
            ),
            "教材有有效预约，不能修改或下架",
            409,
        )

    def book_data(d):
        code = field(d, "course_code", "课程代码", 30).upper()
        require(
            row("SELECT code FROM courses WHERE code=?", (code,)),
            "请选择有效的课程代码",
        )
        try:
            amount = Decimal(str(d.get("price", "")))
            require(
                amount.is_finite()
                and 0 <= amount <= 10000
                and amount * 100 == (amount * 100).to_integral_value(),
                "价格须为0至10000元且最多两位小数",
            )
        except InvalidOperation:
            raise BusinessError("请输入正确的价格")
        images = d.get("images", [])
        require(isinstance(images, list) and 1 <= len(images) <= 3, "请上传1至3张图片")
        for url in images:
            require(
                isinstance(url, str)
                and row(
                    "SELECT url FROM uploads WHERE url=? AND owner_id=?",
                    (url, g.user["id"]),
                ),
                "请使用本人上传的有效图片",
            )
        title = redact(field(d, "title", "教材名称", 100))
        notes = redact(field(d, "notes", "备注", 1000, True))
        require(
            not any(w in title + notes for w in ("代考", "枪支", "毒品")),
            "内容包含禁止发布的词语",
        )
        return (
            code,
            title,
            redact(field(d, "edition", "版次", 50, True)),
            field(d, "isbn", "ISBN", 30, True),
            integer(d.get("condition"), 1, 5, "成色"),
            int(amount * 100),
            notes,
            json.dumps(images),
        )

    @app.post("/api/books")
    @auth()
    def publish():
        require(
            g.user["credit"] >= settings()["min_credit"],
            "信用分不足，暂不能发布，请联系管理员申诉",
            403,
        )
        bid = (
            db()
            .execute(
                "INSERT INTO books(owner_id,course_code,title,edition,isbn,condition,price,notes,images) VALUES(?,?,?,?,?,?,?,?,?)",
                (g.user["id"], *book_data(data())),
            )
            .lastrowid
        )
        log("publish", "book", bid)
        return jsonify(id=bid), 201

    @app.put("/api/books/<int:bid>")
    @auth()
    def edit_book(bid):
        can_manage(book_record(bid))
        db().execute(
            "UPDATE books SET course_code=?,title=?,edition=?,isbn=?,condition=?,price=?,notes=?,images=?,status='pending',review_reason='' WHERE id=?",
            (*book_data(data()), bid),
        )
        log("edit_resubmit", "book", bid)
        return jsonify(ok=True)

    @app.post("/api/books/<int:bid>/withdraw")
    @auth()
    def withdraw(bid):
        can_manage(book_record(bid))
        db().execute("UPDATE books SET status='withdrawn' WHERE id=?", (bid,))
        log("withdraw", "book", bid)
        return jsonify(ok=True)

    @app.post("/api/books/<int:bid>/review")
    @auth(True)
    def review(bid):
        b = book_record(bid)
        require(b["status"] == "pending", "该教材不在待审核状态", 409)
        d = data()
        require(type(d.get("approve")) is bool, "请选择通过或驳回")
        reason = field(d, "reason", "审核理由", 500, d["approve"])
        status = "approved" if d["approve"] else "rejected"
        db().execute(
            "UPDATE books SET status=?,review_reason=? WHERE id=?",
            (status, reason, bid),
        )
        log("review", "book", bid, status + ": " + reason)
        notify(
            b["owner_id"],
            f'《{b["title"]}》审核' + ("通过" if d["approve"] else "驳回：" + reason),
        )
        return jsonify(ok=True)

    @app.get("/api/books")
    def books():
        q = request.args
        where = ["b.status='approved'"]
        args = []
        if q.get("mine") == "1":
            require(g.user, "请先登录", 401)
            where = ["b.owner_id=?"]
            args = [g.user["id"]]
        elif q.get("moderation") == "1":
            require(g.user and g.user["role"] == "admin", "仅管理员可查看", 403)
            where = ["b.status='pending'"]
        else:
            where.append(
                "NOT EXISTS(SELECT 1 FROM reservations r WHERE r.book_id=b.id AND r.status IN ('pending','accepted','ready','confirming','disputed'))"
            )
        if q.get("q"):
            where.append("(b.course_code LIKE ? OR b.title LIKE ? OR c.name LIKE ?)")
            args.extend(["%" + q["q"].strip() + "%"] * 3)
        for key, col in [("college", "c.college"), ("course", "b.course_code")]:
            if q.get(key):
                where.append(col + "=?")
                args.append(q[key])
        if q.get("condition"):
            where.append("b.condition>=?")
            args.append(integer(q["condition"], 1, 5, "成色"))
        for key, op in [("min_price", ">="), ("max_price", "<=")]:
            if q.get(key):
                try:
                    amount = Decimal(q[key])
                    require(amount.is_finite() and amount >= 0, "价格筛选不正确")
                except InvalidOperation:
                    raise BusinessError("价格筛选不正确")
                where.append("b.price" + op + "?")
                args.append(int(amount * 100))
        if q.get("free") == "1":
            where.append("b.price=0")
        order = {
            "price": "b.price ASC,b.id DESC",
            "condition": "b.condition DESC,b.id DESC",
        }.get(q.get("sort"), "b.id DESC")
        result = rows(
            "SELECT b.*,c.name AS course_name,c.college,c.textbook,u.nickname,u.credit FROM books b JOIN courses c ON c.code=b.course_code JOIN users u ON u.id=b.owner_id WHERE "
            + " AND ".join(where)
            + " ORDER BY "
            + order,
            args,
        )
        for b in result:
            b["images"] = json.loads(b["images"])
        return jsonify(result)

    @app.get("/api/books/<int:bid>")
    def book_detail(bid):
        b = book_record(bid)
        require(
            b["status"] in ("approved", "completed")
            or (
                g.user and (g.user["id"] == b["owner_id"] or g.user["role"] == "admin")
            ),
            "教材暂不可见",
            404,
        )
        b["ratings"] = rows(
            "SELECT r.punctuality,r.accuracy,r.communication,r.tags,r.comment,u.nickname FROM ratings r JOIN users u ON u.id=r.author_id WHERE r.target_id=? AND r.deleted=0 ORDER BY r.id DESC LIMIT 20",
            (b["owner_id"],),
        )
        return jsonify(b)

    def reservation_record(rid):
        r = row(
            "SELECT r.*,b.owner_id,b.title FROM reservations r JOIN books b ON b.id=r.book_id WHERE r.id=?",
            (rid,),
        )
        require(r, "预约不存在", 404)
        return r

    @app.post("/api/books/<int:bid>/reservations")
    @auth()
    def reserve(bid):
        b = book_record(bid)
        d = data()
        require(b["owner_id"] != g.user["id"], "不能预约自己的教材")
        require(b["status"] == "approved", "教材当前不可预约", 409)
        require(
            g.user["credit"] >= settings()["min_credit"], "信用分不足，暂不能预约", 403
        )
        meeting = field(d, "meeting_time", "交接时间", 30)
        try:
            parsed = datetime.fromisoformat(meeting)
        except ValueError:
            raise BusinessError("交接时间格式不正确")
        require(
            parsed.tzinfo is None
            and parsed
            > datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None),
            "请选择未来的交接时间（北京时间）",
        )
        rid = (
            db()
            .execute(
                "INSERT INTO reservations(book_id,buyer_id,meeting_time,place,message) VALUES(?,?,?,?,?)",
                (
                    bid,
                    g.user["id"],
                    meeting,
                    redact(field(d, "place", "交接地点", 100)),
                    redact(field(d, "message", "留言", 500, True)),
                ),
            )
            .lastrowid
        )
        log("reserve", "reservation", rid)
        notify(b["owner_id"], f'《{b["title"]}》收到新预约')
        return jsonify(id=rid), 201

    def expire():
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=settings()["confirm_hours"])
        ).strftime("%Y-%m-%d %H:%M:%S")
        for r in rows(
            "SELECT * FROM reservations WHERE status='confirming' AND updated_at<?",
            (cutoff,),
        ):
            db().execute(
                "UPDATE reservations SET status='disputed',reason='双方确认超时',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (r["id"],),
            )
            log("timeout", "reservation", r["id"])
            notify(r["buyer_id"], "预约确认超时，已进入待处理")

    @app.get("/api/reservations")
    @auth()
    def reservations():
        db().execute("BEGIN IMMEDIATE")
        expire()
        if g.user["role"] == "admin" and request.args.get("disputes") == "1":
            result = rows(
                "SELECT r.*,b.owner_id,b.title FROM reservations r JOIN books b ON b.id=r.book_id WHERE r.status='disputed' ORDER BY r.id DESC"
            )
        else:
            result = rows(
                "SELECT r.*,b.owner_id,b.title FROM reservations r JOIN books b ON b.id=r.book_id WHERE r.buyer_id=? OR b.owner_id=? ORDER BY r.id DESC",
                (g.user["id"], g.user["id"]),
            )
        for r in result:
            other = r["buyer_id"] if r["owner_id"] == g.user["id"] else r["owner_id"]
            u = row("SELECT nickname,contact FROM users WHERE id=?", (other,))
            r["other_name"] = u["nickname"]
            if g.user["id"] in (r["buyer_id"], r["owner_id"]) and r["status"] in (
                "accepted",
                "ready",
                "confirming",
                "completed",
                "disputed",
            ):
                r["contact"] = u["contact"]
            r["rated"] = bool(
                row(
                    "SELECT id FROM ratings WHERE reservation_id=? AND author_id=?",
                    (r["id"], g.user["id"]),
                )
            )
        return jsonify(result)

    def complete(r):
        db().execute("UPDATE books SET status='completed' WHERE id=?", (r["book_id"],))
        db().execute(
            "UPDATE users SET credit=MIN(200,credit+?) WHERE id IN (?,?)",
            (settings()["complete_bonus"], r["owner_id"], r["buyer_id"]),
        )

    @app.post("/api/reservations/<int:rid>/action")
    @auth()
    def reservation_action(rid):
        r = reservation_record(rid)
        d = data()
        action = d.get("action")
        uid = g.user["id"]
        require(uid in (r["owner_id"], r["buyer_id"]), "无权操作他人的预约", 403)
        status = r["status"]
        reason = field(d, "reason", "原因", 500, True)
        if action in ("accept", "reject"):
            require(uid == r["owner_id"], "仅发布者可处理预约", 403)
            require(status == "pending", "预约已处理", 409)
            if action == "reject":
                require(reason, "请填写拒绝原因")
            status = "accepted" if action == "accept" else "cancelled"
        elif action == "ready":
            require(status == "accepted", "只有已预约状态才能开始交接", 409)
            status = "ready"
        elif action == "confirm":
            require(
                status in ("ready", "confirming"), "请先开始交接，再由双方确认", 409
            )
            key = "seller_confirm" if uid == r["owner_id"] else "buyer_confirm"
            require(not r[key], "你已经确认过交接", 409)
            r[key] = 1
            db().execute("UPDATE reservations SET " + key + "=1 WHERE id=?", (rid,))
            status = (
                "completed"
                if r["seller_confirm"] and r["buyer_confirm"]
                else "confirming"
            )
            if status == "completed":
                complete(r)
        elif action == "cancel":
            require(
                status in ("pending", "accepted"),
                "开始交接后需申诉处理，不能直接取消",
                409,
            )
            require(reason, "请填写取消原因")
            status = "cancelled"
            db().execute(
                "UPDATE users SET cancellations=cancellations+1 WHERE id=?", (uid,)
            )
        elif action == "appeal":
            require(
                status in ("accepted", "ready", "confirming"),
                "该状态不能发起交接申诉；已结单请使用举报与申诉入口",
                409,
            )
            require(reason, "请填写申诉原因")
            status = "disputed"
        else:
            raise BusinessError("未知操作")
        db().execute(
            "UPDATE reservations SET status=?,reason=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (status, reason, rid),
        )
        log(action, "reservation", rid, reason)
        notify(
            r["buyer_id"] if uid == r["owner_id"] else r["owner_id"],
            f'《{r["title"]}》预约状态已更新，请查看我的预约',
        )
        return jsonify(status=status)

    @app.post("/api/reservations/<int:rid>/resolve")
    @auth(True)
    def resolve_reservation(rid):
        r = reservation_record(rid)
        require(r["status"] == "disputed", "仅待处理预约可裁定", 409)
        d = data()
        outcome = d.get("outcome")
        require(outcome in ("completed", "cancelled", "no_show"), "请选择处理结果")
        reason = field(d, "reason", "处理理由", 500)
        if outcome == "completed":
            complete(r)
        if outcome == "no_show":
            target = d.get("responsible_id")
            require(target in (r["owner_id"], r["buyer_id"]), "请选择责任方")
            db().execute(
                "UPDATE users SET credit=MAX(0,credit-?) WHERE id=?",
                (settings()["no_show_penalty"], target),
            )
        db().execute(
            "UPDATE reservations SET status=?,reason=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (outcome, reason, rid),
        )
        log("resolve", "reservation", rid, outcome + ": " + reason)
        for uid in (r["owner_id"], r["buyer_id"]):
            notify(uid, f"预约#{rid}申诉已处理：" + reason)
        return jsonify(ok=True)

    @app.post("/api/reservations/<int:rid>/rating")
    @auth()
    def rating(rid):
        r = reservation_record(rid)
        require(g.user["id"] in (r["owner_id"], r["buyer_id"]), "无权评价", 403)
        require(r["status"] == "completed", "完成交接后才可评价", 409)
        d = data()
        target = r["buyer_id"] if g.user["id"] == r["owner_id"] else r["owner_id"]
        db().execute(
            "INSERT INTO ratings(reservation_id,author_id,target_id,punctuality,accuracy,communication,tags,comment) VALUES(?,?,?,?,?,?,?,?)",
            (
                rid,
                g.user["id"],
                target,
                *[
                    integer(d.get(k), 1, 5, "评分")
                    for k in ("punctuality", "accuracy", "communication")
                ],
                redact(field(d, "tags", "标签", 100, True)),
                redact(field(d, "comment", "评价", 500, True)),
            ),
        )
        log("rate", "reservation", rid)
        return jsonify(ok=True), 201

    @app.get("/api/ratings")
    @auth()
    def my_ratings():
        return jsonify(
            rows(
                "SELECT * FROM ratings WHERE (author_id=? OR target_id=?) AND deleted=0 ORDER BY id DESC",
                (g.user["id"], g.user["id"]),
            )
        )

    @app.delete("/api/ratings/<int:rid>")
    @auth()
    def delete_rating(rid):
        r = row("SELECT * FROM ratings WHERE id=?", (rid,))
        require(r, "评价不存在", 404)
        require(
            r["author_id"] == g.user["id"] or g.user["role"] == "admin",
            "仅作者或管理员可删除评价",
            403,
        )
        db().execute("UPDATE ratings SET deleted=1 WHERE id=?", (rid,))
        log("delete_rating", "rating", rid)
        return jsonify(ok=True)

    @app.post("/api/reports")
    @auth()
    def report():
        d = data()
        bid = integer(d.get("book_id"), 1, 2147483647, "教材编号")
        book_record(bid)
        reason = field(d, "reason", "举报或申诉内容", 1000)
        require(
            not row(
                "SELECT id FROM reports WHERE author_id=? AND book_id=? AND status='pending'",
                (g.user["id"], bid),
            ),
            "此教材已有待处理举报",
            409,
        )
        rid = (
            db()
            .execute(
                "INSERT INTO reports(author_id,book_id,reason) VALUES(?,?,?)",
                (g.user["id"], bid, reason),
            )
            .lastrowid
        )
        log("report", "report", rid)
        return jsonify(id=rid), 201

    @app.get("/api/reports")
    @auth()
    def reports():
        return jsonify(
            rows(
                "SELECT r.*,b.title,b.owner_id,ap.original_id FROM reports r JOIN books b ON b.id=r.book_id LEFT JOIN report_appeals ap ON ap.appeal_id=r.id"
                + (
                    ""
                    if g.user["role"] == "admin"
                    else " WHERE r.author_id=? OR b.owner_id=?"
                )
                + " ORDER BY r.id DESC",
                () if g.user["role"] == "admin" else (g.user["id"], g.user["id"]),
            )
        )

    @app.post("/api/reports/<int:rid>/appeal")
    @auth()
    def appeal_report(rid):
        r = row("SELECT * FROM reports WHERE id=?", (rid,))
        require(r, "举报不存在", 404)
        b = book_record(r["book_id"])
        require(g.user["id"] == b["owner_id"], "仅被处罚的发布者可申请撤销处罚", 403)
        require(
            r["status"] == "upheld"
            and not row(
                "SELECT appeal_id FROM report_appeals WHERE original_id=? OR appeal_id=?",
                (rid, rid),
            ),
            "该举报不能重复申诉",
            409,
        )
        reason = field(data(), "reason", "申诉理由与补充证据", 1000)
        aid = (
            db()
            .execute(
                "INSERT INTO reports(author_id,book_id,reason) VALUES(?,?,?)",
                (g.user["id"], r["book_id"], f"申请撤销举报#{rid}处罚：" + reason),
            )
            .lastrowid
        )
        db().execute("INSERT INTO report_appeals VALUES(?,?)", (aid, rid))
        log("appeal_report", "report", aid)
        return jsonify(id=aid), 201

    @app.delete("/api/reports/<int:rid>")
    @auth()
    def retract_report(rid):
        r = row("SELECT * FROM reports WHERE id=?", (rid,))
        require(r, "举报不存在", 404)
        require(r["author_id"] == g.user["id"], "只能撤回自己的举报", 403)
        require(r["status"] == "pending", "已处理举报不能撤回", 409)
        db().execute("UPDATE reports SET status='withdrawn' WHERE id=?", (rid,))
        log("retract", "report", rid)
        return jsonify(ok=True)

    @app.post("/api/reports/<int:rid>/resolve")
    @auth(True)
    def resolve_report(rid):
        r = row("SELECT * FROM reports WHERE id=?", (rid,))
        require(r, "举报不存在", 404)
        require(r["status"] == "pending", "已处理，不能重复扣分", 409)
        d = data()
        require(type(d.get("upheld")) is bool, "请选择判定结果")
        reason = field(d, "reason", "处理理由", 1000)
        b = book_record(r["book_id"])
        appeal = row("SELECT * FROM report_appeals WHERE appeal_id=?", (rid,))
        if appeal:
            if d["upheld"]:
                penalty = row(
                    "SELECT * FROM report_penalties WHERE report_id=?",
                    (appeal["original_id"],),
                )
                require(
                    penalty and not penalty["reversed"],
                    "原处罚已撤销或无可恢复扣分",
                    409,
                )
                db().execute(
                    "UPDATE users SET credit=MIN(200,credit+?) WHERE id=?",
                    (penalty["amount"], b["owner_id"]),
                )
                db().execute(
                    "UPDATE report_penalties SET reversed=1 WHERE report_id=?",
                    (appeal["original_id"],),
                )
                db().execute(
                    "UPDATE reports SET status='overturned' WHERE id=?",
                    (appeal["original_id"],),
                )
            db().execute(
                "UPDATE reports SET status=?,resolution=? WHERE id=?",
                ("upheld" if d["upheld"] else "dismissed", reason, rid),
            )
            log("appeal_resolve", "report", rid, reason)
            notify(b["owner_id"], "处罚复核已完成：" + reason)
            return jsonify(ok=True)
        if d["upheld"]:
            actual = min(b["credit"], settings()["report_penalty"])
            db().execute(
                "INSERT INTO report_penalties(report_id,amount) VALUES(?,?)",
                (rid, actual),
            )
            db().execute(
                "UPDATE users SET credit=MAX(0,credit-?) WHERE id=?",
                (settings()["report_penalty"], b["owner_id"]),
            )
            if d.get("takedown") and b["status"] != "completed":
                db().execute(
                    "UPDATE books SET status='withdrawn' WHERE id=?", (b["id"],)
                )
                for rsv in rows(
                    "SELECT id FROM reservations WHERE book_id=? AND status IN ('pending','accepted','ready','confirming','disputed')",
                    (b["id"],),
                ):
                    db().execute(
                        "UPDATE reservations SET status='cancelled',reason='举报成立，管理员下架教材',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (rsv["id"],),
                    )
                    log("moderation_cancel", "reservation", rsv["id"])
        db().execute(
            "UPDATE reports SET status=?,resolution=? WHERE id=?",
            ("upheld" if d["upheld"] else "dismissed", reason, rid),
        )
        log("resolve", "report", rid, reason)
        for uid in {r["author_id"], b["owner_id"]}:
            notify(uid, f"举报#{rid}处理结果：" + reason)
        return jsonify(ok=True)

    @app.get("/api/notifications")
    @auth()
    def notifications():
        return jsonify(
            rows(
                "SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 100",
                (g.user["id"],),
            )
        )

    @app.post("/api/notifications/read")
    @auth()
    def read_notifications():
        db().execute("UPDATE notifications SET seen=1 WHERE user_id=?", (g.user["id"],))
        return jsonify(ok=True)

    def save_course_data(d):
        code = field(d, "code", "课程代码", 30).upper()
        require(
            re.fullmatch(r"[A-Z0-9_-]+", code), "课程代码只允许字母、数字、横线或下划线"
        )
        db().execute(
            "INSERT INTO courses VALUES(?,?,?,?) ON CONFLICT(code) DO UPDATE SET name=excluded.name,college=excluded.college,textbook=excluded.textbook",
            (
                code,
                field(d, "name", "课程名", 100),
                field(d, "college", "学院", 50),
                field(d, "textbook", "常用教材", 200, True),
            ),
        )
        log("course_save", "course", code)

    @app.post("/api/admin/courses")
    @auth(True)
    def save_course():
        save_course_data(data())
        return jsonify(ok=True)

    @app.post("/api/admin/courses/import")
    @auth(True)
    def import_courses():
        content = field(data(), "csv", "CSV内容", 100000).lstrip("\ufeff")
        reader = csv.DictReader(io.StringIO(content))
        require(
            reader.fieldnames
            and {"code", "name", "college"}.issubset(reader.fieldnames),
            "CSV表头须包含 code,name,college,textbook",
        )
        count = 0
        for course in reader:
            save_course_data(course)
            count += 1
        require(count > 0, "CSV没有有效数据")
        return jsonify(count=count)

    @app.route("/api/admin/settings", methods=["GET", "PUT"])
    @auth(True)
    def configure():
        if request.method == "PUT":
            d = data()
            for key in DEFAULTS:
                if key in d:
                    value = integer(
                        d[key],
                        1 if key == "confirm_hours" else 0,
                        720 if key == "confirm_hours" else 200,
                        key,
                    )
                    db().execute(
                        "UPDATE settings SET value=? WHERE key=?", (value, key)
                    )
            log("settings", "system", 0)
        return jsonify(settings())

    def stats():
        clauses = []
        args = []
        if request.args.get("college"):
            clauses.append("c.college=?")
            args.append(request.args["college"])
        for key, op in [("start", ">="), ("end", "<=")]:
            if request.args.get(key):
                try:
                    datetime.strptime(request.args[key], "%Y-%m-%d")
                except ValueError:
                    raise BusinessError("日期格式应为YYYY-MM-DD")
                clauses.append("date(b.created_at)" + op + "?")
                args.append(request.args[key])
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        selected = rows(
            "SELECT b.id,b.status,b.course_code,c.name FROM books b JOIN courses c ON c.code=b.course_code"
            + where,
            args,
        )
        ids = {b["id"] for b in selected}
        reviewed = sum(
            b["status"] in ("approved", "completed", "rejected") for b in selected
        )
        passed = sum(b["status"] in ("approved", "completed") for b in selected)
        rs = [r for r in rows("SELECT * FROM reports") if r["book_id"] in ids]
        counts = {}
        for b in selected:
            key = (b["course_code"], b["name"])
            counts[key] = counts.get(key, 0) + 1
        return {
            "published": len(selected),
            "pending": sum(b["status"] == "pending" for b in selected),
            "completed": sum(b["status"] == "completed" for b in selected),
            "approval_rate": round(passed / reviewed * 100, 1) if reviewed else 0,
            "reports": len(rs),
            "handled_reports": sum(r["status"] in ("upheld", "dismissed") for r in rs),
            "hot_courses": [
                {"code": k[0], "name": k[1], "count": v}
                for k, v in sorted(counts.items(), key=lambda x: x[1], reverse=True)[:8]
            ],
        }

    @app.get("/api/admin/stats")
    @auth(True)
    def admin_stats():
        return jsonify(stats())

    @app.get("/api/admin/export")
    @auth(True)
    def export():
        s = stats()
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["指标", "数值"])
        for k, v in s.items():
            if k != "hot_courses":
                writer.writerow([k, v])
        writer.writerow(["课程代码", "课程名称", "发布数"])
        for c in s["hot_courses"]:
            writer.writerow(
                [
                    (
                        "'" + str(c[k])
                        if str(c[k]).startswith(("=", "+", "-", "@"))
                        else c[k]
                    )
                    for k in ("code", "name", "count")
                ]
            )
        return Response(
            "\ufeff" + buffer.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=campus-report.csv"},
        )

    @app.get("/api/admin/logs")
    @auth(True)
    def logs():
        return jsonify(
            rows(
                "SELECT l.*,u.nickname FROM logs l LEFT JOIN users u ON u.id=l.actor_id ORDER BY l.id DESC LIMIT 500"
            )
        )

    with app.app_context():
        db().execute("PRAGMA journal_mode=WAL")
        db().executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
        for k, v in DEFAULTS.items():
            db().execute("INSERT OR IGNORE INTO settings VALUES(?,?)", (k, v))
        if app.config["DEMO"] and not row("SELECT id FROM users LIMIT 1"):
            from seed import seed_demo

            seed_demo(db(), Path(app.config["UPLOAD_FOLDER"]))
    app.process_timeouts = expire
    app.database = db
    return app


if __name__ == "__main__":
    from waitress import serve

    serve(
        create_app(),
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        threads=16,
    )
