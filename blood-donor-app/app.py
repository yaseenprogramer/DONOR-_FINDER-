import math, os, random, re, sqlite3
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote
from flask import Flask, g, jsonify, render_template, request

app = Flask(__name__)
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "donorpp_v2.db")
GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
CAN_GIVE = {"A+": ["A+", "A-", "O+", "O-"], "A-": ["A-", "O-"], "B+": ["B+", "B-", "O+", "O-"],
            "B-": ["B-", "O-"], "AB+": GROUPS, "AB-": ["A-", "B-", "AB-", "O-"],
            "O+": ["O+", "O-"], "O-": ["O-"]}
COOLDOWN, OTPS, PHONE = 90, {}, re.compile(r"[6-9]\d{9}")
# Set DEMO_PHONE to your own number: every alert for SAMPLE data then goes to you, never to a stranger.
DEMO = re.sub(r"\D", "", os.environ.get("DEMO_PHONE", ""))[-10:]
AREAS = [("Avadi", 13.1067, 80.0970), ("Ambattur", 13.1143, 80.1548), ("Anna Nagar", 13.0850, 80.2101),
         ("T Nagar", 13.0418, 80.2341), ("Guindy", 13.0067, 80.2206), ("Tambaram", 12.9249, 80.1000),
         ("Velachery", 12.9815, 80.2180), ("Poonamallee", 13.0473, 80.0945), ("Porur", 13.0382, 80.1565),
         ("Tiruvallur", 13.1431, 79.9086), ("Kanchipuram", 12.8342, 79.7036), ("Chennai Central", 13.0827, 80.2707)]
NAMES = ("Arun K,Priya S,Karthik R,Divya M,Mohammed A,Sneha V,Vignesh P,Lakshmi N,Rahul D,Fathima B,Suresh G,"
         "Anitha T,Naveen J,Meena R,Imran S,Kavya L,Harish B,Nithya P,Yusuf K,Deepa C,Gokul M,Revathi A,"
         "Joseph F,Shalini D").split(",")
BANKS = [("Avadi Community Blood Bank", 0), ("Ambattur Care Blood Centre", 1), ("Anna Nagar Lifeline Blood Hub", 2),
         ("Tambaram Lifeline Blood Bank", 5), ("Tiruvallur District Blood Centre", 9), ("Kanchi Government Blood Bank", 10)]
# group, patient, hospital, units, area index, responders
REQS = [("O-", "Mr. Raman", "Ambattur Care Hospital", 2, 1, 2), ("B+", "Baby Aadhira", "Tambaram Children's Ward", 1, 5, 0),
        ("A+", "Mrs. Fathima", "Tiruvallur Govt Hospital", 3, 9, 5)]


def init():
    c = sqlite3.connect(DB)
    c.executescript("""CREATE TABLE IF NOT EXISTS donors(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, name TEXT,
        phone TEXT UNIQUE, grp TEXT, lat REAL, lng REAL, last_donation TEXT, demo INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS requests(id INTEGER PRIMARY KEY AUTOINCREMENT, grp TEXT, patient TEXT, hospital TEXT,
        contact TEXT, units INTEGER, lat REAL, lng REAL, created TEXT, responders INTEGER DEFAULT 0,
        status TEXT DEFAULT 'open', demo INTEGER DEFAULT 0);""")
    if not c.execute("SELECT 1 FROM donors").fetchone():
        rnd = random.Random(7)
        groups = ["O+", "A+", "B+", "O-", "AB+", "A-", "B-", "O+", "A+", "AB-", "B+", "O+"]
        days = [200, 150, None, 120, 95, 300, 40, 180, None, 110, 20, 260]
        for i, n in enumerate(NAMES):
            _, la, lo = AREAS[(i * 5) % 12]
            d = days[(i * 5 + 1) % 12]
            c.execute("INSERT INTO donors(kind,name,phone,grp,lat,lng,last_donation,demo) VALUES('donor',?,?,?,?,?,?,1)",
                      (n, f"90000{i + 1:05d}", groups[(i * 7) % 12], la + rnd.uniform(-.02, .02),
                       lo + rnd.uniform(-.02, .02), (date.today() - timedelta(days=d)).isoformat() if d else None))
        for j, (n, a) in enumerate(BANKS):
            c.execute("INSERT INTO donors(kind,name,phone,grp,lat,lng,demo) VALUES('hospital',?,?,'ALL',?,?,1)",
                      (n, f"90001{j + 1:05d}", AREAS[a][1] + .01, AREAS[a][2] + .01))
        now = datetime.now(timezone.utc)
        for k, (gr, pt, h, u, a, rs) in enumerate(REQS):
            c.execute("INSERT INTO requests(grp,patient,hospital,contact,units,lat,lng,created,responders,demo)"
                      " VALUES(?,?,?,?,?,?,?,?,?,1)", (gr, pt, h, f"9000009{k:03d}", u, AREAS[a][1], AREAS[a][2],
                                                     (now - timedelta(minutes=4 + k * 14)).isoformat(), rs))
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
    return max(0, COOLDOWN - (date.today() - date.fromisoformat(last)).days) if last else 0


