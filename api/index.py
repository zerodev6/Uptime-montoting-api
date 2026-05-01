"""
MvxyUptime API v2 — Advanced Serverless Uptime Monitor (No Notifications)
Built for Vercel + MongoDB Atlas
Author: @Venuboyy
"""

from http.server import BaseHTTPRequestHandler
import json, os, time, urllib.request, urllib.error
import hashlib, hmac
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, parse_qs
from pymongo import MongoClient, DESCENDING

# ════════════════════════════════════════════════════════════════════
#  ENVIRONMENT CONFIG
# ════════════════════════════════════════════════════════════════════

MONGO_URI      = os.environ.get("MONGO_URI", "")
API_SECRET     = os.environ.get("API_SECRET", "changeme")

VALID_INTERVALS = [10, 30, 60, 120, 300, 600, 1800, 3600]
_mongo_client = None

def get_db():
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = _mongo_client["uptime_db"]
    _ensure_indexes(db)
    return db

def _ensure_indexes(db):
    try:
        db.monitors.create_index("id", unique=True)
        db.checks.create_index([("monitor_id", 1), ("checked_at", -1)])
        db.incidents.create_index([("monitor_id", 1), ("opened_at", -1)])
    except Exception:
        pass

# ════════════════════════════════════════════════════════════════════
#  HELPERS
# ════════════════════════════════════════════════════════════════════

def now_utc():
    return datetime.now(timezone.utc)

def now_iso():
    return now_utc().isoformat()

def ok(data=None, status=200):
    body = {"ok": True}
    if data is not None:
        body["data"] = data
    return status, body

def err(msg, status=400):
    return status, {"ok": False, "error": msg}

def require_auth(headers):
    return hmac.compare_digest(headers.get("x-api-key", ""), API_SECRET)

