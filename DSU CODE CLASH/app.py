"""
Smart Waste Management — Three-Mode Dashboard Backend
Modes: User | Worker | Manager
"""
import os
import sys
import math
import time
import uuid
import json
import base64
import socket
import sqlite3
import threading
import argparse
from datetime import datetime, date
from flask import Flask, request, jsonify, send_file

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE    = os.path.dirname(os.path.abspath(__file__))
DB      = os.path.join(BASE, "twin.db")
UPLOADS = os.path.join(BASE, "uploads")
DEPOT   = (12.9352, 77.5350)
HOURS   = list(range(5, 23))
LOCK    = threading.Lock()

os.makedirs(UPLOADS, exist_ok=True)

app = Flask(__name__)

# ── SmartWaste AI Chatbot Blueprint ─────────────────────────────────────────
from chatbot_backend import chatbot_bp
app.register_blueprint(chatbot_bp)

# ── In-memory truck state ────────────────────────────────────────────────────
T = {
    "lat": None, "lon": None, "accuracy": None, "speed_kmph": 0.0,
    "heading": None, "altitude": None, "last_gps_ts": None, "device_ts": None,
    "gps_sharing": False, "running": False, "window": None,
    "stops": [], "target": 0, "visited": [], "notified": [], "skipped": [],
    "trail": []
}

# ── In-memory worker GPS state ───────────────────────────────────────────────
W_GPS = {}   # {worker_id: {lat, lon, ts, trail: [[lat,lon], ...]}}


