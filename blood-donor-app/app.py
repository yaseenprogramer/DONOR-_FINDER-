import json, math, os, queue, random, re, secrets, sqlite3, threading, time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote
from flask import Flask, Response, g, jsonify, render_template, request, stream_with_context

app = Flask(__name__)
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "donorpp_v3.db")
GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
CAN_GIVE = {"A+": ["A+", "A-", "O+", "O-"], "A-": ["A-", "O-"], "B+": ["B+", "B-", "O+", "O-"],
            "B-": ["B-", "O-"], "AB+": GROUPS, "AB-": ["A-", "B-", "AB-", "O-"],
            "O+": ["O+", "O-"], "O-": ["O-"]}
INTERVAL = {"M": 90, "F": 120}  # MoHFW guideline: days between whole-blood donations
URG = {"critical": 0, "urgent": 1, "planned": 2}
PHONE = re.compile(r"[6-9]\d{9}")
DEMO_MODE = os.environ.get("DEMO_MODE", "1") == "1"  # shows OTPs on screen and enables the demo login
OTPS, HITS, SUBS, LOCK = {}, {}, set(), threading.Lock()


def clean(p):
    return re.sub(r"\D", "", str(p or ""))[-10:]


DEMO = clean(os.environ.get("DEMO_PHONE"))  # your own number: sample-data alerts go to you, never to a stranger
AREAS = [("Avadi", 13.1067, 80.0970), ("Ambattur", 13.1143, 80.1548), ("Anna Nagar", 13.0850, 80.2101),
         ("T Nagar", 13.0418, 80.2341), ("Guindy", 13.0067, 80.2206), ("Tambaram", 12.9249, 80.1000),
         ("Velachery", 12.9815, 80.2180), ("Poonamallee", 13.0473, 80.0945), ("Porur", 13.0382, 80.1565),
         ("Tiruvallur", 13.1431, 79.9086), ("Kanchipuram", 12.8342, 79.7036), ("Chennai Central", 13.0827, 80.2707)]
NAMES = ("Arun K,Priya S,Karthik R,Divya M,Mohammed A,Sneha V,Vignesh P,Lakshmi N,Rahul D,Fathima B,Suresh G,"
         "Anitha T,Naveen J,Meena R,Imran S,Kavya L,Harish B,Nithya P,Yusuf K,Deepa C,Gokul M,Revathi A,"
         "Joseph F,Shalini D").split(",")
BANKS = [("Avadi Community Blood Bank", 0), ("Ambattur Care Blood Centre", 1), ("Anna Nagar Lifeline Blood Hub", 2),
         ("Tambaram Lifeline Blood Bank", 5), ("Tiruvallur District Blood Centre", 9), ("Kanchi Government Blood Bank", 10)]
# group, patient, hospital, units, urgency, area index, responders
REQS = [("O-", "Mr. Raman", "Ambattur Care Hospital", 2, "critical", 1, 2),
        ("B+", "Baby Aadhira", "Tambaram Children's Ward", 1, "urgent", 5, 0),
        ("A+", "Mrs. Fathima", "Tiruvallur Govt Hospital", 3, "planned", 9, 3)]


