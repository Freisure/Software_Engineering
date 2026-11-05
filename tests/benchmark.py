"""Optional real HTTP load check: python tests/benchmark.py (isolated data)."""

import json
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from waitress import create_server


def main():
    parent = Path(__file__).resolve().parents[1] / "instance"
    parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="benchmark-", dir=parent) as folder:
        app = create_app(
            {
                "DATABASE": str(Path(folder) / "campus.db"),
                "UPLOAD_FOLDER": str(Path(folder) / "uploads"),
                "SECRET_KEY": "benchmark-only",
                "DEMO": True,
            }
        )
        with app.app_context():
            db = app.database()
            db.execute("BEGIN IMMEDIATE")
            for i in range(994):
                db.execute(
                    "INSERT INTO books(owner_id,course_code,title,edition,condition,price,notes,images,status) SELECT owner_id,course_code,title,edition,condition,price,notes,images,status FROM books WHERE id=?",
                    (i % 6 + 1,),
                )
            db.commit()
        server = create_server(app, host="127.0.0.1", port=0, threads=16)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        barrier = threading.Barrier(50)

        def browse(i):
            barrier.wait()
            start = time.perf_counter()
            with urlopen(
                f"http://127.0.0.1:{server.effective_port}/api/books?q=SE3", timeout=20
            ) as response:
                body = json.load(response)
                assert response.status == 200 and len(body) == 167
            return time.perf_counter() - start

        try:
            with ThreadPoolExecutor(max_workers=50) as pool:
                durations = sorted(pool.map(browse, range(50)))
            result = {
                "books": 1000,
                "concurrent_browsers": 50,
                "successful_requests": len(durations),
                "p50_seconds": round(durations[24], 4),
                "p95_seconds": round(durations[47], 4),
                "max_seconds": round(max(durations), 4),
                "under_2_seconds": max(durations) <= 2,
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
        finally:
            server.close()
            thread.join(timeout=5)


if __name__ == "__main__":
    main()
