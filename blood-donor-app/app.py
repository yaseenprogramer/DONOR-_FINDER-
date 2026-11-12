import math, os, random, re, sqlite3
from datetime import date, timedelta
from urllib.parse import quote
from flask import Flask, g, jsonify, render_template, request

app = Flask(__name__)
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "donorpp.db")
GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
CAN_GIVE = {"A+": ["A+", "A-", "O+", "O-"], "A-": ["A-", "O-"], "B+": ["B+", "B-", "O+", "O-"],
            "B-": ["B-", "O-"], "AB+": GROUPS, "AB-": ["A-", "B-", "AB-", "O-"],
            "O+": ["O+", "O-"], "O-": ["O-"]}
COOLDOWN, OTPS, PHONE = 90, {}, re.compile(r"[6-9]\d{9}")
# kind, name, phone, group, lat, lng, days since last donation (None = never)
SEED = [
    ("donor", "Arun K", "9000000001", "O+", 13.1067, 80.0970, 200),
    ("donor", "Priya S", "9000000002", "A+", 13.1143, 80.1548, 150),
    ("donor", "Karthik R", "9000000003", "B+", 13.0850, 80.2101, None),
    ("donor", "Divya M", "9000000004", "O-", 13.0418, 80.2341, 120),
    ("donor", "Mohammed A", "9000000005", "AB+", 13.0067, 80.2206, 95),
    ("donor", "Sneha V", "9000000006", "A-", 12.9249, 80.1000, 300),
    ("donor", "Vignesh P", "9000000007", "B-", 12.9815, 80.2180, 40),
    ("donor", "Lakshmi N", "9000000008", "O+", 13.0473, 80.0945, 180),
    ("donor", "Rahul D", "9000000009", "A+", 13.1431, 79.9086, None),
    ("donor", "Fathima B", "9000000010", "O+", 12.8342, 79.7036, 110),
    ("donor", "Suresh G", "9000000011", "B+", 13.0382, 80.1565, 20),
    ("hospital", "Avadi Community Blood Bank", "9000000012", "ALL", 13.1090, 80.1010, None),
    ("hospital", "Ambattur Care Blood Centre", "9000000013", "ALL", 13.1180, 80.1500, None),
    ("hospital", "Tambaram Lifeline Blood Bank", "9000000014", "ALL", 12.9230, 80.1180, None),
    ("hospital", "Tiruvallur District Blood Centre", "9000000015", "ALL", 13.1400, 79.9100, None),
    ("hospital", "Kanchi Government Blood Bank", "9000000016", "ALL", 12.8400, 79.7100, None),
]


def init():
    c = sqlite3.connect(DB)
    c.executescript("""CREATE TABLE IF NOT EXISTS donors(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT,
        name TEXT, phone TEXT UNIQUE, grp TEXT, lat REAL, lng REAL, last_donation TEXT);
        CREATE TABLE IF NOT EXISTS requests(id INTEGER PRIMARY KEY AUTOINCREMENT, grp TEXT, patient TEXT,
        contact TEXT, units INTEGER, lat REAL, lng REAL);""")
    if not c.execute("SELECT 1 FROM donors").fetchone():
        for k, n, p, g_, la, lo, d in SEED:
            last = (date.today() - timedelta(days=d)).isoformat() if d else None
            c.execute("INSERT INTO donors(kind,name,phone,grp,lat,lng,last_donation) VALUES(?,?,?,?,?,?,?)",
                      (k, n, p, g_, la, lo, last))
    c.commit()
    c.close()


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d:
        d.close()


def body():
    return request.get_json(silent=True) or {}


def clean(p):
    return re.sub(r"\D", "", str(p or ""))[-10:]


def num(v, lo, hi, default=None):
    try:
        x = float(v)
        return x if lo <= x <= hi else default
    except (TypeError, ValueError):
        return default


def km(a, b, c, d):
    p = math.pi / 180
    h = 0.5 - math.cos((c - a) * p) / 2 + math.cos(a * p) * math.cos(c * p) * (1 - math.cos((d - b) * p)) / 2
    return 12742 * math.asin(math.sqrt(h))


def wait(last):
    if not last:
        return 0
    return max(0, COOLDOWN - (date.today() - date.fromisoformat(last)).days)