def init():
    c = sqlite3.connect(DB)
    c.executescript("""CREATE TABLE IF NOT EXISTS donors(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, name TEXT,
        phone TEXT UNIQUE, grp TEXT, sex TEXT DEFAULT 'M', lat REAL, lng REAL, last_donation TEXT,
        available INTEGER DEFAULT 1, stock TEXT, token TEXT, demo INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS requests(id INTEGER PRIMARY KEY AUTOINCREMENT, grp TEXT, patient TEXT, hospital TEXT,
        contact TEXT, units INTEGER, urgency TEXT, lat REAL, lng REAL, created TEXT, status TEXT DEFAULT 'open',
        secret TEXT, demo INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS responses(id INTEGER PRIMARY KEY AUTOINCREMENT, request_id INTEGER, donor_id INTEGER,
        created TEXT, UNIQUE(request_id, donor_id));""")
    if not c.execute("SELECT 1 FROM donors").fetchone():
        rnd = random.Random(7)
        groups = ["O+", "A+", "B+", "O-", "AB+", "A-", "B-", "O+", "A+", "AB-", "B+", "O+"]
        days = [200, 150, None, 120, 95, 300, 40, 180, None, 110, 20, 260]
        for i, n in enumerate(NAMES):
            _, la, lo = AREAS[(i * 5) % 12]
            d = days[(i * 5 + 1) % 12]
            c.execute("INSERT INTO donors(kind,name,phone,grp,sex,lat,lng,last_donation,demo) VALUES('donor',?,?,?,?,?,?,?,1)",
                      (n, f"90000{i + 1:05d}", groups[(i * 7) % 12], "F" if i % 2 else "M", la + rnd.uniform(-.02, .02),
                       lo + rnd.uniform(-.02, .02), (date.today() - timedelta(days=d)).isoformat() if d else None))
        for j, (n, a) in enumerate(BANKS):
            stock = {x: rnd.randint(0, 14) for x in GROUPS}
            c.execute("INSERT INTO donors(kind,name,phone,grp,lat,lng,stock,demo) VALUES('hospital',?,?,'ALL',?,?,?,1)",
                      (n, f"90001{j + 1:05d}", AREAS[a][1] + .01, AREAS[a][2] + .01, json.dumps(stock)))
        now = datetime.now(timezone.utc)
        for k, (gr, pt, h, u, ur, a, rs) in enumerate(REQS):
            cur = c.execute("INSERT INTO requests(grp,patient,hospital,contact,units,urgency,lat,lng,created,secret,demo)"
                            " VALUES(?,?,?,?,?,?,?,?,?,?,1)", (gr, pt, h, f"9000009{k:03d}", u, ur, AREAS[a][1], AREAS[a][2],
                                                               (now - timedelta(minutes=4 + k * 14)).isoformat(), secrets.token_urlsafe(8)))
            for did in range(1, rs + 1):
                c.execute("INSERT OR IGNORE INTO responses(request_id,donor_id,created) VALUES(?,?,?)", (cur.lastrowid, did, now.isoformat()))
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


@app.after_request
def headers(r):
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["Referrer-Policy"] = "same-origin"
    return r


@app.errorhandler(404)
def nf(_):
    return (jsonify(error="Not found"), 404) if request.path.startswith("/api/") else render_template("index.html")


@app.errorhandler(500)
def ise(_):
    return jsonify(error="Server error, please retry"), 500


def body():
    return request.get_json(silent=True) or {}


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


def wait(last, sex="M"):
    return max(0, INTERVAL.get(sex, 90) - (date.today() - date.fromisoformat(last)).days) if last else 0