# ── Database ─────────────────────────────────────────────────────────────────
def db():
    con = sqlite3.connect(DB, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def _add_col(cursor, table, col, coltype):
    """Add column if it doesn't already exist (silently skips if it does)."""
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
    except sqlite3.OperationalError:
        pass


def init_db():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS residents(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, lat REAL, lon REAL,
            slots TEXT, radius INTEGER DEFAULT 300
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS notifications(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resident_id INTEGER, ts TEXT, msg TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS users(
            id TEXT PRIMARY KEY,
            name TEXT, lat REAL, lon REAL,
            preferred_time TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS workers(
            id TEXT PRIMARY KEY,
            name TEXT, vehicle TEXT, assigned_area TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS assignments(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_id TEXT, area_name TEXT,
            driver_name TEXT, vehicle TEXT,
            scheduled_time TEXT, polygon TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        _add_col(c, "assignments", "polygon", "TEXT")

        c.execute("""CREATE TABLE IF NOT EXISTS blackspot_reports(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT, lat REAL, lon REAL,
            description TEXT, image_path TEXT,
            waste_class TEXT DEFAULT 'Unclassified',
            wet_pct REAL DEFAULT 0, dry_pct REAL DEFAULT 0,
            assigned_worker_id TEXT, dispatch_time TEXT, urgency TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS cleaned_reports(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_id TEXT, blackspot_id INTEGER,
            image_path TEXT, notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS complaints(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT, lat REAL, lon REAL,
            message TEXT,
            verified_status TEXT DEFAULT 'Pending',
            verification_note TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS worker_coverage(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_id TEXT, lat REAL, lon REAL,
            ts TEXT, coverage_date TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS time_preferences(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT, area_name TEXT,
            preferred_time TEXT, lat REAL, lon REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        _add_col(c, "time_preferences", "lat",  "REAL")
        _add_col(c, "time_preferences", "lon",  "REAL")


# ── Helpers ───────────────────────────────────────────────────────────────────
def hav(a, b, c, d):
    """Haversine distance in metres between (a,b) and (c,d)."""
    p = math.pi / 180
    x = (math.sin((c - a) * p / 2) ** 2
         + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2)
    return 12742000 * math.asin(math.sqrt(x))


def pip(lat, lon, polygon):
    """Ray-casting point-in-polygon. polygon = [[lat,lon], ...]"""
    n = len(polygon)
    inside = False
    x, y = lon, lat
    p1x, p1y = polygon[0][1], polygon[0][0]
    for i in range(n + 1):
        p2x, p2y = polygon[i % n][1], polygon[i % n][0]
        if min(p1y, p2y) < y <= max(p1y, p2y):
            if x <= max(p1x, p2x):
                xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x if p1y != p2y else p1x
                if p1x == p2x or x <= xinters:
                    inside = not inside
        p1x, p1y = p2x, p2y
    return inside


def residents():
    with db() as c:
        out = []
        for r in c.execute("SELECT * FROM residents"):
            d = dict(r)
            d["slots"] = [int(s) for s in (d["slots"] or "").split(",") if s]
            out.append(d)
        return out


def save_image(data_url, prefix="img"):
    try:
        header, encoded = data_url.split(",", 1)
        ext = "png" if "png" in header else "jpg"
        fn = f"{prefix}_{uuid.uuid4().hex[:10]}.{ext}"
        with open(os.path.join(UPLOADS, fn), "wb") as f:
            f.write(base64.b64decode(encoded))
        return fn
    except Exception:
        return None


def classify_waste(image_path):
    """Placeholder classifier — replace with your model."""
    import random
    random.seed(hash(image_path or "") % 9973)
    wet  = random.randint(15, 85)
    dry  = 100 - wet
    label = "Mostly Wet" if wet > 60 else ("Mostly Dry" if dry > 60 else "Mixed Waste")
    return label, wet, dry


def today_str():
    return date.today().isoformat()


def best_time_from_list(times):
    """Majority-vote in 30-min buckets. Returns (bucket_label, count)."""
    buckets = {}
    for t in times:
        if not t:
            continue
        try:
            h, m = map(int, t.split(":"))
            label = f"{h:02d}:{'30' if m >= 30 else '00'}"
            buckets[label] = buckets.get(label, 0) + 1
        except Exception:
            continue
    if not buckets:
        return None, 0
    best = max(buckets, key=lambda k: (buckets[k], -int(k.split(":")[0])))
    return best, buckets[best]


def verify_complaint(comp):
    comp_date = (comp["created_at"] or "")[:10]
    with db() as c:
        trail = c.execute(
            "SELECT lat, lon FROM worker_coverage WHERE coverage_date=?", (comp_date,)
        ).fetchall()
    for pt in trail:
        if hav(comp["lat"], comp["lon"], pt["lat"], pt["lon"]) <= 200:
            return "Truck Visited", "GPS trail shows a truck passed within 200 m. User may have missed it."
    return "Truck Did Not Visit", "No GPS trail found within 200 m. Follow up with the driver."


def compute_gps_status():
    if not T["gps_sharing"]:
        return "GPS DISCONNECTED"
    if T["last_gps_ts"] is None:
        return "WAITING FOR GPS"
    elapsed = time.time() - T["last_gps_ts"]
    if elapsed <= 12.0:
        return "LIVE GPS"
    elif elapsed <= 30.0:
        return "LOCATION STALE"
    return "GPS DISCONNECTED"


def notify_nearby():
    if T["lat"] is None or T["lon"] is None:
        return
    for s in T["stops"]:
        if s["id"] in T["notified"] or s["id"] in T["visited"]:
            continue
        d = hav(T["lat"], T["lon"], s["lat"], s["lon"])
        if d <= s["radius"]:
            spd = max(T["speed_kmph"], 15.0)
            eta = max(1, round(d / (spd / 3.6) / 60))
            msg = f"Garbage truck arriving in ~{eta} min ({int(d)} m away)"
            with db() as c:
                c.execute("INSERT INTO notifications(resident_id,ts,msg) VALUES(?,?,?)",
                          (s["id"], datetime.now().strftime("%H:%M:%S"), msg))
            T["notified"].append(s["id"])


def schedule_helper(length):
    rs = residents()
    n  = len(rs)
    per_hour = {h: sum(h in r["slots"] for r in rs) for h in HOURS}
    wins = []
    for s in HOURS:
        hrs = range(s, s + length)
        if max(hrs) > HOURS[-1]:
            continue
        cov = sum(any(h in r["slots"] for h in hrs) for r in rs)
        wins.append(dict(start=s, end=s + length, covered=cov,
                         percent=round(100 * cov / n) if n else 0))
    wins.sort(key=lambda w: (-w["covered"], w["start"]))
    return dict(total=n, per_hour=per_hour, best=wins[:3])


def build_route(start, length):
    hrs  = range(start, start + length)
    cov  = [r for r in residents() if any(h in r["slots"] for h in hrs)]
    skip = [r["id"] for r in residents() if r not in cov]
    route, cur = [], DEPOT
    while cov:
        nxt = min(cov, key=lambda r: hav(cur[0], cur[1], r["lat"], r["lon"]))
        route.append(nxt)
        cov.remove(nxt)
        cur = (nxt["lat"], nxt["lon"])
    return route, skip


# ════════════════════════════════════════════════════════════════════════════════
#  FLASK ROUTES
# ════════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return send_file(os.path.join(BASE, "templates", "index.html"))

@app.route("/user")
def user_page():
    return send_file(os.path.join(BASE, "templates", "user.html"))

@app.route("/worker")
def worker_page():
    return send_file(os.path.join(BASE, "templates", "worker.html"))

@app.route("/driver")
def driver_page():
    return send_file(os.path.join(BASE, "templates", "worker.html"))

@app.route("/manager")
def manager_page():
    return send_file(os.path.join(BASE, "templates", "manager.html"))

@app.route("/uploads/<filename>")
def serve_upload(filename):
    return send_file(os.path.join(UPLOADS, filename))


# ────────────────────────── User APIs ────────────────────────────────────────

@app.route("/api/user/register", methods=["POST"])
def user_register():
    d    = request.get_json(silent=True) or {}
    uid  = d.get("id") or str(uuid.uuid4())
    name = str(d.get("name", "")).strip()[:80]
    ptime= str(d.get("preferred_time", "07:00"))[:8]
    try:
        lat = float(d["lat"]); lon = float(d["lon"])
    except (KeyError, ValueError, TypeError):
        return jsonify(ok=False, error="lat and lon required"), 400

    with db() as c:
        if c.execute("SELECT id FROM users WHERE id=?", (uid,)).fetchone():
            c.execute("UPDATE users SET name=?,lat=?,lon=?,preferred_time=? WHERE id=?",
                      (name, lat, lon, ptime, uid))
        else:
            c.execute("INSERT INTO users(id,name,lat,lon,preferred_time) VALUES(?,?,?,?,?)",
                      (uid, name, lat, lon, ptime))
        # Keep residents table in sync
        slot_h = max(5, min(22, int(ptime.split(":")[0])))
        slots  = f"{slot_h},{min(slot_h+1,22)}"
        if not c.execute("SELECT id FROM residents WHERE name=?", (name,)).fetchone():
            c.execute("INSERT INTO residents(name,lat,lon,slots,radius) VALUES(?,?,?,?,?)",
                      (name, lat, lon, slots, 300))
        # Record time preference with location for map-based analysis
        c.execute("INSERT INTO time_preferences(user_id,area_name,preferred_time,lat,lon) VALUES(?,?,?,?,?)",
                  (uid, "default", ptime, lat, lon))
    return jsonify(ok=True, id=uid), 200


@app.route("/api/user/<uid>")
def user_get(uid):
    with db() as c:
        u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        return jsonify(ok=False, error="Not found"), 404
    return jsonify(dict(u))


@app.route("/api/user/<uid>/time", methods=["PUT"])
def user_update_time(uid):
    d     = request.get_json(silent=True) or {}
    ptime = str(d.get("preferred_time", "07:00"))[:8]
    with db() as c:
        u = c.execute("SELECT lat,lon FROM users WHERE id=?", (uid,)).fetchone()
        c.execute("UPDATE users SET preferred_time=? WHERE id=?", (ptime, uid))
        lat = u["lat"] if u else None
        lon = u["lon"] if u else None
        c.execute("INSERT INTO time_preferences(user_id,area_name,preferred_time,lat,lon) VALUES(?,?,?,?,?)",
                  (uid, "default", ptime, lat, lon))
    return jsonify(ok=True)


@app.route("/api/user/complaint", methods=["POST"])
def user_complaint():
    d   = request.get_json(silent=True) or {}
    uid = str(d.get("user_id", ""))
    msg = str(d.get("message", "Truck did not come today"))[:500]
    try:
        lat = float(d["lat"]); lon = float(d["lon"])
    except (KeyError, ValueError, TypeError):
        lat, lon = 0.0, 0.0
    with db() as c:
        c.execute("INSERT INTO complaints(user_id,lat,lon,message) VALUES(?,?,?,?)",
                  (uid, lat, lon, msg))
    return jsonify(ok=True), 201


@app.route("/api/user/<uid>/complaints")
def user_complaints(uid):
    with db() as c:
        rows = c.execute(
            "SELECT * FROM complaints WHERE user_id=? ORDER BY id DESC LIMIT 30", (uid,)
        ).fetchall()
    result = []
    for r in rows:
        comp = dict(r)
        if comp["verified_status"] == "Pending":
            status, note = verify_complaint(comp)
            comp["verified_status"] = status
            comp["verification_note"] = note
        result.append(comp)
    return jsonify(result)


@app.route("/api/user/blackspot", methods=["POST"])
def user_blackspot():
    d    = request.get_json(silent=True) or {}
    uid  = str(d.get("user_id", ""))
    desc = str(d.get("description", "Blackspot report"))[:500]
    try:
        lat = float(d["lat"]); lon = float(d["lon"])
    except (KeyError, ValueError, TypeError):
        lat, lon = 0.0, 0.0

    image_path = None
    if d.get("image"):
        image_path = save_image(d["image"], prefix="blackspot")

    label, wet, dry = classify_waste(image_path)

    with db() as c:
        c.execute("""INSERT INTO blackspot_reports
                     (user_id,lat,lon,description,image_path,waste_class,wet_pct,dry_pct)
                     VALUES(?,?,?,?,?,?,?,?)""",
                  (uid, lat, lon, desc, image_path, label, wet, dry))
    return jsonify(ok=True, waste_class=label, wet_pct=wet, dry_pct=dry), 201


@app.route("/api/user/<uid>/notifications")
def user_notifications(uid):
    with db() as c:
        u   = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not u:
            return jsonify([])
        res = c.execute("SELECT id FROM residents WHERE name=?", (u["name"],)).fetchone()
        if not res:
            return jsonify([])
        ns  = c.execute("SELECT * FROM notifications WHERE resident_id=? ORDER BY id DESC LIMIT 20",
                        (res["id"],)).fetchall()
    return jsonify([dict(n) for n in ns])


@app.route("/api/user/<uid>/area")
def user_area(uid):
    """Which area & worker covers this user's location."""
    with db() as c:
        u = c.execute("SELECT lat,lon FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        return jsonify(area=None, worker=None)
    with db() as c:
        asgns = c.execute(
            "SELECT a.*, w.name as worker_name, w.vehicle FROM assignments a "
            "LEFT JOIN workers w ON a.worker_id=w.id ORDER BY a.id DESC"
        ).fetchall()
    for a in asgns:
        a = dict(a)
        if a.get("polygon"):
            try:
                poly = json.loads(a["polygon"])
                if pip(u["lat"], u["lon"], poly):
                    return jsonify(area=a["area_name"], worker=a["worker_name"],
                                   vehicle=a["vehicle"], scheduled_time=a["scheduled_time"])
            except Exception:
                pass
    return jsonify(area=None, worker=None)


# ────────────────────────── Worker APIs ──────────────────────────────────────

@app.route("/api/worker/register", methods=["POST"])
def worker_register():
    d       = request.get_json(silent=True) or {}
    wid     = d.get("id") or str(uuid.uuid4())
    name    = str(d.get("name", "")).strip()[:80]
    vehicle = str(d.get("vehicle", "")).strip()[:30]
    with db() as c:
        if c.execute("SELECT id FROM workers WHERE id=?", (wid,)).fetchone():
            c.execute("UPDATE workers SET name=?,vehicle=? WHERE id=?", (name, vehicle, wid))
        else:
            c.execute("INSERT INTO workers(id,name,vehicle) VALUES(?,?,?)", (wid, name, vehicle))
    return jsonify(ok=True, id=wid), 200


@app.route("/api/worker/<wid>/assignment")
def worker_assignment(wid):
    with db() as c:
        a = c.execute(
            "SELECT * FROM assignments WHERE worker_id=? ORDER BY id DESC LIMIT 1", (wid,)
        ).fetchone()
    if not a:
        return jsonify(assigned=False)
    a = dict(a)

    # Best time from location-aware preferences
    with db() as c:
        tp_rows = c.execute("SELECT preferred_time,lat,lon FROM time_preferences").fetchall()
    times = [r["preferred_time"] for r in tp_rows]
    best_time, pref_count = best_time_from_list(times)
    a["best_time"] = best_time
    a["preference_count"] = pref_count

    # Residents in polygon
    all_res = residents()
    poly = None
    if a.get("polygon"):
        try:
            poly = json.loads(a["polygon"])
        except Exception:
            pass
    res_in_area = [r for r in all_res if pip(r["lat"], r["lon"], poly)] if poly else all_res

    # Visited today (worker GPS within 50m of resident)
    tod = today_str()
    with db() as c:
        trail = c.execute(
            "SELECT lat,lon FROM worker_coverage WHERE worker_id=? AND coverage_date=?", (wid, tod)
        ).fetchall()

    visited_ids = []
    for r in res_in_area:
        for pt in trail:
            if hav(r["lat"], r["lon"], pt["lat"], pt["lon"]) <= 50:
                visited_ids.append(r["id"])
                break

    a["residents_count"] = len(res_in_area)
    a["visited_count"]   = len(visited_ids)
    a["visited_ids"]     = visited_ids
    return jsonify(assigned=True, assignment=a, residents=res_in_area, visited_ids=visited_ids)


@app.route("/api/worker/coverage", methods=["POST"])
def worker_coverage():
    d   = request.get_json(silent=True) or {}
    wid = str(d.get("worker_id", ""))
    try:
        lat = float(d["lat"]); lon = float(d["lon"])
    except (KeyError, ValueError, TypeError):
        return jsonify(ok=False, error="lat/lon required"), 400

    now_str = datetime.now().strftime("%H:%M:%S")
    tod     = today_str()

    with LOCK:
        if wid not in W_GPS:
            W_GPS[wid] = {"lat": None, "lon": None, "ts": None, "trail": []}
        W_GPS[wid].update({"lat": lat, "lon": lon, "ts": time.time()})
        trail = W_GPS[wid]["trail"]
        if not trail or hav(trail[-1][0], trail[-1][1], lat, lon) >= 5.0:
            trail.append([lat, lon])
            W_GPS[wid]["trail"] = trail[-2000:]

    with db() as c:
        c.execute(
            "INSERT INTO worker_coverage(worker_id,lat,lon,ts,coverage_date) VALUES(?,?,?,?,?)",
            (wid, lat, lon, now_str, tod)
        )
    # Proximity notifications
    with db() as c:
        res_rows = c.execute("SELECT * FROM residents").fetchall()
    for r in res_rows:
        if hav(lat, lon, r["lat"], r["lon"]) <= r["radius"]:
            with db() as c:
                c.execute("INSERT INTO notifications(resident_id,ts,msg) VALUES(?,?,?)",
                          (r["id"], now_str, f"Waste truck is {int(hav(lat,lon,r['lat'],r['lon']))}m away!"))
    return jsonify(ok=True)


@app.route("/api/worker/coverage_trail/<wid>")
def worker_coverage_trail(wid):
    tod = today_str()
    with db() as c:
        rows = c.execute(
            "SELECT lat,lon FROM worker_coverage WHERE worker_id=? AND coverage_date=? ORDER BY id",
            (wid, tod)
        ).fetchall()
    return jsonify([[r["lat"], r["lon"]] for r in rows])


@app.route("/api/worker/cleaned", methods=["POST"])
def worker_cleaned():
    d      = request.get_json(silent=True) or {}
    wid    = str(d.get("worker_id", ""))
    bsid   = d.get("blackspot_id")
    notes  = str(d.get("notes", ""))[:500]
    imgpth = save_image(d["image"], prefix="cleaned") if d.get("image") else None
    with db() as c:
        c.execute("INSERT INTO cleaned_reports(worker_id,blackspot_id,image_path,notes) VALUES(?,?,?,?)",
                  (wid, bsid, imgpth, notes))
        if bsid:
            c.execute("UPDATE blackspot_reports SET assigned_worker_id=? WHERE id=?", (wid, bsid))
    return jsonify(ok=True), 201


@app.route("/api/worker/<wid>/blackspots")
def worker_blackspots(wid):
    with db() as c:
        rows = c.execute(
            "SELECT * FROM blackspot_reports WHERE assigned_worker_id=? ORDER BY id DESC", (wid,)
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/worker/gps_all")
def worker_gps_all():
    with LOCK:
        result = {}
        for wid, state in W_GPS.items():
            if state["ts"] and time.time() - state["ts"] < 60:
                result[wid] = {"lat": state["lat"], "lon": state["lon"],
                               "trail": state["trail"][-200:]}
    return jsonify(result)


# ────────────────────────── Manager APIs ─────────────────────────────────────

@app.route("/api/manager/assign", methods=["POST"])
def manager_assign():
    d           = request.get_json(silent=True) or {}
    wid         = str(d.get("worker_id", ""))
    area        = str(d.get("area_name",  "Ward 1"))[:100]
    driver_name = str(d.get("driver_name", ""))[:80]
    vehicle     = str(d.get("vehicle", ""))[:30]
    sched       = str(d.get("scheduled_time", ""))[:10]
    polygon_data = d.get("polygon")
    polygon_json = json.dumps(polygon_data) if polygon_data else None

    res_count = 0
    if polygon_data:
        for r in residents():
            if pip(r["lat"], r["lon"], polygon_data):
                res_count += 1

    with db() as c:
        c.execute(
            "INSERT INTO assignments(worker_id,area_name,driver_name,vehicle,scheduled_time,polygon) "
            "VALUES(?,?,?,?,?,?)",
            (wid, area, driver_name, vehicle, sched, polygon_json)
        )
        c.execute("UPDATE workers SET assigned_area=? WHERE id=?", (area, wid))
    return jsonify(ok=True, resident_count=res_count), 201


@app.route("/api/manager/workers")
def manager_workers():
    with db() as c:
        rows = c.execute("SELECT * FROM workers").fetchall()
    result = []
    for r in rows:
        w = dict(r)
        with LOCK:
            gps = W_GPS.get(w["id"])
            if gps and gps["ts"] and time.time() - gps["ts"] < 60:
                w["live_lat"] = gps["lat"]; w["live_lon"] = gps["lon"]
                w["online"]   = True;       w["trail"]    = gps["trail"][-100:]
            else:
                w["live_lat"] = None; w["live_lon"] = None
                w["online"]   = False; w["trail"]   = []
        result.append(w)
    return jsonify(result)


@app.route("/api/manager/worker/<wid>", methods=["DELETE"])
def delete_worker(wid):
    with db() as c:
        c.execute("DELETE FROM workers        WHERE id=?",        (wid,))
        c.execute("DELETE FROM assignments    WHERE worker_id=?", (wid,))
        c.execute("DELETE FROM worker_coverage WHERE worker_id=?", (wid,))
    with LOCK:
        W_GPS.pop(wid, None)
    return jsonify(ok=True)


@app.route("/api/manager/worker/<wid>/assignment")
def manager_worker_assignment(wid):
    with db() as c:
        a = c.execute(
            "SELECT * FROM assignments WHERE worker_id=? ORDER BY id DESC LIMIT 1", (wid,)
        ).fetchone()
    if not a:
        return jsonify(assigned=False)
    return jsonify(assigned=True, assignment=dict(a))


@app.route("/api/manager/coverage")
def manager_coverage():
    tod = today_str()
    with db() as c:
        rows = c.execute(
            "SELECT worker_id,lat,lon FROM worker_coverage WHERE coverage_date=?", (tod,)
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/manager/coverage/reset", methods=["POST"])
def reset_coverage():
    with db() as c:
        c.execute("DELETE FROM worker_coverage WHERE coverage_date=?", (today_str(),))
    with LOCK:
        for wid in W_GPS:
            W_GPS[wid]["trail"] = []
    return jsonify(ok=True)


@app.route("/api/manager/time_analysis")
def manager_time_analysis():
    area       = request.args.get("area", "")
    center_lat = request.args.get("lat",    type=float)
    center_lon = request.args.get("lon",    type=float)
    radius_m   = request.args.get("radius", 2000, type=float)

    with db() as c:
        rows = c.execute("SELECT preferred_time,lat,lon FROM time_preferences").fetchall()

    if center_lat is not None and center_lon is not None:
        # Location-based: filter by proximity
        times = [r["preferred_time"] for r in rows
                 if r["lat"] and r["lon"]
                 and hav(center_lat, center_lon, r["lat"], r["lon"]) <= radius_m]
    else:
        # Fallback: all times
        times = [r["preferred_time"] for r in rows if r["preferred_time"]]

    total = len(times)
    if total == 0:
        return jsonify(total=0, best_time=None, best_count=0, distribution={})

    buckets: dict = {}
    for t in times:
        try:
            h, m = map(int, t.split(":"))
            label = f"{h:02d}:{'30' if m >= 30 else '00'}"
            buckets[label] = buckets.get(label, 0) + 1
        except Exception:
            continue

    best_time, best_count = best_time_from_list(times)
    return jsonify(total=total, best_time=best_time, best_count=best_count, distribution=buckets)


@app.route("/api/manager/blackspots")
def manager_blackspots():
    with db() as c:
        rows = c.execute(
            "SELECT b.*, w.name as worker_name FROM blackspot_reports b "
            "LEFT JOIN workers w ON b.assigned_worker_id=w.id ORDER BY b.id DESC"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/manager/blackspot/<int:bid>")
def blackspot_detail(bid):
    with db() as c:
        b = c.execute("SELECT * FROM blackspot_reports WHERE id=?", (bid,)).fetchone()
        if not b:
            return jsonify(ok=False), 404
        b = dict(b)
        if b.get("assigned_worker_id"):
            w = c.execute("SELECT name,vehicle FROM workers WHERE id=?",
                          (b["assigned_worker_id"],)).fetchone()
            if w:
                b["worker_name"]    = w["name"]
                b["worker_vehicle"] = w["vehicle"]
        cl = c.execute(
            "SELECT cr.*, w.name as cleaner_name FROM cleaned_reports cr "
            "LEFT JOIN workers w ON cr.worker_id=w.id "
            "WHERE cr.blackspot_id=? ORDER BY cr.id DESC LIMIT 1", (bid,)
        ).fetchone()
        if cl:
            cl = dict(cl)
            b["cleaned"]       = True
            b["cleaned_image"] = cl.get("image_path")
            b["cleaned_at"]    = cl.get("created_at")
            b["cleaner_name"]  = cl.get("cleaner_name")
            b["cleaned_notes"] = cl.get("notes")
        else:
            b["cleaned"] = False
    return jsonify(b)


@app.route("/api/manager/blackspot/<int:bid>/dispatch", methods=["POST"])
def dispatch_blackspot(bid):
    d    = request.get_json(silent=True) or {}
    dt   = str(d.get("dispatch_time", ""))[:10]
    urg  = str(d.get("urgency", "Normal"))[:20]
    wid  = str(d.get("worker_id", "")) or None
    with db() as c:
        c.execute(
            "UPDATE blackspot_reports SET dispatch_time=?,urgency=?,assigned_worker_id=? WHERE id=?",
            (dt, urg, wid, bid)
        )
    return jsonify(ok=True)


@app.route("/api/manager/blackspot/<int:bid>", methods=["DELETE"])
def delete_blackspot(bid):
    with db() as c:
        row = c.execute("SELECT image_path FROM blackspot_reports WHERE id=?", (bid,)).fetchone()
        if row and row["image_path"]:
            try:
                os.remove(os.path.join(UPLOADS, row["image_path"]))
            except Exception:
                pass
        c.execute("DELETE FROM blackspot_reports WHERE id=?", (bid,))
    return jsonify(ok=True)


@app.route("/api/manager/cleaned")
def manager_cleaned():
    with db() as c:
        rows = c.execute(
            "SELECT c.*, w.name as worker_name FROM cleaned_reports c "
            "LEFT JOIN workers w ON c.worker_id=w.id ORDER BY c.id DESC"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/manager/cleaned/<int:cid>", methods=["DELETE"])
def delete_cleaned(cid):
    with db() as c:
        row = c.execute("SELECT image_path FROM cleaned_reports WHERE id=?", (cid,)).fetchone()
        if row and row["image_path"]:
            try:
                os.remove(os.path.join(UPLOADS, row["image_path"]))
            except Exception:
                pass
        c.execute("DELETE FROM cleaned_reports WHERE id=?", (cid,))
    return jsonify(ok=True)


@app.route("/api/manager/complaints")
def manager_complaints():
    with db() as c:
        rows = c.execute(
            "SELECT comp.*, u.name as user_name FROM complaints comp "
            "LEFT JOIN users u ON comp.user_id=u.id ORDER BY comp.id DESC"
        ).fetchall()
    result = []
    for r in rows:
        comp = dict(r)
        if comp["verified_status"] == "Pending":
            status, note = verify_complaint(comp)
            comp["verified_status"]   = status
            comp["verification_note"] = note
        result.append(comp)
    return jsonify(result)


@app.route("/api/manager/assignments")
def manager_assignments():
    with db() as c:
        rows = c.execute(
            "SELECT a.*, w.name as worker_name FROM assignments a "
            "LEFT JOIN workers w ON a.worker_id=w.id ORDER BY a.id DESC"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


# ────────────────────────── Chatbot (replaced by Blueprint) ─────────────────
# The /api/chatbot route is now handled by chatbot_backend.py Blueprint.
# Blueprint registered at app init provides: /api/chatbot, /api/chatbot/quickdata, /api/chatbot/suggest

def chatbot_legacy_placeholder():
    d        = request.get_json(silent=True) or {}
    question = str(d.get("question", "")).strip()[:1000]
    mode     = str(d.get("mode", "user"))
    if not question:
        return jsonify(ok=False, error="Question required"), 400

    KEY = os.environ.get("GEMINI_API_KEY", "")

    if KEY:
        try:
            import google.generativeai as genai
            genai.configure(api_key=KEY)
            model = genai.GenerativeModel("gemini-1.5-flash")
            if mode == "worker":
                sys_prompt = (
                    "You are a safety and operations assistant for waste collection workers in Bangalore, India. "
                    "Answer questions about PPE, safe waste handling, hazardous materials, health precautions, "
                    "heat safety, animal hazards, route planning, and operational procedures. "
                    "Be concise (3-5 sentences), direct and practical. "
                    "Always tailor your answer specifically to the question asked."
                )
            else:
                sys_prompt = (
                    "You are a knowledgeable waste management assistant for SmartWaste, a smart garbage "
                    "collection platform in Bangalore, India. Answer questions about waste segregation, "
                    "recycling, composting, wet/dry waste, BBMP rules, environmental best practices, "
                    "e-waste, hazardous waste, and SmartWaste platform features. "
                    "Be concise (3-5 sentences), friendly and practical. "
                    "Give specific, actionable answers tailored to the exact question. Never be generic."
                )
            full_prompt = f"{sys_prompt}\n\nUser question: {question}"
            response = model.generate_content(full_prompt)
            return jsonify(ok=True, answer=response.text.strip())
        except Exception as e:
            print(f"[Gemini error] {e}")
            pass  # Fall through to keyword fallback

    # ── Extended local keyword fallback ───────────────────────────────────────
    q = question.lower()
    ans = None

    if mode == "worker":
        if any(w in q for w in ["ppe","glove","protect","suit","gear","equipment"]):
            ans = ("Mandatory PPE for every shift: puncture-resistant rubber gloves, N95 respirator mask, "
                   "steel-toe safety boots, high-visibility vest, and safety goggles. Check your PPE before "
                   "starting — worn or torn equipment must be replaced immediately. No shortcuts on PPE.")
        elif any(w in q for w in ["needle","syringe","sharp","blade","broken glass"]):
            ans = ("Never touch sharps with bare hands. Use long tongs and thick gloves. "
                   "Place needles in a rigid sealed container — not the regular bin. "
                   "If you get a needle-stick injury, clean with running water for 5 min and report to supervisor immediately for medical attention.")
        elif any(w in q for w in ["chemical","acid","toxic","unknown liquid","fume","smell strong","hazardous liquid"]):
            ans = ("Treat unknown liquids or strong chemical smells as hazardous. "
                   "Don't pick them up — seal the area, wear your respirator, and call your supervisor. "
                   "Never mix unidentified substances. Log the incident and let the hazmat team handle it.")
        elif any(w in q for w in ["heat","sun","dehydrat","dizzy","hot","summer","sweating heavily"]):
            ans = ("Heat safety: drink 250ml of water every 20 minutes even without thirst. "
                   "Take 10-min shade breaks every hour in peak summer. Warning signs: dizziness, nausea, "
                   "or stopping sweating — these mean heat exhaustion. Stop work, move to shade, drink water, and call for help.")
        elif any(w in q for w in ["cut","wound","bleed","scratch","injury"]):
            ans = ("Clean any cut or wound immediately — run clean water over it for 5 minutes, "
                   "apply antiseptic, cover with a sterile bandage. Report all injuries to your supervisor. "
                   "Deep wounds, bites, or injuries from sharp waste require immediate medical attention for tetanus/infection risk.")
        elif any(w in q for w in ["dog","animal","bite","rat","snake","pest"]):
            ans = ("Animal bites are medical emergencies. Immediately wash the bite with soap and water for 15 minutes. "
                   "Seek medical attention for rabies vaccination — especially for dog, cat, or monkey bites. "
                   "Report all animal encounters on duty to your supervisor.")
        elif any(w in q for w in ["route","area","house","which area","where to go","coverage"]):
            ans = ("Check your assigned area in the Area tab on your dashboard. "
                   "Red pins are houses not yet visited. Start with the nearest unvisited house to be efficient. "
                   "Your GPS trail shows in green on the map as you move. Aim to cover all red pins before end of shift.")
        elif any(w in q for w in ["schedule","time","when","shift","pickup time"]):
            ans = ("Your optimal pickup time is shown in the Schedule tab — it's calculated from resident preferences in your area. "
                   "Aim to reach each house within that time window for maximum pickup success. "
                   "Houses turn green once your GPS passes within 50m of them.")
        else:
            ans = (f"For your question about '{question}': Always prioritize safety on shift — "
                   "wear your PPE, stay hydrated, and don't handle unknown materials alone. "
                   "Check your Area tab for today's coverage status, and use the Proof tab to upload cleaned area photos. "
                   "What specific safety or operations question can I help with?")
    else:
        # User mode fallback
        if any(w in q for w in ["wet waste","organic","kitchen","food scrap","vegetable peel","fruit","leftover","rice","cooked"]):
            ans = ("Wet waste = any organic/biodegradable item: vegetable peels, fruit scraps, leftover food, "
                   "tea leaves, coffee grounds, garden clippings, and eggshells. Always use a GREEN bin. "
                   "Wet waste is best composted — it becomes rich fertilizer in 30-45 days and reduces waste by up to 50%.")
        elif any(w in q for w in ["dry waste","paper","cardboard","plastic bottle","glass bottle","metal can","recyclable"]):
            ans = ("Dry waste = clean recyclables: paper, cardboard, plastic bottles (types 1/2/5), "
                   "glass bottles/jars, and metal tins/cans. Use the BLUE bin. "
                   "Rinse containers before putting them in — food contamination ruins an entire batch of recyclables.")
        elif any(w in q for w in ["segregat","separate","sort","which bin","colour","green bin","blue bin","red bin"]):
            ans = ("Waste segregation in Bangalore: 🟢 GREEN bin = wet/organic waste (food, peels, garden). "
                   "🔵 BLUE bin = dry recyclables (paper, plastic, glass, metal). "
                   "🔴 RED bin = hazardous/domestic waste (batteries, medicines, diapers, chemicals). "
                   "Proper segregation makes recycling 10x more effective — it's mandatory under BBMP rules.")
        elif any(w in q for w in ["compost","composting","vermicompost","fertilizer from waste"]):
            ans = ("Composting at home is easy and reduces waste dramatically. "
                   "Compost: vegetable peels, fruit scraps, tea/coffee grounds, eggshells, dry leaves, cardboard. "
                   "Don't compost: meat, dairy, oily food, diseased plants. A small balcony compost bin works for a family. "
                   "Ready in 30-60 days, produces rich garden fertilizer.")
        elif any(w in q for w in ["plastic","single use","polythene","straw","bag","sachet","wrap"]):
            ans = ("Single-use plastics (bags, straws, sachets) are banned in Bangalore — avoid them. "
                   "Rigid plastics marked 1, 2, or 5 are recyclable (go in blue bin after cleaning). "
                   "Thin films, multi-layer pouches, and styrofoam cannot be recycled — they become landfill. "
                   "Switch to cloth bags, steel bottles, and glass containers wherever possible.")
        elif any(w in q for w in ["e-waste","electronic","phone","laptop","computer","tv","charger","cable","battery"]):
            ans = ("E-waste contains toxic metals (lead, mercury, cadmium) — never put in regular bins. "
                   "Drop off electronics at authorised e-waste centres: most malls and BBMP e-waste camps. "
                   "Many brands (Dell, Apple, Samsung) have free take-back programs for old devices. "
                   "Burning e-waste releases highly toxic fumes — always dispose responsibly.")
        elif any(w in q for w in ["recycle","recycling"]):
            ans = ("Recyclable: clean glass, metal cans, rigid plastics (1/2/5), paper, cardboard. "
                   "Not recyclable: food-soiled packaging, tissue/paper towels, styrofoam, multilayer pouches, broken glass (handle carefully). "
                   "Always clean before recycling — a pizza box with grease cannot be recycled, but a clean cardboard box can.")
        elif any(w in q for w in ["bbmp","municipal","corporation","helpline","report","collect","pickup","truck missed","not come"]):
            ans = ("BBMP Solid Waste Management helpline: 1533. For missed pickup, use the Inform tab in SmartWaste "
                   "to file a complaint — it auto-records your GPS location. "
                   "You can also check the live truck location on the Map tab to see if the truck is in your area. "
                   "BBMP also accepts complaints at bbmpsms.com and the Sahaaya app.")
        elif any(w in q for w in ["hazardous","medical","medicine","pills","syringe","sanitary","chemical waste","paint","motor oil"]):
            ans = ("Hazardous household waste goes in the RED bin: expired medicines, thermometers, pesticides, "
                   "paint, motor oil, sanitary products, and medical sharps. Seal all hazardous items before disposal. "
                   "Never pour medicines down the drain — they contaminate groundwater. "
                   "Many pharmacies accept expired medicines for proper disposal.")
        elif any(w in q for w in ["reduce","reuse","zero waste","eco","sustainable","green","minimiz","less waste"]):
            ans = ("Top tips to reduce waste: 1) Always carry reusable bags and water bottle. "
                   "2) Buy in bulk to reduce packaging. 3) Compost your kitchen scraps. "
                   "4) Repair before replacing — most electronics and clothes can be fixed. "
                   "5) Shop second-hand. These habits can cut your household waste by 60% within a month.")
        elif any(w in q for w in ["fine","penalty","law","illegal dump","rule","violat"]):
            ans = ("Illegal waste dumping in Bangalore: up to ₹500 fine for individuals, ₹5,000 for businesses. "
                   "Burning waste in the open is a criminal offence under Air Prevention Act. "
                   "Littering in public places: ₹100–500 fine. Report violations to BBMP at 1533 or via the BBMP app.")
        elif any(w in q for w in ["smell","odour","stink","bad smell","bin smell"]):
            ans = ("To control bin odour: separate wet waste and dispose of it daily (never let it sit for 2+ days). "
                   "Sprinkle a small amount of lime powder or dry soil in the green bin to absorb smell. "
                   "Clean bins weekly with diluted vinegar or baking soda solution. "
                   "Keep bin lids closed — this also prevents flies and pests.")
        elif any(w in q for w in ["notification","alert","notify","ping","truck near"]):
            ans = ("SmartWaste sends a notification when the garbage truck is within 400m of your home. "
                   "Enable notifications in the Settings tab. Make sure your browser allows notifications from this site. "
                   "You'll see a toast alert with approximate distance and ETA — keep your waste ready by the door!")
        elif any(w in q for w in ["blackspot","dump","illegal pile","complaint","garbage heap"]):
            ans = ("Spotted an illegal garbage dump or blackspot? Use the Upload tab to photograph and report it. "
                   "Your geotagged photo goes directly to the manager who can dispatch a worker to clean it. "
                   "The system automatically classifies wet vs dry waste in the image. "
                   "You can track if it's been cleaned in the Spots section.")
        elif any(w in q for w in ["map","location","where","track","live"]):
            ans = ("The Map tab shows your garbage truck's live location in real-time (updates every 5 seconds). "
                   "A cyan route line shows the truck's path towards your home. "
                   "Your home is shown as a green pin. The truck turns amber and pulses when GPS is active. "
                   "If the truck icon is grey, GPS hasn't been updated in the last 30 seconds.")
        else:
            ans = (f"Thanks for your question about '{question}'! "
                   "Key reminders: use GREEN bin for wet waste, BLUE bin for recyclables, RED bin for hazardous items. "
                   "Track your truck live on the Map tab, report issues via Inform tab, and upload blackspot photos in the Upload tab. "
                   "Ask me anything specific about recycling, composting, waste rules, or SmartWaste features!")

    return jsonify(ok=True, answer=ans)


# ────────────────────────── Legacy / Original APIs ───────────────────────────

@app.route("/api/residents", methods=["GET", "POST"])
def api_res():
    if request.method == "POST":
        d = request.get_json(silent=True)
        if not d:
            return jsonify(ok=False, error="Invalid JSON"), 400
        name = str(d.get("name", "")).strip()[:60]
        if not name:
            return jsonify(ok=False, error="Name is required"), 400
        try:
            lat = float(d["lat"]); lon = float(d["lon"])
        except (KeyError, ValueError, TypeError):
            return jsonify(ok=False, error="Valid lat and lon required"), 400
        slots  = ",".join(str(int(h)) for h in d.get("slots", []) if int(h) in HOURS)
        radius = int(d.get("radius", 300))
        with db() as c:
            cur = c.execute("INSERT INTO residents(name,lat,lon,slots,radius) VALUES(?,?,?,?,?)",
                            (name, lat, lon, slots, radius))
        return jsonify(ok=True, id=cur.lastrowid), 201
    return jsonify(residents())


@app.route("/api/residents/<int:rid>", methods=["DELETE"])
def del_res(rid):
    with db() as c:
        c.execute("DELETE FROM residents WHERE id=?", (rid,))
    return jsonify(ok=True)


@app.route("/api/schedule")
def api_sched():
    length = int(request.args.get("len", 2))
    return jsonify(schedule_helper(length))


@app.route("/api/truck/start", methods=["POST"])
def truck_start():
    d = request.get_json(silent=True) or {}
    try:
        start_hr = int(d.get("start", 7)); length_hr = int(d.get("len", 2))
    except (ValueError, TypeError):
        return jsonify(ok=False, error="Invalid start/len"), 400
    route, skip = build_route(start_hr, length_hr)
    with LOCK:
        T["stops"] = route; T["target"] = 0; T["visited"] = []
        T["notified"] = []; T["skipped"] = skip
        T["window"] = [start_hr, start_hr + length_hr]; T["running"] = bool(route)
        with db() as c:
            c.execute("DELETE FROM notifications")
    return jsonify(ok=True, stops=len(route), skipped=len(skip))


@app.route("/api/truck/stop", methods=["POST"])
def truck_stop():
    with LOCK:
        T["running"] = False
    return jsonify(ok=True)


@app.route("/api/truck/start_gps", methods=["POST"])
def start_gps():
    with LOCK:
        T["gps_sharing"] = True
    return jsonify(ok=True, status=compute_gps_status())


@app.route("/api/truck/stop_gps", methods=["POST"])
def stop_gps():
    with LOCK:
        T["gps_sharing"] = False
    return jsonify(ok=True, status="GPS DISCONNECTED")


@app.route("/api/truck/location", methods=["POST"])
def gps_location():
    data = request.get_json(silent=True)
    if not data or "lat" not in data or "lon" not in data:
        return jsonify(ok=False, error="Missing lat/lon"), 400
    try:
        lat = float(data["lat"]); lon = float(data["lon"])
    except (ValueError, TypeError):
        return jsonify(ok=False, error="lat/lon must be numeric"), 400
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return jsonify(ok=False, error="Coordinates out of range"), 400

    accuracy   = None
    speed_kmph = None
    heading    = None
    altitude   = None
    if data.get("accuracy") is not None:
        try:
            a = float(data["accuracy"])
            if a >= 0: accuracy = round(a, 1)
        except Exception: pass
    if data.get("speed") is not None:
        try:
            s = float(data["speed"])
            if s >= 0: speed_kmph = round(s * 3.6, 1)
        except Exception: pass
    if data.get("heading") is not None:
        try:
            h = float(data["heading"])
            if 0 <= h <= 360: heading = round(h, 1)
        except Exception: pass
    if data.get("altitude") is not None:
        try:
            altitude = round(float(data["altitude"]), 1)
        except Exception: pass

    with LOCK:
        now = time.time()
        prev_lat, prev_lon, prev_ts = T["lat"], T["lon"], T["last_gps_ts"]
        if speed_kmph is None:
            if prev_lat and prev_ts and (now - prev_ts) > 0.8:
                d_m = hav(prev_lat, prev_lon, lat, lon)
                speed_kmph = min(round((d_m / (now - prev_ts)) * 3.6, 1), 120.0)
            else:
                speed_kmph = T["speed_kmph"]
        T.update(dict(lat=lat, lon=lon, accuracy=accuracy, speed_kmph=speed_kmph,
                      heading=heading, altitude=altitude, device_ts=data.get("timestamp"),
                      last_gps_ts=now, gps_sharing=True))
        if not T["trail"] or hav(T["trail"][-1][0], T["trail"][-1][1], lat, lon) >= 1.5:
            T["trail"].append([lat, lon])
            if len(T["trail"]) > 1000: T["trail"] = T["trail"][-1000:]
        if T["stops"]:
            for s in T["stops"]:
                if s["id"] not in T["visited"] and hav(lat, lon, s["lat"], s["lon"]) <= 30.0:
                    T["visited"].append(s["id"])
            notify_nearby()
            if len(T["visited"]) >= len(T["stops"]): T["running"] = False

    return jsonify(ok=True, status=compute_gps_status(),
                   visited=len(T["visited"]), total_stops=len(T["stops"]))


@app.route("/api/truck")
def api_truck():
    with LOCK:
        gps_status = compute_gps_status()
        elapsed    = (time.time() - T["last_gps_ts"]) if T["last_gps_ts"] else None
        stops = []
        for s in T["stops"]:
            d_m = hav(T["lat"], T["lon"], s["lat"], s["lon"]) if T["lat"] else None
            eta = round(d_m / (max(T["speed_kmph"], 15.0) / 3.6) / 60, 1) if d_m else None
            stops.append(dict(id=s["id"], name=s["name"], lat=s["lat"], lon=s["lon"],
                              dist=int(d_m) if d_m else None, eta_min=eta,
                              state=("visited"  if s["id"] in T["visited"]
                                     else "notified" if s["id"] in T["notified"] else "pending")))
        out = dict(
            lat=T["lat"], lon=T["lon"], accuracy=T["accuracy"],
            speed_kmph=T["speed_kmph"], heading=T["heading"], altitude=T["altitude"],
            last_gps_ts=T["last_gps_ts"], last_gps_age=round(elapsed, 1) if elapsed else None,
            gps_status=gps_status, gps_sharing=T["gps_sharing"], running=T["running"],
            window=T["window"], stops=stops,
            visited_count=len(T["visited"]), total_stops=len(T["stops"]),
            skipped=T["skipped"], depot=list(DEPOT), trail=T["trail"][-500:]
        )
    with db() as c:
        out["notifications"] = [dict(r) for r in c.execute(
            "SELECT * FROM notifications ORDER BY id DESC LIMIT 50")]
    return jsonify(out)


@app.route("/api/seed", methods=["POST"])
def seed():
    import random; random.seed(7)
    with db() as c:
        c.execute("DELETE FROM residents")
        for i in range(25):
            peak  = random.choice([6, 7, 7, 8, 19, 20, 20, 21])
            slots = sorted({peak, peak + 1} | ({random.choice(HOURS)} if random.random() < 0.4 else set()))
            slots = [h for h in slots if h in HOURS]
            c.execute("INSERT INTO residents(name,lat,lon,slots,radius) VALUES(?,?,?,?,?)",
                      (f"House {i+1}",
                       DEPOT[0] + random.uniform(-0.006, 0.008),
                       DEPOT[1] + random.uniform(-0.006, 0.008),
                       ",".join(map(str, slots)), 300))
    return jsonify(ok=True)


# ════════════════════════════════════════════════════════════════════════════════
def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]; s.close(); return ip
    except Exception:
        return "127.0.0.1"


init_db()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SmartWaste Backend")
    parser.add_argument("--port",  type=int, default=5000)
    parser.add_argument("--host",  default="0.0.0.0")
    parser.add_argument("--https", action="store_true")
    args   = parser.parse_args()
    lan_ip = get_lan_ip()
    ssl_ctx = None
    proto   = "http"
    if args.https:
        cert, key = os.path.join(BASE, "cert.pem"), os.path.join(BASE, "key.pem")
        if os.path.exists(cert) and os.path.exists(key):
            ssl_ctx = (cert, key); proto = "https"
    print("\n" + "=" * 72)
    print("   SMARTWASTE — THREE-MODE DASHBOARD")
    print(f"   Landing  : {proto}://127.0.0.1:{args.port}/")
    print(f"   User     : {proto}://127.0.0.1:{args.port}/user")
    print(f"   Worker   : {proto}://{lan_ip}:{args.port}/worker   (use on phone)")
    print(f"   Manager  : {proto}://127.0.0.1:{args.port}/manager")
    print("   Set OPENAI_API_KEY env var to enable real ChatGPT responses.")
    print("=" * 72 + "\n")
    app.run(debug=False, host=args.host, port=args.port, ssl_context=ssl_ctx)