def make_id(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()[:16]

def snap_interval(seconds: int) -> int:
    return min(VALID_INTERVALS, key=lambda x: abs(x - seconds))

def human_interval(s: int) -> str:
    if s < 60:   return f"{s}s"
    if s < 3600: return f"{s // 60}m"
    return f"{s // 3600}h"

# ════════════════════════════════════════════════════════════════════
#  HTTP CHECK ENGINE
# ════════════════════════════════════════════════════════════════════

def check_url(url: str, timeout: int = 10) -> dict:
    start = time.time()
    result = {
        "url": url,
        "checked_at": now_iso(),
        "status": "down",
        "status_code": None,
        "latency_ms": None,
        "error": None,
        "ssl_valid": url.startswith("https"),
        "redirect_url": None,
    }
    try:
        req = urllib.request.Request(
            url, method="GET",
            headers={"User-Agent": "MvxyUptime/2.0 (@Venuboyy)"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            latency = round((time.time() - start) * 1000, 2)
            result.update({
                "status_code": resp.status,
                "latency_ms": latency,
                "redirect_url": resp.url if resp.url != url else None,
                "status": "up" if 200 <= resp.status < 400 else "down",
            })
    except urllib.error.HTTPError as e:
        latency = round((time.time() - start) * 1000, 2)
        result.update({"latency_ms": latency, "status_code": e.code,
                        "error": f"HTTP {e.code}: {e.reason}"})
    except Exception as e:
        latency = round((time.time() - start) * 1000, 2)
        result.update({"latency_ms": latency, "error": str(e)[:200]})
    return result

def determine_state(result: dict, mon: dict) -> str:
    if result["status"] == "down":
        return "down"
    threshold = mon.get("degraded_threshold_ms")
    if threshold and (result.get("latency_ms") or 0) > threshold:
        return "degraded"
    return "up"

# ════════════════════════════════════════════════════════════════════
#  INCIDENT MANAGEMENT
# ════════════════════════════════════════════════════════════════════

def handle_incident(db, mon: dict, state: str, result: dict) -> str | None:
    mid = mon["id"]
    open_inc = db.incidents.find_one({"monitor_id": mid, "resolved": False},
                                      sort=[("opened_at", DESCENDING)])
    
    if state in ("down", "degraded"):
        if not open_inc:
            inc = {
                "id": make_id(f"{mid}{now_iso()}"),
                "monitor_id": mid,
                "monitor_name": mon.get("name", mon["url"]),
                "url": mon["url"],
                "state": state,
                "opened_at": now_iso(),
                "resolved": False,
                "resolved_at": None,
                "duration_seconds": None,
                "checks_during": 1,
                "cause": result.get("error") or f"HTTP {result.get('status_code', '?')}",
            }
            db.incidents.insert_one(inc)
            return inc["id"]
        else:
            db.incidents.update_one({"id": open_inc["id"]},
                {"$inc": {"checks_during": 1}, "$set": {"state": state}})
            return open_inc["id"]

    elif state == "up" and open_inc:
        opened = datetime.fromisoformat(open_inc["opened_at"].replace("Z", "+00:00"))
        duration = int((now_utc() - opened).total_seconds())
        db.incidents.update_one({"id": open_inc["id"]}, {"$set": {
            "resolved": True, "resolved_at": now_iso(), "duration_seconds": duration,
        }})

    return None

# ════════════════════════════════════════════════════════════════════
#  STATS HELPERS
# ════════════════════════════════════════════════════════════════════

def calc_uptime(db, monitor_id: str) -> dict:
    windows = {"1h": 1, "24h": 24, "7d": 168, "30d": 720}
    out = {}
    for label, hours in windows.items():
        since = (now_utc() - timedelta(hours=hours)).isoformat()
        total = db.checks.count_documents({"monitor_id": monitor_id, "checked_at": {"$gte": since}})
        if total == 0:
            out[label] = None
            continue
        up = db.checks.count_documents({"monitor_id": monitor_id,
                                         "checked_at": {"$gte": since}, "state": "up"})
        out[label] = round((up / total) * 100, 3)
    return out

def calc_latency(db, monitor_id: str, hours: int = 24):
    since = (now_utc() - timedelta(hours=hours)).isoformat()
    pipeline = [
        {"$match": {"monitor_id": monitor_id, "checked_at": {"$gte": since},
                    "latency_ms": {"$ne": None}}},
        {"$group": {"_id": None, "avg": {"$avg": "$latency_ms"},
                    "min": {"$min": "$latency_ms"}, "max": {"$max": "$latency_ms"}}},
    ]
    r = list(db.checks.aggregate(pipeline))
    return {"avg": round(r[0]["avg"], 2), "min": r[0]["min"], "max": r[0]["max"]} if r else None

def save_check(db, mon: dict, result: dict):
    mid   = mon["id"]
    state = determine_state(result, mon)
    db.checks.insert_one({
        "monitor_id": mid,
        "checked_at": result["checked_at"],
        "state": state,
        "status": result["status"],
        "status_code": result["status_code"],
        "latency_ms": result["latency_ms"],
        "ssl_valid": result.get("ssl_valid"),
        "error": result.get("error"),
    })
    handle_incident(db, mon, state, result)
    db.monitors.update_one({"id": mid}, {
        "$set": {
            "status": state,
            "last_checked": result["checked_at"],
            "last_status_code": result["status_code"],
            "last_latency_ms": result["latency_ms"],
            "uptime": calc_uptime(db, mid),
            "latency_stats_24h": calc_latency(db, mid),
        },
        "$inc": {"total_checks": 1},
    })
    # Cap history to 5000 checks
    old = list(db.checks.find({"monitor_id": mid}, {"_id": 1}).sort("checked_at", DESCENDING).skip(5000))
    if old:
        db.checks.delete_many({"_id": {"$in": [c["_id"] for c in old]}})

# ════════════════════════════════════════════════════════════════════
#  ROUTE HANDLERS
# ════════════════════════════════════════════════════════════════════

def route_health(method, params, body, headers):
    return ok({"service": "MvxyUptime API v2 (No Notifications)", "status": "operational"})

def route_monitors_list(method, params, body, headers):
    if not require_auth(headers): return err("Unauthorized", 401)
    tag = params.get("tag", [None])[0]
    q = {"tags": tag} if tag else {}
    mons = list(get_db().monitors.find(q, {"_id": 0}).sort("created_at", DESCENDING))
    return ok({"monitors": mons, "count": len(mons)})

def route_monitors_create(method, params, body, headers):
    if not require_auth(headers): return err("Unauthorized", 401)
    url = body.get("url", "").strip()
    if not url: return err("'url' is required")
    
    interval = snap_interval(int(body.get("interval_seconds", 60)))
    mid = make_id(url)
    db = get_db()
    doc = {
        "id": mid,
        "name": body.get("name", "").strip() or url,
        "url": url,
        "interval_seconds": interval,
        "interval_human": human_interval(interval),
        "timeout_seconds": int(body.get("timeout_seconds", 10)),
        "tags": body.get("tags", []),
        "degraded_threshold_ms": body.get("degraded_threshold_ms"),
        "status": "unknown",
        "last_checked": None,
        "uptime": {},
        "created_at": now_iso(),
        "paused": False,
        "total_checks": 0
    }
    db.monitors.update_one({"id": mid}, {"$setOnInsert": doc}, upsert=True)
    result = check_url(url, doc["timeout_seconds"])
    save_check(db, doc, result)
    return ok({"monitor": db.monitors.find_one({"id": mid}, {"_id": 0})}, 201)

def route_monitors_update(method, params, body, headers, monitor_id):
    if not require_auth(headers): return err("Unauthorized", 401)
    fields = ["name", "interval_seconds", "tags", "degraded_threshold_ms", "timeout_seconds"]
    update = {k: body[k] for k in fields if k in body}
    if "interval_seconds" in update:
        iv = snap_interval(int(update["interval_seconds"]))
        update["interval_seconds"], update["interval_human"] = iv, human_interval(iv)
    
    db = get_db()
    if db.monitors.update_one({"id": monitor_id}, {"$set": update}).matched_count == 0:
        return err("Monitor not found", 404)
    return ok({"monitor": db.monitors.find_one({"id": monitor_id}, {"_id": 0})})

def route_monitors_delete(method, params, body, headers, monitor_id):
    if not require_auth(headers): return err("Unauthorized", 401)
    db = get_db()
    if db.monitors.delete_one({"id": monitor_id}).deleted_count == 0:
        return err("Monitor not found", 404)
    db.checks.delete_many({"monitor_id": monitor_id})
    db.incidents.delete_many({"monitor_id": monitor_id})
    return ok({"deleted": monitor_id})

def route_ping_all(method, params, body, headers):
    if not require_auth(headers): return err("Unauthorized", 401)
    db = get_db()
    mons = list(db.monitors.find({"paused": False}))
    results = []
    for mon in mons:
        last_checked = mon.get("last_checked")
        if last_checked:
            elapsed = (now_utc() - datetime.fromisoformat(last_checked.replace("Z", "+00:00"))).total_seconds()
            if elapsed < mon.get("interval_seconds", 60): continue
            
        res = check_url(mon["url"], mon.get("timeout_seconds", 10))
        save_check(db, mon, res)
        results.append({"id": mon["id"], "state": determine_state(res, mon)})
    return ok({"pinged": len(results), "results": results})

def route_status_page(method, params, body, headers):
    db = get_db()
    mons = list(db.monitors.find({"paused": False}, {"_id": 0, "notifications": 0}))
    return ok({"monitors": mons, "generated_at": now_iso()})

# ════════════════════════════════════════════════════════════════════
#  ROUTER & VERCEL HANDLER
# ════════════════════════════════════════════════════════════════════

ROUTES = [
    ("GET",    "/api/health",          route_health,           None),
    ("GET",    "/api/monitors",        route_monitors_list,    None),
    ("POST",   "/api/monitors",        route_monitors_create,  None),
    ("PATCH",  "/api/monitors/{id}",   route_monitors_update,  "id"),
    ("DELETE", "/api/monitors/{id}",   route_monitors_delete,  "id"),
    ("POST",   "/api/ping-all",        route_ping_all,         None),
    ("GET",    "/api/status",          route_status_page,      None),
]

def match_route(method, path):
    path = path.split("?")[0].rstrip("/") or "/"
    for r_method, pattern, fn, id_key in ROUTES:
        if r_method != method: continue
        pp, rp = pattern.split("/"), path.split("/")
        if len(pp) != len(rp): continue
        captured, ok_match = None, True
        for a, b in zip(pp, rp):
            if a.startswith("{"): captured = b
            elif a != b: ok_match = False; break
        if ok_match: return fn, captured, id_key
    return None, None, None

class handler(BaseHTTPRequestHandler):
    def _handle(self):
        method, path = self.command, self.path
        cl = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(cl)) if cl else {}
        headers = {k.lower(): v for k, v in self.headers.items()}
        
        fn, captured, id_key = match_route(method, path)
        if not fn:
            status, resp = err("Route not found", 404)
        else:
            try:
                status, resp = fn(method, parse_qs(urlparse(path).query), body, headers, captured) if id_key else fn(method, parse_qs(urlparse(path).query), body, headers)
            except Exception as e:
                status, resp = err(f"Server Error: {e}", 500)

        rb = json.dumps(resp, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(rb)

    def do_GET(self): self._handle()
    def do_POST(self): self._handle()
    def do_PATCH(self): self._handle()
    def do_DELETE(self): self._handle()
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key")
        self.end_headers()
    def log_message(self, *args): pass