def minutes(t):
    return int((datetime.now(timezone.utc) - datetime.fromisoformat(t)).total_seconds() // 60)


def match(grp, lat, lng, radius):
    out, hidden = [], 0
    for r in db().execute("SELECT * FROM donors"):
        if r["grp"] != "ALL" and r["grp"] not in CAN_GIVE[grp]:
            continue
        d = km(lat, lng, r["lat"], r["lng"])
        if d > radius:
            continue
        if r["kind"] == "donor" and wait(r["last_donation"]):
            hidden += 1  # cooldown shield: never alert someone who donated recently
            continue
        out.append(dict(id=r["id"], kind=r["kind"], name=r["name"], grp=r["grp"], lat=r["lat"], lng=r["lng"],
                        km=round(d, 1), phone=r["phone"][:2] + "XXXXXX" + r["phone"][-2:], exact=r["grp"] == grp,
                        _p=DEMO if (r["demo"] and DEMO) else r["phone"]))
    out.sort(key=lambda x: x["km"])
    return out, hidden


@app.route("/")
def home():
    return render_template("index.html")


@app.get("/api/stats")
def stats():
    rows = db().execute("SELECT kind,last_donation FROM donors").fetchall()
    don = [r for r in rows if r["kind"] == "donor"]
    reqs = db().execute("SELECT COUNT(*) FROM requests WHERE status='open'").fetchone()[0]
    return jsonify(donors=len(don), banks=len(rows) - len(don),
                   eligible=sum(1 for r in don if not wait(r["last_donation"])), requests=reqs)


@app.get("/api/search")
def search():
    a = request.args
    grp = a.get("group", "O+")
    if grp not in GROUPS:
        return jsonify(error="Invalid blood group"), 400
    res, hidden = match(grp, num(a.get("lat"), -90, 90, 13.0827), num(a.get("lng"), -180, 180, 80.2707),
                        num(a.get("radius"), 1, 200, 15))
    for x in res:
        x.pop("_p")
    return jsonify(results=res, hidden=hidden, compatible=CAN_GIVE[grp])


@app.get("/api/requests")
def board():
    lat = num(request.args.get("lat"), -90, 90, 13.0827)
    lng = num(request.args.get("lng"), -180, 180, 80.2707)
    out = []
    for r in db().execute("SELECT * FROM requests WHERE status='open' ORDER BY id DESC LIMIT 40"):
        m = minutes(r["created"])
        m = m % 60 + 2 if r["demo"] else m  # sample requests stay fresh for the demo
        if m < 2880:
            out.append(dict(id=r["id"], grp=r["grp"], patient=r["patient"], hospital=r["hospital"], units=r["units"],
                            ago=m, responders=r["responders"], km=round(km(lat, lng, r["lat"], r["lng"]), 1)))
    return jsonify(requests=out[:8])


@app.post("/api/otp")
def otp():
    p = clean(body().get("phone"))
    if not PHONE.fullmatch(p):
        return jsonify(error="Enter a valid 10-digit mobile number"), 400
    OTPS[p] = str(random.randint(1000, 9999))
    # DEMO MODE: OTP is returned so the flow is visible. In production send it by SMS and drop demo_otp.
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
    hospital = str(j.get("hospital") or "").strip()[:60]
    cur = db().execute("INSERT INTO requests(grp,patient,hospital,contact,units,lat,lng,created) VALUES(?,?,?,?,?,?,?,?)",
                       (grp, patient, hospital, contact, units, lat, lng, datetime.now(timezone.utc).isoformat()))
    db().commit()
    res, hidden = match(grp, lat, lng, 25)
    if not res:
        res, hidden = match(grp, lat, lng, 80)
    msg = (f"URGENT: {units} unit(s) of {grp} blood needed for {patient}" + (f" at {hospital}" if hospital else "") +
           f". Location: https://maps.google.com/?q={lat},{lng} Contact: {contact}. Can you help? - Donor++")
    for x in res:
        x["wa"] = f"https://wa.me/91{x.pop('_p')}?text={quote(msg)}"
    return jsonify(id=cur.lastrowid, matches=res[:12], hidden=hidden)


@app.post("/api/respond")
def respond():
    r = db().execute("SELECT * FROM requests WHERE id=? AND status='open'",
                     (int(num(body().get("id"), 1, 10 ** 9, 0)),)).fetchone()
    if not r:
        return jsonify(error="This request is already closed"), 404
    db().execute("UPDATE requests SET responders=responders+1 WHERE id=?", (r["id"],))
    db().commit()
    to = DEMO if (r["demo"] and DEMO) else r["contact"]
    msg = f"Hi, I saw your {r['grp']} blood request for {r['patient']} on Donor++. I can donate. Where and when?"
    return jsonify(wa=f"https://wa.me/91{to}?text={quote(msg)}")


@app.post("/api/fulfill")
def fulfill():
    j = body()
    cur = db().execute("UPDATE requests SET status='fulfilled' WHERE id=? AND contact=?",
                       (int(num(j.get("id"), 1, 10 ** 9, 0)), clean(j.get("contact"))))
    db().commit()
    return jsonify(ok=cur.rowcount > 0)


init()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
