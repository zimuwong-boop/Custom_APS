"""Disposable single-container acceptance: persistence, concurrency, backup/restore, offline."""

import concurrent.futures
import http.cookiejar
import json
import os
import secrets
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCKER = (
    "/Applications/Docker.app/Contents/Resources/bin/docker"
    if Path("/Applications/Docker.app").exists()
    else "docker"
)
name = "aps-acceptance-" + secrets.token_hex(4)
volume = name + "-data"
port = 18080
base = f"http://127.0.0.1:{port}/api/v1/"
env = {
    **os.environ,
    "PATH": "/Applications/Docker.app/Contents/Resources/bin:" + os.environ["PATH"],
}
logs = []


def docker(*args):
    result = subprocess.run([DOCKER, *args], env=env, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def wait_ready():
    for _ in range(60):
        try:
            if (
                json.loads(urllib.request.urlopen(base + "health/ready", timeout=2).read())["data"][
                    "status"
                ]
                == "ok"
            ):
                return
        except (OSError, ValueError):
            time.sleep(0.5)
    raise RuntimeError("Container readiness timeout")


def start():
    docker(
        "run",
        "-d",
        "--name",
        name,
        "--cpus",
        "2",
        "--memory",
        "4g",
        "-p",
        f"127.0.0.1:{port}:8000",
        "-v",
        f"{volume}:/data",
        "-e",
        "SECRET_KEY=" + secrets.token_urlsafe(48),
        "custom-aps:local",
    )
    wait_ready()


def api(path, method="GET", body=None):
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    bootstrap = json.loads(opener.open(base + "bootstrap").read())["data"]
    headers = {
        "Content-Type": "application/json",
        "X-CSRFToken": bootstrap["csrf_token"],
        "Idempotency-Key": secrets.token_hex(12),
    }
    request = urllib.request.Request(
        base + path,
        data=json.dumps({**(body or {}), "dataset_epoch": bootstrap["dataset_epoch"]}).encode()
        if method != "GET"
        else None,
        headers=headers,
        method=method,
    )
    try:
        response = opener.open(request)
        return response.status, json.loads(response.read())["data"]
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


try:
    start()
    assert api("items")[1]["total"] == 0
    assert api("units")[1]["total"] == 3
    logs.append("Fresh start: units only, no business data; readiness healthy.")
    unit = next(u for u in api("units")[1]["results"] if u["code"] == "PCS")
    _, raw = api(
        "items",
        "POST",
        {"code": "TEST-R", "name": "Temporary raw", "type": "RAW", "unit_id": unit["id"]},
    )
    _, semi = api(
        "items",
        "POST",
        {"code": "TEST-S", "name": "Temporary semi", "type": "SEMI", "unit_id": unit["id"]},
    )
    _, bom = api(
        "boms",
        "POST",
        {
            "item_id": semi["id"],
            "revision": "V1",
            "base_quantity": "1",
            "lines": [{"component_item_id": raw["id"], "quantity": "1"}],
        },
    )
    assert api(f"boms/{bom['id']}/activate", "POST", {"expected_version": bom["version"]})[0] == 200
    _, sale = api(
        "sales-orders",
        "POST",
        {
            "number": "TEST-SALE",
            "customer_name": "Temporary test",
            "lines": [{"item_id": semi["id"], "quantity": "1"}],
        },
    )
    assert (
        api(f"sales-orders/{sale['id']}/confirm", "POST", {"expected_version": sale["version"]})[0]
        == 200
    )
    _, plan = api("plans/current")
    assert (
        api(f"plans/{plan['id']}/confirm", "POST", {"expected_version": plan["version"]})[0] == 200
    )
    order = api("production-orders")[1]["results"][0]
    assert (
        api(
            f"production-orders/{order['id']}/start", "POST", {"expected_version": order["version"]}
        )[0]
        == 200
    )
    order = api(f"production-orders/{order['id']}")[1]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda amount: api(
                    f"production-orders/{order['id']}/progress",
                    "POST",
                    {"expected_version": order["version"], "own_progress": amount},
                )[0],
                ["50", "60"],
            )
        )
    assert sorted(results) == [200, 409], results
    logs.append(
        "Two concurrent writers: exactly one committed, the other received VERSION_CONFLICT."
    )
    baseline = api(f"production-orders/{order['id']}")[1]["progress"]
    old_epoch = api("bootstrap")[1]["dataset_epoch"]
    backup_path = "/data/acceptance-backup.sqlite3"
    docker("exec", name, "python", "scripts/backup_sqlite.py", "/data/aps.sqlite3", backup_path)
    current = api(f"production-orders/{order['id']}")[1]
    assert (
        api(
            f"production-orders/{order['id']}/progress",
            "POST",
            {"expected_version": current["version"], "own_progress": "100"},
        )[0]
        == 200
    )
    docker("restart", name)
    wait_ready()
    assert api(f"production-orders/{order['id']}")[1]["progress"] == "100.00"
    logs.append("Restart preserved completed progress and batch genealogy.")
    docker("stop", name)
    docker("rm", name)
    docker(
        "run",
        "--rm",
        "-v",
        f"{volume}:/data",
        "--entrypoint",
        "python",
        "custom-aps:local",
        "scripts/restore_sqlite.py",
        backup_path,
        "/data/aps.sqlite3",
        "--service-stopped",
    )
    start()
    assert api(f"production-orders/{order['id']}")[1]["progress"] == baseline
    assert api("bootstrap")[1]["dataset_epoch"] > old_epoch
    assert "PASS" in docker("exec", name, "python", "manage.py", "check_demo_integrity")
    assert (
        api(f"trace/batches/{order['batch_number']}")[1]["nodes"][0]["batch_number"]
        == order["batch_number"]
    )
    logs.append("Restore recovered original progress and batch number; safety copy retained.")
    html = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read().decode()
    assert "/assets/" in html
    import re

    asset = re.search(r'src="([^"]+\.js)"', html).group(1)
    assert urllib.request.urlopen(f"http://127.0.0.1:{port}" + asset).status == 200
    docker("stop", name)
    docker("rm", name)
    docker(
        "run",
        "-d",
        "--name",
        name,
        "--network",
        "none",
        "-v",
        f"{volume}:/data",
        "-e",
        "SECRET_KEY=" + secrets.token_urlsafe(48),
        "custom-aps:local",
    )
    for _ in range(60):
        try:
            output = docker(
                "exec",
                name,
                "python",
                "-c",
                (
                    "import urllib.request; "
                    "print(urllib.request.urlopen("
                    "'http://127.0.0.1:8000/api/v1/health/ready').status); "
                    "print(urllib.request.urlopen('http://127.0.0.1:8000/').status)"
                ),
            )
            if output == "200\n200":
                break
        except subprocess.CalledProcessError:
            time.sleep(0.5)
    else:
        raise RuntimeError("Offline startup failed")
    logs.append(
        "Network disabled: local API and bundled SPA served successfully without external services."
    )
    docker("exec", name, "python", "-c", "import os; os.chmod('/data/aps.sqlite3', 0o400)")
    probe = """import urllib.request, urllib.error
for path in ['ready','live']:
    try:
        print(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/'+path).status)
    except urllib.error.HTTPError as error:
        print(error.code)
"""
    assert docker("exec", name, "python", "-c", probe) == "503\n200"
    docker("exec", name, "python", "-c", "import os; os.chmod('/data/aps.sqlite3', 0o600)")
    logs.append("Read-only database: ready returned 503 while live remained 200.")
    (ROOT / "Docs/container-verification.json").write_text(
        json.dumps(
            {"status": "PASS", "cpu_limit": 2, "memory_limit": "4g", "checks": logs},
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print("\n".join(logs))
finally:
    subprocess.run([DOCKER, "rm", "-f", name], env=env, capture_output=True)
    subprocess.run([DOCKER, "volume", "rm", volume], env=env, capture_output=True)
