"""End-to-end API test using Flask's test client (no socket needed)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from forge.samples import BY_ID

app.config["TESTING"] = True
client = app.test_client()


def check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print("[%s] %s%s" % (status, label, (" - " + detail) if detail else ""))
    return condition


ok = True

r = client.get("/api/health")
ok &= check("GET /api/health", r.status_code == 200 and r.get_json()["status"] == "ok")

r = client.get("/")
ok &= check("GET / renders", r.status_code == 200 and b"Utility Bill Forge" in r.data)
ok &= check("index has textarea", b'id="bill-text"' in r.data)
ok &= check("index has sample loader", b"toggle-samples" in r.data)

r = client.get("/static/style.css")
ok &= check("GET /static/style.css", r.status_code == 200 and len(r.data) > 2000)
r = client.get("/static/app.js")
ok &= check("GET /static/app.js", r.status_code == 200 and len(r.data) > 2000)

r = client.get("/api/samples")
samples = r.get_json()["samples"]
ok &= check("GET /api/samples", r.status_code == 200 and len(samples) >= 6, "%d samples" % len(samples))
r = client.get("/api/sample/tiered_residential")
ok &= check("GET /api/sample/<id>", r.status_code == 200 and "text" in r.get_json())

r = client.post("/api/analyze", json={"text": BY_ID["tiered_residential"]["text"]})
data = r.get_json()
ok &= check("POST /api/analyze", r.status_code == 200 and data["bill_count"] == 1)
ok &= check("analyze returns score", 0 <= data["primary"]["score"]["overall"] <= 100,
            str(data["primary"]["score"]["overall"]))
ok &= check("analyze returns findings", isinstance(data["primary"]["findings"], list))
ok &= check("analyze returns savings", isinstance(data["primary"]["savings"], list))
ok &= check("analyze returns session id", data.get("session_id") is not None)
sid = data["session_id"]

for s in samples:
    r = client.post("/api/analyze", json={"text": s["text"]})
    d = r.get_json()
    good = (r.status_code == 200 and d["bill_count"] >= 1
            and d["primary"]["score"]["overall"] >= 0
            and d["primary"]["metrics"]["total"] is not None)
    ok &= check("analyze sample " + s["id"], good,
                "score %s, total %s" % (d["primary"]["score"]["overall"], d["primary"]["metrics"]["total"]))

r = client.get("/api/sessions")
ok &= check("GET /api/sessions", r.status_code == 200 and len(r.get_json()["sessions"]) > 0)

r = client.patch("/api/sessions/%d" % sid, json={"rating": 5, "notes": "looks right"})
body = r.get_json()
ok &= check("PATCH session rating", r.status_code == 200 and body["rating"] == 5)
ok &= check("PATCH session notes", body["notes"] == "looks right")

r = client.get("/api/sessions/%d" % sid)
ok &= check("GET session", r.status_code == 200 and "result" in r.get_json())

r = client.patch("/api/sessions/999999", json={"rating": 3})
ok &= check("PATCH missing session -> 404", r.status_code == 404)

r = client.get("/api/export/%d?fmt=md" % sid)
ok &= check("export md", r.status_code == 200 and b"# Utility Bill Audit" in r.data)
ok &= check("export md disposition", "attachment" in (r.headers.get("Content-Disposition") or ""))
r = client.get("/api/export/%d?fmt=json" % sid)
ok &= check("export json", r.status_code == 200 and b'"primary"' in r.data)

r = client.post("/api/analyze", json={"text": ""})
ok &= check("empty text -> 400", r.status_code == 400 and "error" in r.get_json())

r = client.post("/api/analyze", json={"text": "hello world" + chr(10) + "not a bill"})
ok &= check("garbage still returns a result", r.status_code == 200)

r = client.get("/api/sample/does-not-exist")
ok &= check("missing sample -> 404", r.status_code == 404)

r = client.get("/api/export/999999?fmt=md")
ok &= check("missing export -> 404", r.status_code == 404)

r = client.post("/api/analyze", json={"text": BY_ID["two_bill_compare"]["text"]})
d = r.get_json()
ok &= check("multi-bill splits", d["bill_count"] == 2, "%d bills" % d["bill_count"])
ok &= check("multi-bill comparison present", d["comparison"] is not None)
ok &= check("multi-bill notes", len(d["comparison"]["notes"]) > 0)

for s in client.get("/api/sessions").get_json()["sessions"]:
    client.delete("/api/sessions/%d" % s["id"])
ok &= check("DELETE session", client.get("/api/sessions").get_json()["sessions"] == [])

print("")
print("ALL API CHECKS PASSED" if ok else "SOME API CHECKS FAILED")
sys.exit(0 if ok else 1)