def minutes(t):
    return int((datetime.now(timezone.utc) - datetime.fromisoformat(t)).total_seconds() // 60)


def mask(p):
    return p[:2] + "XXXXXX" + p[-2:]


def to_phone(r):
    return DEMO if (r["demo"] and DEMO) else r["phone"]


def ip():
    return request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr or "?"


def limited(key, n, per):
    now = time.time()
    h = [t for t in HITS.get(key, []) if now - t < per]
    HITS[key] = h
    if len(h) >= n:
        return True
    h.append(now)
    return False


def user():
    t = request.headers.get("X-Token", "")
    return db().execute("SELECT * FROM donors WHERE token=?", (t,)).fetchone() if len(t) > 8 else None


def profile(r):
    d = r["kind"] == "donor"
    iv = INTERVAL.get(r["sex"], 90) if d else 0
    nxt = (date.fromisoformat(r["last_donation"]) + timedelta(days=iv)).isoformat() if d and r["last_donation"] else None
    return dict(id=r["id"], kind=r["kind"], name=r["name"], grp=r["grp"], sex=r["sex"], lat=r["lat"], lng=r["lng"],
                available=bool(r["available"]), last_donation=r["last_donation"], interval=iv, next=nxt,
                wait=wait(r["last_donation"], r["sex"]) if d else 0, pass_id=f"D++{r['id']:04d}", phone=mask(r["phone"]),
                stock=json.loads(r["stock"]) if r["stock"] else None)


def publish(event, data=None):
    msg = f"event: {event}\ndata: {json.dumps(data or {})}\n\n"
    with LOCK:
        for q in list(SUBS):
            try:
                q.put_nowait(msg)
            except queue.Full:
                pass


def match(grp, lat, lng, radius, skip=()):
    out, hidden = [], 0
    for r in db().execute("SELECT * FROM donors WHERE available=1"):
        if r["id"] in skip:
            continue
        units = None
        if r["kind"] == "hospital":
            if r["stock"]:
                units = sum(json.loads(r["stock"]).get(x, 0) for x in CAN_GIVE[grp])
                if units <= 0:
                    continue
        elif r["grp"] not in CAN_GIVE[grp]:
            continue
        d = km(lat, lng, r["lat"], r["lng"])
        if d > radius:
            continue
        if r["kind"] == "donor" and wait(r["last_donation"], r["sex"]):
            hidden += 1  # cooldown shield: never alert someone who donated recently
            continue
        out.append(dict(id=r["id"], kind=r["kind"], name=r["name"], grp=r["grp"], lat=r["lat"], lng=r["lng"],
                        km=round(d, 1), phone=mask(r["phone"]), exact=r["grp"] == grp, units=units, _p=to_phone(r)))
    out.sort(key=lambda x: x["km"])
    return out, hidden


def open_requests(lat, lng):
    out = []
    for r in db().execute("SELECT * FROM requests WHERE status='open' ORDER BY id DESC LIMIT 80"):
        m = minutes(r["created"])
        m = m % 60 + 2 if r["demo"] else m  # sample requests stay fresh for the demo
        if m >= (4320 if r["urgency"] == "planned" else 1440):
            continue
        n = db().execute("SELECT COUNT(*) FROM responses WHERE request_id=?", (r["id"],)).fetchone()[0]
        out.append(dict(id=r["id"], grp=r["grp"], patient=r["patient"], hospital=r["hospital"], units=r["units"],
                        urgency=r["urgency"], ago=m, responders=n, lat=round(r["lat"], 2), lng=round(r["lng"], 2),
                        km=round(km(lat, lng, r["lat"], r["lng"]), 1)))
    out.sort(key=lambda x: (URG.get(x["urgency"], 1), x["ago"]))
    return out


@app.route("/")
def home():
    return render_template("index.html")


@app.get("/healthz")
def healthz():
    return "ok"


@app.get("/api/stream")
def stream():
    q = queue.Queue(maxsize=200)
    with LOCK:
        SUBS.add(q)
    publish("presence", {"online": len(SUBS)})

    def gen():
        try:
            yield "retry: 3000\n\n"
            while True:
                try:
                    yield q.get(timeout=15)
                except queue.Empty:
                    yield ": ping\n\n"
        finally:
            with LOCK:
                SUBS.discard(q)
            publish("presence", {"online": len(SUBS)})
    return Response(stream_with_context(gen()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/stats")
def stats():
    rows = db().execute("SELECT kind,last_donation,sex,available FROM donors").fetchall()
    don = [r for r in rows if r["kind"] == "donor"]
    open_n = db().execute("SELECT COUNT(*) FROM requests WHERE status='open'").fetchone()[0]
    return jsonify(donors=len(don), banks=len(rows) - len(don), requests=open_n, online=len(SUBS), demo=DEMO_MODE,
                   eligible=sum(1 for r in don if r["available"] and not wait(r["last_donation"], r["sex"])))


@app.get("/api/search")
def search():
    a = request.args
    grp = a.get("group", "O+")
    if grp not in GROUPS:
        return jsonify(error="Invalid blood group"), 400
    lat, lng = num(a.get("lat"), -90, 90, 13.0827), num(a.get("lng"), -180, 180, 80.2707)
    radius = num(a.get("radius"), 1, 200, 15)
    res, hidden = match(grp, lat, lng, radius)
    for x in res:
        x.pop("_p")
    return jsonify(results=res, hidden=hidden, compatible=CAN_GIVE[grp],
                   sos=[r for r in open_requests(lat, lng) if r["km"] <= radius])


@app.get("/api/requests")
def board():
    lat, lng = num(request.args.get("lat"), -90, 90, 13.0827), num(request.args.get("lng"), -180, 180, 80.2707)
    return jsonify(requests=open_requests(lat, lng)[:10])


@app.post("/api/otp")
def otp():
    p = clean(body().get("phone"))
    if not PHONE.fullmatch(p):
        return jsonify(error="Enter a valid 10-digit mobile number"), 400
    if limited("otp:" + p, 5, 600) or limited("otpip:" + ip(), 20, 600):
        return jsonify(error="Too many OTP requests. Try again in a few minutes."), 429
    OTPS[p] = str(random.randint(1000, 9999))
    # In production send OTPS[p] by SMS and set DEMO_MODE=0, which removes demo_otp from this response.
    return jsonify(ok=True, demo_otp=OTPS[p] if DEMO_MODE else None)


def session(row):
    tok = secrets.token_urlsafe(16)
    db().execute("UPDATE donors SET token=? WHERE id=?", (tok, row["id"]))
    db().commit()
    return jsonify(token=tok, me=profile(db().execute("SELECT * FROM donors WHERE id=?", (row["id"],)).fetchone()))


@app.post("/api/register")
def register():
    j = body()
    p = clean(j.get("phone"))
    kind = "hospital" if j.get("kind") == "hospital" else "donor"
    grp = "ALL" if kind == "hospital" else j.get("group")
    sex = "F" if j.get("sex") == "F" else "M"
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
    if not j.get("consent") or (kind == "donor" and not j.get("declared")):
        return jsonify(error="Please accept the consent and eligibility declarations"), 400
    if OTPS.get(p) != str(j.get("otp")):
        return jsonify(error="Wrong or missing OTP"), 400
    try:
        cur = db().execute("INSERT INTO donors(kind,name,phone,grp,sex,lat,lng,last_donation,stock) VALUES(?,?,?,?,?,?,?,?,?)",
                           (kind, name, p, grp, sex, lat, lng, last, json.dumps({x: 0 for x in GROUPS}) if kind == "hospital" else None))
        db().commit()
    except sqlite3.IntegrityError:
        return jsonify(error="This number is already registered. Please log in."), 409
    OTPS.pop(p, None)
    publish("donor_new", {"kind": kind})
    return session(db().execute("SELECT * FROM donors WHERE id=?", (cur.lastrowid,)).fetchone())


@app.post("/api/login")
def login():
    j = body()
    p = clean(j.get("phone"))
    if OTPS.get(p) != str(j.get("otp")):
        return jsonify(error="Wrong or missing OTP"), 400
    r = db().execute("SELECT * FROM donors WHERE phone=?", (p,)).fetchone()
    if not r:
        return jsonify(error="No account for this number. Please join first."), 404
    OTPS.pop(p, None)
    return session(r)


@app.post("/api/demo-login")
def demo_login():
    if not DEMO_MODE:
        return jsonify(error="Not available"), 404
    r = db().execute("SELECT * FROM donors WHERE demo=1 AND kind='donor' AND grp='O+' ORDER BY id LIMIT 1").fetchone()
    return session(r)


@app.get("/api/me")
def me():
    u = user()
    return (jsonify(me=profile(u)) if u else (jsonify(error="Please log in"), 401))


@app.post("/api/me/donated")
def donated():
    u = user()
    if not u or u["kind"] != "donor":
        return jsonify(error="Please log in as a donor"), 401
    db().execute("UPDATE donors SET last_donation=? WHERE id=?", (date.today().isoformat(), u["id"]))
    db().commit()
    publish("stats")
    return jsonify(me=profile(db().execute("SELECT * FROM donors WHERE id=?", (u["id"],)).fetchone()))


@app.post("/api/me/available")
def available():
    u = user()
    if not u:
        return jsonify(error="Please log in"), 401
    db().execute("UPDATE donors SET available=? WHERE id=?", (1 if body().get("on") else 0, u["id"]))
    db().commit()
    publish("stats")
    return jsonify(me=profile(db().execute("SELECT * FROM donors WHERE id=?", (u["id"],)).fetchone()))


@app.post("/api/me/location")
def relocate():
    u = user()
    lat, lng = num(body().get("lat"), -90, 90), num(body().get("lng"), -180, 180)
    if not u or lat is None or lng is None:
        return jsonify(error="Please log in and allow location"), 401
    db().execute("UPDATE donors SET lat=?, lng=? WHERE id=?", (lat, lng, u["id"]))
    db().commit()
    publish("stats")
    return jsonify(me=profile(db().execute("SELECT * FROM donors WHERE id=?", (u["id"],)).fetchone()))


@app.post("/api/me/stock")
def set_stock():
    u = user()
    if not u or u["kind"] != "hospital":
        return jsonify(error="Only blood banks can publish stock"), 401
    st = body().get("stock") or {}
    clean_st = {x: int(num(st.get(x), 0, 999, 0)) for x in GROUPS}
    db().execute("UPDATE donors SET stock=? WHERE id=?", (json.dumps(clean_st), u["id"]))
    db().commit()
    publish("stock")
    return jsonify(me=profile(db().execute("SELECT * FROM donors WHERE id=?", (u["id"],)).fetchone()))


@app.delete("/api/me")
def delete_me():
    u = user()
    if not u:
        return jsonify(error="Please log in"), 401
    db().execute("DELETE FROM responses WHERE donor_id=?", (u["id"],))
    db().execute("DELETE FROM donors WHERE id=?", (u["id"],))
    db().commit()
    publish("stats")
    return jsonify(ok=True)


@app.post("/api/request")
def sos():
    j = body()
    grp = j.get("group")
    lat, lng = num(j.get("lat"), -90, 90), num(j.get("lng"), -180, 180)
    contact = clean(j.get("contact"))
    if grp not in GROUPS or lat is None or lng is None:
        return jsonify(error="Choose a blood group and a location first"), 400
    if not PHONE.fullmatch(contact):
        return jsonify(error="Enter a valid contact number"), 400
    if limited("req:" + ip(), 6, 3600):
        return jsonify(error="Too many requests from this device. Please call 108 or 112 for urgent help."), 429
    urgency = j.get("urgency") if j.get("urgency") in URG else "urgent"
    units = int(num(j.get("units"), 1, 10, 1))
    patient = str(j.get("patient") or "a patient").strip()[:40]
    hospital = str(j.get("hospital") or "").strip()[:60]
    secret = secrets.token_urlsafe(12)
    cur = db().execute("INSERT INTO requests(grp,patient,hospital,contact,units,urgency,lat,lng,created,secret) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (grp, patient, hospital, contact, units, urgency, lat, lng, datetime.now(timezone.utc).isoformat(), secret))
    db().commit()
    publish("request_new", dict(id=cur.lastrowid, grp=grp, units=units, urgency=urgency, patient=patient,
                                hospital=hospital, lat=round(lat, 2), lng=round(lng, 2)))
    return jsonify(id=cur.lastrowid, secret=secret)


def owned(rid):
    r = db().execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone()
    return r if r and secrets.compare_digest(str(r["secret"]), str(request.args.get("secret") or body().get("secret") or "")) else None


@app.get("/api/request/<int:rid>")
def track(rid):
    r = owned(rid)
    if not r:
        return jsonify(error="Request not found"), 404
    rows = db().execute("SELECT d.* FROM responses s JOIN donors d ON d.id=s.donor_id WHERE s.request_id=? ORDER BY s.id", (rid,)).fetchall()
    thanks = f"Thank you for responding to the {r['grp']} blood request for {r['patient']}. Where can we meet?"
    resp = [dict(name=d["name"], grp=d["grp"], km=round(km(r["lat"], r["lng"], d["lat"], d["lng"]), 1),
                 wa=f"https://wa.me/91{to_phone(d)}?text={quote(thanks)}") for d in rows]
    res, hidden = match(r["grp"], r["lat"], r["lng"], 25, skip={d["id"] for d in rows})
    if not res:
        res, hidden = match(r["grp"], r["lat"], r["lng"], 80, skip={d["id"] for d in rows})
    msg = (f"URGENT: {r['units']} unit(s) of {r['grp']} blood needed for {r['patient']}" +
           (f" at {r['hospital']}" if r["hospital"] else "") +
           f". Location: https://maps.google.com/?q={r['lat']},{r['lng']} Contact: {r['contact']}. Can you help? - Donor++")
    for x in res:
        x["wa"] = f"https://wa.me/91{x.pop('_p')}?text={quote(msg)}"
    return jsonify(request=dict(id=r["id"], grp=r["grp"], units=r["units"], urgency=r["urgency"], patient=r["patient"],
                                hospital=r["hospital"], status=r["status"]), responders=resp, matches=res[:15], hidden=hidden)


@app.post("/api/request/<int:rid>/close")
def close_request(rid):
    r = owned(rid)
    status = body().get("status")
    if not r or status not in ("fulfilled", "cancelled"):
        return jsonify(error="Request not found"), 404
    db().execute("UPDATE requests SET status=? WHERE id=?", (status, rid))
    db().commit()
    publish("request_update", {"id": rid})
    return jsonify(ok=True)


@app.post("/api/respond")
def respond():
    u = user()
    if not u or u["kind"] != "donor":
        return jsonify(error="Log in as a donor to respond"), 401
    r = db().execute("SELECT * FROM requests WHERE id=? AND status='open'", (int(num(body().get("id"), 1, 10 ** 9, 0)),)).fetchone()
    if not r:
        return jsonify(error="This request is already closed"), 404
    if u["grp"] not in CAN_GIVE[r["grp"]]:
        return jsonify(error=f"Your blood group ({u['grp']}) cannot donate to {r['grp']}"), 400
    w = wait(u["last_donation"], u["sex"])
    if w:
        return jsonify(error=f"You are in the recovery period for {w} more days. Thank you for donating recently!"), 400
    db().execute("INSERT OR IGNORE INTO responses(request_id,donor_id,created) VALUES(?,?,?)",
                 (r["id"], u["id"], datetime.now(timezone.utc).isoformat()))
    db().commit()
    publish("request_update", {"id": r["id"]})
    msg = f"Hi, I am {u['name']} ({u['grp']}). I saw your blood request for {r['patient']} on Donor++ and I can donate. Where and when?"
    return jsonify(wa=f"https://wa.me/91{DEMO if (r['demo'] and DEMO) else r['contact']}?text={quote(msg)}")


init()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), threaded=True)
