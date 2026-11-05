"""Only explicit demo mode creates fictitious users and catalogue items."""

import json
from PIL import Image, ImageDraw, ImageFont
from werkzeug.security import generate_password_hash

COURSES = [
    ("SE301", "软件工程", "计算机学院", "软件工程导论（第6版）"),
    ("CS201", "数据结构", "计算机学院", "数据结构（C语言版）"),
    ("MA201", "高等数学", "理学院", "高等数学（第7版）"),
    ("CS305", "数据库系统", "计算机学院", "数据库系统概论（第5版）"),
    ("EN101", "大学英语", "外国语学院", "新视野大学英语（第3版）"),
    ("EC201", "微观经济学", "经济管理学院", "微观经济学（第9版）"),
]


def seed_demo(db, folder):
    for sid, name, role, contact in [
        ("admin", "学院管理员", "admin", "admin-demo"),
        ("20240001", "林同学", "student", "lin-demo"),
        ("20240002", "陈同学", "student", "chen-demo"),
    ]:
        db.execute(
            "INSERT INTO users(student_id,password,nickname,college,class_name,contact,role) VALUES(?,?,?,?,?,?,?)",
            (
                sid,
                generate_password_hash("Campus2026!"),
                name,
                "计算机学院",
                "软件工程2401",
                contact,
                role,
            ),
        )
    for c in COURSES:
        db.execute("INSERT INTO courses VALUES(?,?,?,?)", c)
    colors = ["#214c69", "#48675b", "#84634b", "#4f5e8b", "#99624f", "#665881"]
    labels = [
        "SOFTWARE\nENGINEERING",
        "DATA\nSTRUCTURES",
        "ADVANCED\nMATHEMATICS",
        "DATABASE\nSYSTEMS",
        "COLLEGE\nENGLISH",
        "MICRO\nECONOMICS",
    ]
    for i, c in enumerate(COURSES):
        picture = Image.new("RGB", (600, 760), colors[i])
        draw = ImageDraw.Draw(picture)
        try:
            font = ImageFont.truetype("arial.ttf", 48)
            small = ImageFont.truetype("arial.ttf", 24)
        except OSError:
            font = ImageFont.load_default(size=48)
            small = ImageFont.load_default(size=24)
        draw.rectangle((32, 0, 38, 760), fill="white")
        draw.text((75, 75), c[0], font=small, fill="white")
        draw.multiline_text((75, 210), labels[i], font=font, fill="white", spacing=14)
        draw.line((75, 430, 520, 430), fill="white", width=2)
        draw.text((75, 640), "CAMPUS / DEMO COVER", font=small, fill="white")
        name = f"demo-{i}.jpg"
        picture.save(folder / name)
        url = "/uploads/" + name
        db.execute("INSERT INTO uploads VALUES(?,2)", (url,))
        db.execute(
            "INSERT INTO books(owner_id,course_code,title,edition,condition,price,notes,images,status) VALUES(2,?,?,?,?,?,?,?, 'approved')",
            (
                c[0],
                c[1] + "教材",
                "课程演示版",
                5 if i % 2 == 0 else 4,
                [2200, 1800, 0, 2500, 1200, 1600][i],
                "演示教材：封面为项目自制示意图。书页完整，可在图书馆线下交接。",
                json.dumps([url]),
            ),
        )
        db.execute(
            "INSERT INTO logs(actor_id,action,entity,entity_id,detail) VALUES(1,'demo_seed','book',?,'虚构演示数据')",
            (str(i + 1),),
        )
