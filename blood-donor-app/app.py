# DONOR FINDER++  -  app.py
# Flask + SQLite. Replace your old app.py completely with this file.
import os, re, time, math, json, uuid, hashlib, secrets, sqlite3
from datetime import datetime, timedelta, date

import requests
from flask import (Flask, g, jsonify, request, session,
                   render_template, render_template_string)
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "donors.db")

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    MAX_CONTENT_LENGTH=1 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")),
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)

# ----------------------------------------------------------------- constants
STD_GROUPS = ["O+", "O-", "A+", "A-", "B+", "B-", "AB+", "AB-"]
RARE_GROUPS = ["Oh (Bombay)", "Rh-null (Golden)", "Kell- (K-)", "Duffy- (Fy a-b-)"]
ALL_GROUPS = STD_GROUPS + RARE_GROUPS

# recipient group -> donor groups that can give to them
COMPAT = {
    "O-": ["O-"],
    "O+": ["O+", "O-"],
    "A-": ["A-", "O-"],
    "A+": ["A+", "A-", "O+", "O-"],
    "B-": ["B-", "O-"],
    "B+": ["B+", "B-", "O+", "O-"],
    "AB-": ["AB-", "A-", "B-", "O-"],
    "AB+": list(STD_GROUPS),
}
for _r in RARE_GROUPS:           # rare phenotypes: same phenotype only
    COMPAT[_r] = [_r]

ORG_TYPES = ["College", "Hostel", "Department", "Corporate", "Community"]

RANKS = [(10, "Apex Lifeblood"), (5, "Arterial Paladin"),
         (2, "Crimson Vanguard"), (1, "Hemoglobin Herald"),
         (0, "Pulse Pledger")]
POINTS_PER_UNIT = 150
COOLDOWN_DAYS = 90
LIVES_PER_DONATION = 3

CITY_COORDS = {
    "chennai": (13.0827, 80.2707), "coimbatore": (11.0168, 76.9558),
    "madurai": (9.9252, 78.1198), "tiruchirappalli": (10.7905, 78.7047),
    "trichy": (10.7905, 78.7047), "salem": (11.6643, 78.1460),
    "tirunelveli": (8.7139, 77.7567), "erode": (11.3410, 77.7172),
    "vellore": (12.9165, 79.1325), "thanjavur": (10.7870, 79.1378),
    "bengaluru": (12.9716, 77.5946), "bangalore": (12.9716, 77.5946),
    "hyderabad": (17.3850, 78.4867), "kochi": (9.9312, 76.2673),
    "thiruvananthapuram": (8.5241, 76.9366), "mumbai": (19.0760, 72.8777),
    "pune": (18.5204, 73.8567), "delhi": (28.6139, 77.2090),
    "kolkata": (22.5726, 88.3639), "ahmedabad": (23.0225, 72.5714),
    "jaipur": (26.9124, 75.7873), "lucknow": (26.8467, 80.9462),
    "puducherry": (11.9416, 79.8083),
}