def match(grp, lat, lng, radius):
    out, hidden = [], 0
    for r in db().execute("SELECT * FROM donors"):
        if r["grp"] != "ALL" and r["grp"] not in CAN_GIVE[grp]:
            continue
        d = km(lat, lng, r["lat"], r["lng"])
        if d > radius:
            continue
        if r["kind"] == "donor" and wait(r["last_donation"]):
            hidden += 1  # cooldown shield: never alert a donor who gave blood recently
            continue
        out.append(dict(id=r["id"], kind=r["kind"], name=r["name"], grp=r["grp"], lat=r["lat"], lng=r["lng"],
                        km=round(d, 1), phone=r["phone"][:2] + "XXXXXX" + r["phone"][-2:],
                        exact=r["grp"] == grp, _p=r["phone"]))
    out.sort(key=lambda x: x["km"])
    return out, hidden


@app.route("/")
def home():
    return render_template("index.html")


@app.get("/api/stats")
def stats():
    rows = db().execute("SELECT kind,last_donation FROM donors").fetchall()
    don = [r for r in rows if r["kind"] == "donor"]
    reqs = db().execute("SELECT COUNT(*) FROM requests").fetchone()[0]
    return jsonify(donors=len(don), banks=len(rows) - len(don),
                   eligible=sum(1 for r in don if not wait(r["last_donation"])), requests=reqs)


@app.get("/api/search")
def search():
    a = request.args
    grp = a.get("group", "O+")
    if grp not in GROUPS:
        return jsonify(error="Invalid blood group"), 400
    lat = num(a.get("lat"), -90, 90, 13.0827)
    lng = num(a.get("lng"), -180, 180, 80.2707)
    res, hidden = match(grp, lat, lng, num(a.get("radius"), 1, 200, 15))
    for x in res:
        x.pop("_p")
    return jsonify(results=res, hidden=hidden, compatible=CAN_GIVE[grp])


@app.post("/api/otp")
def otp():
    p = clean(body().get("phone"))
    if not PHONE.fullmatch(p):
        return jsonify(error="Enter a valid 10-digit mobile number"), 400
    OTPS[p] = str(random.randint(1000, 9999))
    # DEMO MODE: the OTP is returned so judges can see the flow. In production, send it by SMS and drop demo_otp.
    return jsonify(ok=True, demo_otp=OTPS[p])


@app.post("/api/register")
def register():
    j = body()
    p = clean(j.get("phone"))
    kind = "hospital" if j.get("kind") == "hospital" else "donor"
    grp = "ALL" if kind == "hospital" else j.get("group")
    name = str(j.get("name") or "").strip()[:60]
    lat, lng = num(j.get("lat"), -90, 90), num(j.get("lng"), -180, 180)
    last = (j.get("last_donation") or None) if kind == "donor" else None
    try:
        if last and date.fromisoformat(last) > date.today():
            raise ValueError
    except (ValueError, TypeError):
        return jsonify(error="Last donation date is invalid"), 400
    if not name or grp not in GROUPS + ["ALL"] or lat is None or lng is None or not PHONE.fullmatch(p):
        return jsonify(error="Please fill every field correctly"), 400
    if OTPS.get(p) != str(j.get("otp")):
        return jsonify(error="Wrong or missing OTP"), 400
    try:
        cur = db().execute("INSERT INTO donors(kind,name,phone,grp,lat,lng,last_donation) VALUES(?,?,?,?,?,?,?)",
                           (kind, name, p, grp, lat, lng, last))
        db().commit()
    except sqlite3.IntegrityError:
        return jsonify(error="This number is already registered"), 409
    OTPS.pop(p, None)
    return jsonify(ok=True, kind=kind, grp=grp, pass_id=f"D++{cur.lastrowid:04d}", wait=wait(last))


@app.post("/api/request")
def sos():
    j = body()
    grp = j.get("group")
    lat, lng = num(j.get("lat"), -90, 90), num(j.get("lng"), -180, 180)
    contact = clean(j.get("contact"))
    if grp not in GROUPS or lat is None or lng is None:
        return jsonify(error="Choose a blood group first"), 400
    if not PHONE.fullmatch(contact):
        return jsonify(error="Enter a valid contact number"), 400
    units = int(num(j.get("units"), 1, 10, 1))
    patient = str(j.get("patient") or "a patient").strip()[:40]
    db().execute("INSERT INTO requests(grp,patient,contact,units,lat,lng) VALUES(?,?,?,?,?,?)",
                 (grp, patient, contact, units, lat, lng))
    db().commit()
    res, hidden = match(grp, lat, lng, 25)
    if not res:
        res, hidden = match(grp, lat, lng, 80)
    msg = (f"URGENT: {units} unit(s) of {grp} blood needed for {patient}. "
           f"Location: https://maps.google.com/?q={lat},{lng} Contact: {contact}. Can you help? - Donor++")
    for x in res:
        x["wa"] = f"https://wa.me/91{x.pop('_p')}?text={quote(msg)}"
    return jsonify(matches=res[:12], hidden=hidden)


init()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