# ----------------------------------------------------------------- database
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=15)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_e):
    db = g.pop("db", None)
    if db is not None:
        db.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS donors_pp(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  uid TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  phone TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  blood_group TEXT NOT NULL,
  city TEXT NOT NULL,
  lat REAL, lon REAL,
  org_type TEXT DEFAULT 'Community',
  org_name TEXT DEFAULT '',
  available INTEGER DEFAULT 1,
  last_donation TEXT,
  donations INTEGER DEFAULT 0,
  points INTEGER DEFAULT 0,
  photo_data TEXT,
  photo_status TEXT DEFAULT 'none',
  is_demo INTEGER DEFAULT 0,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS camps_pp(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT, organizer TEXT, city TEXT, address TEXT,
  lat REAL, lon REAL, camp_date TEXT, camp_time TEXT, contact TEXT,
  is_sample INTEGER DEFAULT 0, created_by INTEGER, created_at TEXT
);
CREATE TABLE IF NOT EXISTS pledges_pp(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  camp_id INTEGER, donor_id INTEGER,
  UNIQUE(camp_id, donor_id)
);
CREATE TABLE IF NOT EXISTS sos_pp(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  donor_id INTEGER, patient TEXT, blood_group TEXT, hospital TEXT,
  city TEXT, contact TEXT, units INTEGER, note TEXT, radius INTEGER,
  hash TEXT, sms_sent INTEGER DEFAULT 0, sms_status TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS donations_pp(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  donor_id INTEGER, units INTEGER, donated_on TEXT, place TEXT, created_at TEXT
);
"""


def now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def init_db():
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    if os.environ.get("SEED_DEMO", "1") == "1":
        seed_demo(db)
    db.commit()
    db.close()


def seed_demo(db):
    if db.execute("SELECT 1 FROM donors_pp WHERE is_demo=1 LIMIT 1").fetchone():
        return
    demo = [
        ("Aarav K", "O+", "Chennai", "Hostel", "Block-A Hostel", 5),
        ("Meera S", "B+", "Chennai", "Department", "Computer Science Dept", 4),
        ("Rahul V", "A+", "Coimbatore", "Corporate", "Sample Tech Pvt Ltd", 3),
        ("Divya R", "O-", "Madurai", "Hostel", "Block-A Hostel", 6),
        ("Karthik M", "AB+", "Chennai", "Department", "Computer Science Dept", 2),
        ("Fathima N", "Oh (Bombay)", "Bengaluru", "College", "Sample Arts College", 1),
        ("Suresh P", "B-", "Salem", "Corporate", "Sample Tech Pvt Ltd", 2),
        ("Lakshmi T", "A-", "Trichy", "College", "Sample Arts College", 3),
    ]
    for i, (n, bg, city, ot, on, d) in enumerate(demo, 1):
        lat, lon = CITY_COORDS[city.lower()]
        db.execute(
            """INSERT INTO donors_pp(uid,name,phone,password_hash,blood_group,city,
               lat,lon,org_type,org_name,available,donations,points,is_demo,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,1,?,?,1,?)""",
            ("DF-DEMO%d" % i, n, "DEMO%06d" % i, "!", bg, city, lat, lon, ot, on,
             d, d * POINTS_PER_UNIT, now()))
    if not db.execute("SELECT 1 FROM camps_pp WHERE is_sample=1 LIMIT 1").fetchone():
        base = date.today()
        camps = [
            ("SAMPLE: Community Blood Drive", "Sample Rotary Club", "Chennai",
             "Sample Hall, T Nagar", 13.0418, 80.2341, 6),
            ("SAMPLE: Campus Donation Day", "Sample College NSS", "Coimbatore",
             "Sample Auditorium", 11.0168, 76.9558, 9),
            ("SAMPLE: Rare Group Donor Meet", "Sample Red Cross", "Bengaluru",
             "Sample Centre, MG Road", 12.9756, 77.6068, 12),
        ]
        for t, o, c, a, la, lo, off in camps:
            db.execute(
                """INSERT INTO camps_pp(title,organizer,city,address,lat,lon,camp_date,
                   camp_time,contact,is_sample,created_at) VALUES(?,?,?,?,?,?,?,?,?,1,?)""",
                (t, o, c, a, la, lo, (base + timedelta(days=off)).isoformat(),
                 "09:00 - 15:00", "", now()))


init_db()

# ----------------------------------------------------------------- helpers
def clean(s, n=120):
    s = "" if s is None else str(s)
    s = re.sub(r"[\x00-\x1f\x7f]", " ", s).strip()
    return s[:n]


def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def to_float(v):
    try:
        f = float(v)
        if math.isfinite(f):
            return f
    except (TypeError, ValueError):
        pass
    return None


def valid_coords(lat, lon):
    return (lat is not None and lon is not None
            and -90 <= lat <= 90 and -180 <= lon <= 180)


def city_xy(city):
    return CITY_COORDS.get(clean(city, 60).lower())


def rank_for(donations):
    for need, name in RANKS:
        if donations >= need:
            return name
    return RANKS[-1][1]


def next_rank(donations):
    for need, name in reversed(RANKS):
        if need > donations:
            return {"name": name, "need": need - donations}
    return None


def short_name(n):
    parts = clean(n, 60).split()
    if len(parts) <= 1:
        return parts[0] if parts else "Donor"
    return "%s %s." % (parts[0], parts[-1][0].upper())


def next_eligible(last):
    if not last:
        return None
    try:
        d = datetime.strptime(last[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return (d + timedelta(days=COOLDOWN_DAYS)).isoformat()


def cooled_down(last):
    ne = next_eligible(last)
    return ne is None or ne <= date.today().isoformat()


def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    return get_db().execute("SELECT * FROM donors_pp WHERE id=? AND is_demo=0",
                            (uid,)).fetchone()


def need_login():
    u = current_user()
    if not u:
        return None, (jsonify(ok=False, error="Please log in first."), 401)
    return u, None


_hits = {}


def rate_ok(key, limit, window):
    t = time.time()
    arr = [x for x in _hits.get(key, []) if t - x < window]
    if len(arr) >= limit:
        _hits[key] = arr
        return False
    arr.append(t)
    _hits[key] = arr
    return True


def client_ip():
    xf = request.headers.get("X-Forwarded-For", "")
    return (xf.split(",")[0].strip() if xf else request.remote_addr) or "?"


def user_json(u):
    return {
        "uid": u["uid"], "name": u["name"], "phone": u["phone"],
        "blood_group": u["blood_group"], "city": u["city"],
        "org_type": u["org_type"], "org_name": u["org_name"],
        "available": bool(u["available"]), "donations": u["donations"],
        "points": u["points"], "rank": rank_for(u["donations"]),
        "next_rank": next_rank(u["donations"]),
        "last_donation": u["last_donation"],
        "next_eligible": next_eligible(u["last_donation"]),
        "eligible_now": cooled_down(u["last_donation"]),
        "photo_status": u["photo_status"],
    }


def metrics(db):
    donations = db.execute("SELECT COALESCE(SUM(units),0) FROM donations_pp").fetchone()[0]
    logs = db.execute("SELECT COUNT(*) FROM donations_pp").fetchone()[0]
    active = db.execute("SELECT COUNT(*) FROM donors_pp WHERE is_demo=0 AND available=1").fetchone()[0]
    rare = db.execute(
        "SELECT COUNT(*) FROM donors_pp WHERE is_demo=0 AND blood_group IN (%s)"
        % ",".join("?" * len(RARE_GROUPS)), RARE_GROUPS).fetchone()[0]
    sms = db.execute("SELECT COALESCE(SUM(sms_sent),0) FROM sos_pp").fetchone()[0]
    sos = db.execute("SELECT COUNT(*) FROM sos_pp").fetchone()[0]
    return {"donations_logged": logs, "units": donations,
            "lives_impacted": logs * LIVES_PER_DONATION,
            "active_donors": active, "rare_donors": rare,
            "sos_total": sos, "sos_sms_sent": sms}


# ----------------------------------------------------------------- SMS
def send_sms(numbers, text):
    """Returns (sent_count, status). Never pretends to send."""
    if not numbers:
        return 0, "NO_RECIPIENTS"
    f2s = os.environ.get("FAST2SMS_KEY")
    sid = os.environ.get("TWILIO_ACCOUNT_SID")
    tok = os.environ.get("TWILIO_AUTH_TOKEN")
    frm = os.environ.get("TWILIO_PHONE_NUMBER")
    try:
        if f2s:
            r = requests.post(
                "https://www.fast2sms.com/dev/bulkV2",
                headers={"authorization": f2s},
                data={"route": "q", "message": text, "language": "english",
                      "flash": 0, "numbers": ",".join(numbers)}, timeout=15)
            ok = r.ok and r.json().get("return") is True
            return (len(numbers), "SENT") if ok else (0, "FAILED")
        if sid and tok and frm:
            sent = 0
            for n in numbers:
                r = requests.post(
                    "https://api.twilio.com/2010-04-01/Accounts/%s/Messages.json" % sid,
                    auth=(sid, tok),
                    data={"From": frm, "To": "+91" + n, "Body": text}, timeout=15)
                if r.status_code in (200, 201):
                    sent += 1
            return sent, ("SENT" if sent else "FAILED")
    except Exception:
        return 0, "FAILED"
    return 0, "NOT_CONFIGURED"


# ----------------------------------------------------------------- pages
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/healthz")
def healthz():
    return "ok"


VERIFY_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DONOR FINDER++ Pass Verification</title>
<style>body{font-family:system-ui,sans-serif;background:#12060a;color:#fff;display:grid;
place-items:center;min-height:100vh;margin:0}.c{background:#2a0d15;border:1px solid #7a1a2c;
border-radius:18px;padding:28px;max-width:380px;width:90%;text-align:center}
.ok{color:#5df08c}.no{color:#ff7b7b}.b{font-size:44px;font-weight:800;color:#ff4d6a}
small{color:#c9a0a8}a{color:#ff9aae}</style></head><body><div class="c">
{% if d %}
<h2 class="ok">&#10004; Valid DONOR FINDER++ Pass</h2>
<div class="b">{{ d.blood_group }}</div>
<h3>{{ d.name }}</h3>
<p>{{ d.rank }} &middot; {{ d.donations }} donation(s) logged</p>
<p>ID photo: <b>{{ d.photo_status }}</b></p>
<small>ID: {{ d.uid }}{% if d.is_demo %} &middot; DEMO PROFILE{% endif %}<br>
This pass proves membership only. Medical eligibility is always checked at the hospital.</small>
{% else %}
<h2 class="no">&#10008; Pass not found</h2><p>This ID is not registered.</p>
{% endif %}
<p><a href="/">Back to DONOR FINDER++</a></p></div></body></html>"""


@app.route("/verify/<uid>")
def verify(uid):
    r = get_db().execute("SELECT * FROM donors_pp WHERE uid=?", (clean(uid, 30),)).fetchone()
    d = None
    if r:
        d = {"uid": r["uid"], "name": short_name(r["name"]),
             "blood_group": r["blood_group"], "rank": rank_for(r["donations"]),
             "donations": r["donations"], "photo_status": r["photo_status"],
             "is_demo": bool(r["is_demo"])}
    return render_template_string(VERIFY_HTML, d=d)


# ----------------------------------------------------------------- bootstrap
@app.route("/api/bootstrap")
def bootstrap():
    db = get_db()
    me = current_user()
    lat = to_float(request.args.get("lat"))
    lon = to_float(request.args.get("lon"))
    have = valid_coords(lat, lon)

    donors = []
    for r in db.execute("SELECT * FROM donors_pp WHERE available=1 ORDER BY points DESC LIMIT 400"):
        xy = (r["lat"], r["lon"]) if r["lat"] is not None else city_xy(r["city"])
        dist = None
        if have and xy:
            dist = round(haversine(lat, lon, xy[0], xy[1]), 1)
        donors.append({
            "uid": r["uid"], "name": short_name(r["name"]),
            "blood_group": r["blood_group"], "city": r["city"],
            "org_name": r["org_name"], "rank": rank_for(r["donations"]),
            "verified": r["photo_status"] == "verified",
            "eligible": cooled_down(r["last_donation"]),
            "demo": bool(r["is_demo"]), "distance_km": dist,
            "phone": r["phone"] if (me and not r["is_demo"]) else None,
        })
    if have:
        donors.sort(key=lambda d: (d["distance_km"] is None, d["distance_km"] or 0))

    camps = []
    today = date.today().isoformat()
    for r in db.execute("SELECT * FROM camps_pp WHERE camp_date>=? ORDER BY camp_date LIMIT 200", (today,)):
        xy = (r["lat"], r["lon"]) if r["lat"] is not None else city_xy(r["city"])
        dist = round(haversine(lat, lon, xy[0], xy[1]), 1) if (have and xy) else None
        pledges = db.execute("SELECT COUNT(*) FROM pledges_pp WHERE camp_id=?", (r["id"],)).fetchone()[0]
        mine = bool(me and db.execute("SELECT 1 FROM pledges_pp WHERE camp_id=? AND donor_id=?",
                                      (r["id"], me["id"])).fetchone())
        camps.append({
            "id": r["id"], "title": r["title"], "organizer": r["organizer"],
            "city": r["city"], "address": r["address"], "date": r["camp_date"],
            "time": r["camp_time"], "contact": r["contact"],
            "sample": bool(r["is_sample"]), "lat": r["lat"], "lon": r["lon"],
            "distance_km": dist, "pledges": pledges, "pledged": mine,
        })
    if have:
        camps.sort(key=lambda c: (c["distance_km"] is None, c["distance_km"] or 0, c["date"]))

    since = (datetime.utcnow() - timedelta(hours=48)).strftime("%Y-%m-%d %H:%M:%S")
    sos = [{"blood_group": r["blood_group"], "hospital": r["hospital"], "city": r["city"],
            "units": r["units"], "note": r["note"], "created_at": r["created_at"],
            "contact": r["contact"] if me else None}
           for r in db.execute("SELECT * FROM sos_pp WHERE created_at>=? ORDER BY id DESC LIMIT 30", (since,))]

    orgs = [{"type": r["org_type"], "name": r["org_name"], "points": r["p"],
             "donors": r["n"], "donations": r["d"]}
            for r in db.execute(
                """SELECT org_type,org_name,SUM(points) p,COUNT(*) n,SUM(donations) d
                   FROM donors_pp WHERE org_name<>'' GROUP BY org_type,org_name
                   ORDER BY p DESC LIMIT 30""")]
    heroes = [{"name": short_name(r["name"]), "points": r["points"],
               "rank": rank_for(r["donations"]), "blood_group": r["blood_group"],
               "org_name": r["org_name"], "demo": bool(r["is_demo"])}
              for r in db.execute("SELECT * FROM donors_pp ORDER BY points DESC LIMIT 10")]

    return jsonify(ok=True, me=user_json(me) if me else None, metrics=metrics(db),
                   donors=donors, camps=camps, sos=sos,
                   leaderboard={"orgs": orgs, "heroes": heroes},
                   groups={"standard": STD_GROUPS, "rare": RARE_GROUPS},
                   compat=COMPAT, org_types=ORG_TYPES,
                   cities=sorted({c.title() for c in CITY_COORDS}),
                   cooldown_days=COOLDOWN_DAYS)


# ----------------------------------------------------------------- auth
@app.route("/api/register", methods=["POST"])
def register():
    d = request.get_json(silent=True) or {}
    if not rate_ok("reg:" + client_ip(), 10, 3600):
        return jsonify(ok=False, error="Too many sign-ups from this network. Try later."), 429
    name = clean(d.get("name"), 60)
    phone = re.sub(r"\D", "", clean(d.get("phone"), 20))[-10:]
    pw = str(d.get("password") or "")
    bg = clean(d.get("blood_group"), 30)
    city = clean(d.get("city"), 60)
    org_type = clean(d.get("org_type"), 20)
    org_name = clean(d.get("org_name"), 80)
    if len(name) < 2:
        return jsonify(ok=False, error="Please enter your name."), 400
    if not re.match(r"^[6-9]\d{9}$", phone):
        return jsonify(ok=False, error="Enter a valid 10-digit Indian mobile number."), 400
    if len(pw) < 8:
        return jsonify(ok=False, error="Password must be at least 8 characters."), 400
    if bg not in ALL_GROUPS:
        return jsonify(ok=False, error="Choose a valid blood group."), 400
    if len(city) < 2:
        return jsonify(ok=False, error="Please enter your city."), 400
    if not d.get("consent"):
        return jsonify(ok=False, error="Consent is required to join the donor network."), 400
    if org_type not in ORG_TYPES:
        org_type = "Community"

    lat, lon = to_float(d.get("lat")), to_float(d.get("lon"))
    if not valid_coords(lat, lon):
        xy = city_xy(city)
        lat, lon = (xy if xy else (None, None))
    else:
        lat, lon = round(lat, 3), round(lon, 3)   # coarse on purpose

    photo, status = None, "none"
    p = d.get("photo")
    if p:
        if (isinstance(p, str) and p.startswith("data:image/jpeg;base64,")
                and len(p) <= 450000 and d.get("redacted")):
            photo, status = p, "pending"
        else:
            return jsonify(ok=False, error="Photo must be a JPEG with the Aadhaar number covered and confirmed."), 400

    db = get_db()
    if db.execute("SELECT 1 FROM donors_pp WHERE phone=?", (phone,)).fetchone():
        return jsonify(ok=False, error="This phone number is already registered. Please log in."), 409
    uid = "DF-" + secrets.token_hex(3).upper()
    while db.execute("SELECT 1 FROM donors_pp WHERE uid=?", (uid,)).fetchone():
        uid = "DF-" + secrets.token_hex(3).upper()
    cur = db.execute(
        """INSERT INTO donors_pp(uid,name,phone,password_hash,blood_group,city,lat,lon,
           org_type,org_name,photo_data,photo_status,created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (uid, name, phone, generate_password_hash(pw), bg, city, lat, lon,
         org_type, org_name, photo, status, now()))
    db.commit()
    session.clear()
    session.permanent = True
    session["uid"] = cur.lastrowid
    return jsonify(ok=True, me=user_json(current_user()))


@app.route("/api/login", methods=["POST"])
def login():
    d = request.get_json(silent=True) or {}
    ident = re.sub(r"\D", "", clean(d.get("phone"), 20))[-10:]
    pw = str(d.get("password") or "")
    if not rate_ok("login:%s:%s" % (client_ip(), ident), 6, 600):
        return jsonify(ok=False, error="Too many attempts. Wait 10 minutes and retry."), 429
    r = get_db().execute("SELECT * FROM donors_pp WHERE phone=? AND is_demo=0", (ident,)).fetchone()
    if not r or not check_password_hash(r["password_hash"], pw):
        return jsonify(ok=False, error="Wrong phone number or password."), 401
    session.clear()
    session.permanent = True
    session["uid"] = r["id"]
    return jsonify(ok=True, me=user_json(r))


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify(ok=True)


@app.route("/api/availability", methods=["POST"])
def availability():
    u, err = need_login()
    if err:
        return err
    d = request.get_json(silent=True) or {}
    val = 1 if d.get("available") else 0
    db = get_db()
    db.execute("UPDATE donors_pp SET available=? WHERE id=?", (val, u["id"]))
    db.commit()
    return jsonify(ok=True, available=bool(val))


# ----------------------------------------------------------------- SOS
@app.route("/api/sos", methods=["POST"])
def sos():
    u, err = need_login()
    if err:
        return err
    d = request.get_json(silent=True) or {}
    db = get_db()

    bg = clean(d.get("blood_group"), 30)
    hospital = clean(d.get("hospital"), 80)
    city = clean(d.get("city"), 60)
    contact = re.sub(r"\D", "", clean(d.get("contact"), 20))[-10:]
    patient = clean(d.get("patient"), 60)
    note = clean(d.get("note"), 200)
    try:
        units = max(1, min(10, int(d.get("units") or 1)))
        radius = max(1, min(500, int(d.get("radius") or 25)))
    except (TypeError, ValueError):
        return jsonify(ok=False, error="Units and radius must be numbers."), 400

    if bg not in ALL_GROUPS:
        return jsonify(ok=False, error="Choose the blood group needed."), 400
    if len(hospital) < 3:
        return jsonify(ok=False, error="Enter the hospital name."), 400
    if not re.match(r"^[6-9]\d{9}$", contact):
        return jsonify(ok=False, error="Enter a valid contact mobile number."), 400

    one_hr = (datetime.utcnow() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    if db.execute("SELECT COUNT(*) FROM sos_pp WHERE donor_id=? AND created_at>=?",
                  (u["id"], one_hr)).fetchone()[0] >= 3:
        return jsonify(ok=False, error="SOS limit reached (3 per hour). Please wait."), 429

    norm = re.sub(r"[^a-z0-9]", "", hospital.lower())
    h = hashlib.sha256(("%s|%s|%s" % (bg, norm, contact)).encode()).hexdigest()
    twelve = (datetime.utcnow() - timedelta(hours=12)).strftime("%Y-%m-%d %H:%M:%S")
    if db.execute("SELECT 1 FROM sos_pp WHERE hash=? AND created_at>=?", (h, twelve)).fetchone():
        return jsonify(ok=False, duplicate=True,
                       error="Duplicate alert blocked: an identical request was already broadcast in the last 12 hours."), 409

    lat, lon = to_float(d.get("lat")), to_float(d.get("lon"))
    if not valid_coords(lat, lon):
        xy = city_xy(city) or ((u["lat"], u["lon"]) if u["lat"] is not None else None)
        lat, lon = xy if xy else (None, None)

    eligible_groups = set(COMPAT.get(bg, [bg]))
    targets = []
    if lat is not None:
        rows = db.execute(
            "SELECT * FROM donors_pp WHERE available=1 AND is_demo=0 AND id<>?", (u["id"],)).fetchall()
        for r in rows:
            if r["blood_group"] not in eligible_groups or not cooled_down(r["last_donation"]):
                continue
            xy = (r["lat"], r["lon"]) if r["lat"] is not None else city_xy(r["city"])
            if not xy:
                continue
            dist = haversine(lat, lon, xy[0], xy[1])
            if dist <= radius:
                targets.append((dist, r["phone"]))
        targets.sort()
        targets = targets[:40]

    text = ("DONOR FINDER++ URGENT: %s blood needed (%d unit) at %s, %s. Contact %s. "
            "Donate only if eligible; the hospital will check your eligibility."
            % (bg, units, hospital, city or "nearby", contact))
    sent, status = send_sms([p for _, p in targets], text)

    db.execute(
        """INSERT INTO sos_pp(donor_id,patient,blood_group,hospital,city,contact,units,note,
           radius,hash,sms_sent,sms_status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (u["id"], patient, bg, hospital, city, contact, units, note, radius, h, sent, status, now()))
    db.commit()

    wa = "https://wa.me/?text=" + requests.utils.quote(
        "URGENT blood needed: %s, %d unit(s) at %s, %s. Contact %s. "
        "Shared via DONOR FINDER++" % (bg, units, hospital, city, contact))
    return jsonify(ok=True, matched=len(targets), sms_sent=sent, sms_status=status,
                   whatsapp=wa, radius=radius)


# ----------------------------------------------------------------- camps
@app.route("/api/camps", methods=["POST"])
def add_camp():
    u, err = need_login()
    if err:
        return err
    if not rate_ok("camp:%s" % u["id"], 5, 3600):
        return jsonify(ok=False, error="Too many camps submitted. Try later."), 429
    d = request.get_json(silent=True) or {}
    title = clean(d.get("title"), 80)
    organizer = clean(d.get("organizer"), 80)
    city = clean(d.get("city"), 60)
    address = clean(d.get("address"), 160)
    cdate = clean(d.get("date"), 10)
    ctime = clean(d.get("time"), 30)
    contact = clean(d.get("contact"), 20)
    if len(title) < 3 or len(city) < 2:
        return jsonify(ok=False, error="Camp title and city are required."), 400
    try:
        dd = datetime.strptime(cdate, "%Y-%m-%d").date()
    except ValueError:
        return jsonify(ok=False, error="Pick a valid camp date."), 400
    if dd < date.today() or dd > date.today() + timedelta(days=365):
        return jsonify(ok=False, error="Camp date must be within the next year."), 400
    lat, lon = to_float(d.get("lat")), to_float(d.get("lon"))
    if not valid_coords(lat, lon):
        xy = city_xy(city)
        lat, lon = xy if xy else (None, None)
    db = get_db()
    db.execute(
        """INSERT INTO camps_pp(title,organizer,city,address,lat,lon,camp_date,camp_time,
           contact,is_sample,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,0,?,?)""",
        (title, organizer, city, address, lat, lon, cdate, ctime, contact, u["id"], now()))
    db.commit()
    return jsonify(ok=True)


@app.route("/api/camps/<int:cid>/pledge", methods=["POST"])
def pledge(cid):
    u, err = need_login()
    if err:
        return err
    db = get_db()
    if not db.execute("SELECT 1 FROM camps_pp WHERE id=?", (cid,)).fetchone():
        return jsonify(ok=False, error="Camp not found."), 404
    db.execute("INSERT OR IGNORE INTO pledges_pp(camp_id,donor_id) VALUES(?,?)", (cid, u["id"]))
    db.commit()
    n = db.execute("SELECT COUNT(*) FROM pledges_pp WHERE camp_id=?", (cid,)).fetchone()[0]
    return jsonify(ok=True, pledges=n)


# ----------------------------------------------------------------- donations
@app.route("/api/donations", methods=["POST"])
def log_donation():
    u, err = need_login()
    if err:
        return err
    d = request.get_json(silent=True) or {}
    if not cooled_down(u["last_donation"]):
        return jsonify(ok=False, error="You can donate again on %s (%d-day gap)."
                       % (next_eligible(u["last_donation"]), COOLDOWN_DAYS)), 400
    place = clean(d.get("place"), 100)
    on = clean(d.get("date"), 10) or date.today().isoformat()
    try:
        dd = datetime.strptime(on, "%Y-%m-%d").date()
    except ValueError:
        return jsonify(ok=False, error="Invalid date."), 400
    if dd > date.today() or dd < date.today() - timedelta(days=30):
        return jsonify(ok=False, error="Date must be within the last 30 days."), 400
    db = get_db()
    db.execute("INSERT INTO donations_pp(donor_id,units,donated_on,place,created_at) VALUES(?,?,?,?,?)",
               (u["id"], 1, on, place, now()))
    db.execute("UPDATE donors_pp SET donations=donations+1, points=points+?, last_donation=? WHERE id=?",
               (POINTS_PER_UNIT, on, u["id"]))
    db.commit()
    return jsonify(ok=True, me=user_json(current_user()), metrics=metrics(db))


# ----------------------------------------------------------------- admin
def admin_ok():
    key = os.environ.get("ADMIN_KEY")
    sent = request.headers.get("X-Admin-Key", "")
    return bool(key) and secrets.compare_digest(key, sent)


@app.route("/api/admin/pending")
def admin_pending():
    if not admin_ok():
        return jsonify(ok=False, error="Forbidden"), 403
    rows = get_db().execute(
        "SELECT id,uid,name,blood_group,city,photo_data FROM donors_pp WHERE photo_status='pending'").fetchall()
    return jsonify(ok=True, pending=[dict(r) for r in rows])


@app.route("/api/admin/verify", methods=["POST"])
def admin_verify():
    if not admin_ok():
        return jsonify(ok=False, error="Forbidden"), 403
    d = request.get_json(silent=True) or {}
    status = "verified" if d.get("approve") else "rejected"
    db = get_db()
    db.execute("UPDATE donors_pp SET photo_status=?, photo_data=NULL WHERE uid=?",
               (status, clean(d.get("uid"), 30)))
    db.commit()
    return jsonify(ok=True, status=status)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
