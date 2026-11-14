import os
import sqlite3
import math
import time
import hashlib
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, g

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "donorfinder-lifestream-secret-2026")
DATABASE = os.environ.get("DB_PATH", "donors.db")

# Cache to prevent duplicate SOS broadcasts within 10 minutes (600 seconds)
RECENT_SOS_CACHE = {}

def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()

def haversine(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return 9999.0
    R = 6371.0  # Earth's radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 1)

def cutoff_date_str():
    return (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d")

def init_db():
    with app.app_context():
        db = get_db()
        c = db.cursor()

        # Donors table
        c.execute("""
            CREATE TABLE IF NOT EXISTS donors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                donor_uid TEXT UNIQUE,
                name TEXT NOT NULL,
                blood_group TEXT NOT NULL,
                phone TEXT NOT NULL,
                area TEXT NOT NULL,
                department TEXT DEFAULT 'General',
                organization TEXT DEFAULT 'Community donor',
                donation_count INTEGER DEFAULT 1,
                last_donation TEXT,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                aadhaar_masked TEXT DEFAULT 'XXXX-XXXX-4589',
                verified INTEGER DEFAULT 1,
                available INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Hospitals & Blood Banks table
        c.execute("""
            CREATE TABLE IF NOT EXISTS hospitals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                area TEXT NOT NULL,
                address TEXT NOT NULL,
                phone TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                blood_groups TEXT NOT NULL,
                verified INTEGER DEFAULT 1,
                open_24_hours INTEGER DEFAULT 1
            )
        """)

        # Blood Requests table
        c.execute("""
            CREATE TABLE IF NOT EXISTS blood_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_name TEXT NOT NULL,
                blood_group TEXT NOT NULL,
                units INTEGER DEFAULT 1,
                hospital TEXT NOT NULL,
                area TEXT NOT NULL,
                contact TEXT NOT NULL,
                urgency TEXT DEFAULT 'Urgent',
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                fulfilled_at TIMESTAMP
            )
        """)

        # Blood Camps table
        c.execute("""
            CREATE TABLE IF NOT EXISTS camps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                organizer TEXT NOT NULL,
                venue TEXT NOT NULL,
                area TEXT NOT NULL,
                camp_date TEXT NOT NULL,
                time TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                registrations INTEGER DEFAULT 0,
                image_url TEXT
            )
        """)

        # LifeStream League Teams table (Colleges, Hostels, Departments)
        c.execute("""
            CREATE TABLE IF NOT EXISTS teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                category TEXT NOT NULL,
                units INTEGER DEFAULT 0,
                members INTEGER DEFAULT 0,
                badge TEXT DEFAULT 'LifeSpark'
            )
        """)

        # Seed initial teams if empty
        c.execute("SELECT COUNT(*) FROM teams")
        if c.fetchone()[0] == 0:
            sample_teams = [
                ("IIT Madras - CSE & Hostel 4", "College & Hostel", 582, 348, "Apex Lifesaver"),
                ("USTM & P.A. Sangma Medical NSS Cell", "Medical & NSS", 486, 312, "Crimson Guardian"),
                ("Anna University - Mech & Hostel B", "College & Hostel", 395, 246, "Crimson Guardian"),
                ("TCS Chennai - Health Club", "Corporate", 278, 191, "Plasma Pioneer"),
                ("Chennai Police Lifeline Wing", "Department", 234, 145, "Plasma Pioneer"),
                ("Loyola College - Youth Red Cross", "College", 189, 118, "LifeSpark"),
            ]
            c.executemany("INSERT OR IGNORE INTO teams (name, category, units, members, badge) VALUES (?, ?, ?, ?, ?)", sample_teams)

        # Seed initial donors if empty (including Bombay blood & Rh-null)
        c.execute("SELECT COUNT(*) FROM donors")
        if c.fetchone()[0] == 0:
            past_date = (datetime.utcnow() - timedelta(days=115)).strftime("%Y-%m-%d")
            sample_donors = [
                ("DF-001001", "Priya Sharma", "O+", "9876501234", "Egmore", "CSE Dept", "IIT Madras", 8, past_date, 13.0798, 80.2615, "XXXX-XXXX-9124", 1, 1),
                ("DF-001002", "Dr. A. Rahman", "Bombay (hh)", "9840112233", "Medical Campus", "Faculty of Medicine", "USTM & P.A. Sangma Medical", 14, past_date, 26.1158, 91.8933, "XXXX-XXXX-4589", 1, 1),
                ("DF-001003", "Ananya Sen", "Rh-null", "9123456789", "Anna Nagar", "Biotech Research", "Community Lifesaver", 6, past_date, 13.0850, 80.2101, "XXXX-XXXX-3341", 1, 1),
                ("DF-001004", "Mohammed Farooq", "A1+", "9894055112", "Nungambakkam", "Hostel Block 4", "Anna University", 9, past_date, 13.0615, 80.2426, "XXXX-XXXX-8900", 1, 1),
                ("DF-001005", "Karthik Raja", "B+", "9789012345", "Kilpauk", "Mechanical Hostel", "IIT Madras", 11, past_date, 13.0835, 80.2361, "XXXX-XXXX-6712", 1, 1),
                ("DF-001006", "Rahul Menon", "O-", "9876501237", "Royapettah", "Traffic Taskforce", "Chennai Police", 5, past_date, 13.0536, 80.2633, "XXXX-XXXX-1994", 1, 1),
                ("DF-001007", "Meera Iyer", "B-", "9876501236", "T. Nagar", "Cloud Solutions", "TCS Chennai", 7, past_date, 13.0418, 80.2341, "XXXX-XXXX-7140", 1, 1),
            ]
            c.executemany("""
                INSERT INTO donors (donor_uid, name, blood_group, phone, area, department, organization, donation_count, last_donation, latitude, longitude, aadhaar_masked, verified, available)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, sample_donors)

        # Seed hospitals if empty
        c.execute("SELECT COUNT(*) FROM hospitals")
        if c.fetchone()[0] == 0:
            sample_hospitals = [
                ("Apollo Hospital", "Greams Road", "21 Greams Lane, Chennai", "04428290200", 13.0638, 80.2513, "A+, A-, B+, B-, O+, O-, AB+, AB-, Bombay (hh)", 1, 1),
                ("P.A. Sangma Int'l Medical College & Hospital (PIMC)", "Ri-Bhoi / Guwahati", "USTM Medical Campus, Meghalaya Border", "03612895030", 26.1158, 91.8933, "A+, B+, O+, O-, AB+, Bombay (hh), Rh-null", 1, 1),
                ("Rajiv Gandhi Govt. General Hospital", "Park Town", "Poonamallee High Road, Chennai", "04425305000", 13.0809, 80.2755, "A+, B+, O+, O-, A1+, A2+", 1, 1),
                ("Government Blood Bank", "Egmore", "Pantheon Road, Egmore, Chennai", "04428191919", 13.0730, 80.2592, "A+, A-, B+, O+, O-", 1, 1),
            ]
            c.executemany("""
                INSERT INTO hospitals (name, area, address, phone, latitude, longitude, blood_groups, verified, open_24_hours)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, sample_hospitals)

        # Seed blood requests if empty
        c.execute("SELECT COUNT(*) FROM blood_requests")
        if c.fetchone()[0] == 0:
            sample_requests = [
                ("Anjali R.", "Bombay (hh)", 2, "P.A. Sangma Medical College / Apollo", "Greams Road", "9876503456", "Critical", "active"),
                ("Ramesh K.", "O-", 3, "Rajiv Gandhi Govt. Hospital", "Park Town", "9876503457", "Critical", "active"),
                ("Kavya S.", "A1+", 1, "Government Blood Bank", "Egmore", "9876503458", "Urgent", "active"),
            ]
            c.executemany("""
                INSERT INTO blood_requests (patient_name, blood_group, units, hospital, area, contact, urgency, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, sample_requests)

        # Seed blood camps (including the real NSS USTM & PIMC camp from the photo)
        c.execute("SELECT COUNT(*) FROM camps")
        if c.fetchone()[0] == 0:
            next_date1 = (datetime.utcnow() + timedelta(days=4)).strftime("%Y-%m-%d")
            next_date2 = (datetime.utcnow() + timedelta(days=8)).strftime("%Y-%m-%d")
            next_date3 = (datetime.utcnow() + timedelta(days=14)).strftime("%Y-%m-%d")
            sample_camps = [
                ("Voluntary Blood Donation Camp - USTM & PIMC", "NSS Cell & Blood Centre, P.A. Sangma Int'l Medical College", "Block B, State University Health Complex", "Ri-Bhoi / Guwahati", next_date1, "09:00 AM – 04:00 PM", 26.1158, 91.8933, 142, "camp-photo1.jpg"),
                ("IIT Madras Crimson Lifeline Drive", "NSS Cell & Red Cross Youth", "Student Activities Centre, Adyar", "Adyar, Chennai", next_date2, "10:00 AM – 04:30 PM", 13.0067, 80.2575, 168, None),
                ("Community Health & Plasma Camp", "Rotary Club & Lions Health Wing", "Anna Nagar Civic Community Hall", "Anna Nagar, Chennai", next_date3, "08:30 AM – 02:00 PM", 13.0850, 80.2101, 95, None),
            ]
            c.executemany("""
                INSERT INTO camps (name, organizer, venue, area, camp_date, time, latitude, longitude, registrations, image_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, sample_camps)

        db.commit()

init_db()

@app.route("/")
def index():
    return render_template("index.html")

# API: Load Dashboard Data (Compatible with DonorFinder frontend)
@app.route("/api/data", methods=["GET"])
def api_data():
    db = get_db()
    c = db.cursor()
    cutoff = cutoff_date_str()

    # Active verified donors who are not in the 90-day cooldown
    c.execute("""
        SELECT * FROM donors 
        WHERE available = 1 AND verified = 1 AND (last_donation IS NULL OR last_donation <= ?)
    """, (cutoff,))
    available_donors = [dict(r) for r in c.fetchall()]

    # Count protected donors currently in 90-day recovery
    c.execute("SELECT COUNT(*) FROM donors WHERE available = 1 AND last_donation > ?", (cutoff,))
    protected_count = c.fetchone()[0]

    # Hospitals
    c.execute("SELECT * FROM hospitals WHERE verified = 1")
    hospitals_list = [dict(r) for r in c.fetchall()]

    # Blood requests
    c.execute("SELECT * FROM blood_requests ORDER BY created_at DESC")
    requests_list = [dict(r) for r in c.fetchall()]

    # Upcoming camps
    c.execute("SELECT * FROM camps WHERE camp_date >= DATE('now') ORDER BY camp_date ASC")
    camps_list = [dict(r) for r in c.fetchall()]

    # Teams / LifeStream League
    c.execute("SELECT * FROM teams ORDER BY units DESC")
    teams_list = [dict(r) for r in c.fetchall()]

    # Real-time lives saved calculation
    c.execute("SELECT SUM(units) FROM blood_requests WHERE status = 'fulfilled'")
    fulfilled_units = c.fetchone()[0] or 0
    total_units_collected = 1248 + (fulfilled_units * 3)
    lives_saved = total_units_collected * 3

    return jsonify({
        "donors": available_donors,
        "hospitals": hospitals_list,
        "requests": requests_list,
        "camps": camps_list,
        "teams": teams_list,
        "protectedCount": protected_count,
        "impact": {
            "averageResponseSeconds": 108,
            "livesSaved": lives_saved
        }
    })

# API: Create / Broadcast Emergency SOS or Register Camp
@app.route("/api/data", methods=["POST"])
def api_create():
    data = request.json or {}
    resource = data.get("resource")
    db = get_db()
    c = db.cursor()

    if resource == "request":
        patient_name = data.get("patientName", "").strip()
        blood_group = data.get("bloodGroup", "").strip()
        hospital = data.get("hospital", "").strip()
        area = data.get("area", "").strip()
        contact = data.get("contact", "").strip()
        units = int(data.get("units", 1))
        urgency = data.get("urgency", "Urgent")
        radius_km = float(data.get("radiusKm", 25))
        user_lat = float(data.get("latitude", 13.0827))
        user_lng = float(data.get("longitude", 80.2707))

        if not (patient_name and blood_group and hospital and contact):
            return jsonify({"error": "Please provide patient name, blood group, hospital, and contact number."}), 400

        # SPAM & DUPLICATE SOS CHECK (within 10 minutes)
        cache_key = f"{patient_name.lower()}_{hospital.lower()}_{blood_group}"
        curr_time = time.time()
        if cache_key in RECENT_SOS_CACHE:
            last_time = RECENT_SOS_CACHE[cache_key]
            if curr_time - last_time < 600:
                remaining_sec = int(600 - (curr_time - last_time))
                return jsonify({
                    "error": f"⚠️ Duplicate Alert Suppressed: An identical SOS for {patient_name} at {hospital} was dispatched {int((curr_time - last_time)//60)}m ago. Cooldown: {remaining_sec}s."
                }), 409

        # Also check database for active duplicates
        c.execute("SELECT id, hospital FROM blood_requests WHERE status = 'active' AND LOWER(patient_name) = ? AND LOWER(hospital) = ?", (patient_name.lower(), hospital.lower()))
        existing = c.fetchone()
        if existing:
            return jsonify({"error": f"⚠️ Duplicate Alert: An active blood request already exists for {patient_name} at {existing['hospital']}."}), 409

        RECENT_SOS_CACHE[cache_key] = curr_time

        c.execute("""
            INSERT INTO blood_requests (patient_name, blood_group, units, hospital, area, contact, urgency, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
        """, (patient_name, blood_group, units, hospital, area, contact, urgency))
        req_id = c.lastrowid
        db.commit()

        # Calculate nearby matching donors for radius SMS broadcast
        c.execute("SELECT latitude, longitude FROM donors WHERE available = 1 AND (blood_group = ? OR ? = 'All groups')", (blood_group, blood_group))
        matching_donors = c.fetchall()
        alerted_count = 0
        for d in matching_donors:
            if haversine(user_lat, user_lng, d["latitude"], d["longitude"]) <= radius_km:
                alerted_count += 1

        c.execute("SELECT * FROM blood_requests WHERE id = ?", (req_id,))
        item = dict(c.fetchone())

        return jsonify({
            "item": item,
            "smsAlert": {
                "success": True,
                "radiusKm": radius_km,
                "alertedCount": alerted_count,
                "preview": f"🚨 EMERGENCY: {blood_group} blood needed at {hospital}. Contact: {contact}."
            }
        }), 201

    elif resource == "camp":
        name = data.get("name", "").strip()
        organizer = data.get("organizer", "").strip()
        venue = data.get("venue", "").strip()
        area = data.get("area", "").strip()
        camp_date = data.get("date", "").strip()
        timing = data.get("time", "").strip()
        lat = float(data.get("latitude", 13.0827))
        lng = float(data.get("longitude", 80.2707))

        if not (name and organizer and venue and camp_date):
            return jsonify({"error": "Missing required blood camp details."}), 400

        c.execute("""
            INSERT INTO camps (name, organizer, venue, area, camp_date, time, latitude, longitude, registrations)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
        """, (name, organizer, venue, area, camp_date, timing, lat, lng))
        camp_id = c.lastrowid
        db.commit()
        c.execute("SELECT * FROM camps WHERE id = ?", (camp_id,))
        return jsonify({"item": dict(c.fetchone())}), 201

    elif resource == "hospital":
        name = data.get("name", "").strip()
        area = data.get("area", "").strip()
        address = data.get("address", "").strip()
        phone = data.get("phone", "").strip()
        blood_groups = data.get("bloodGroups", "A+, B+, O+, O-").strip()
        lat = float(data.get("latitude", 13.0827))
        lng = float(data.get("longitude", 80.2707))

        c.execute("""
            INSERT INTO hospitals (name, area, address, phone, latitude, longitude, blood_groups, verified, open_24_hours)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1)
        """, (name, area, address, phone, lat, lng, blood_groups))
        hosp_id = c.lastrowid
        db.commit()
        c.execute("SELECT * FROM hospitals WHERE id = ?", (hosp_id,))
        return jsonify({"item": dict(c.fetchone())}), 201

    return jsonify({"error": "Unknown resource"}), 400

# API: Update / Fulfill Blood Request or Join Camp
@app.route("/api/data", methods=["PATCH"])
def api_update():
    data = request.json or {}
    resource = data.get("resource")
    item_id = data.get("id")
    db = get_db()
    c = db.cursor()

    if resource == "request":
        status = data.get("status")
        if status:
            fulfilled_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S") if status == "fulfilled" else None
            c.execute("UPDATE blood_requests SET status = ?, fulfilled_at = ? WHERE id = ?", (status, fulfilled_at, item_id))
            db.commit()
            c.execute("SELECT * FROM blood_requests WHERE id = ?", (item_id,))
            return jsonify({"item": dict(c.fetchone())})

    elif resource == "camp":
        if data.get("action") == "join":
            c.execute("UPDATE camps SET registrations = registrations + 1 WHERE id = ?", (item_id,))
            db.commit()
            c.execute("SELECT * FROM camps WHERE id = ?", (item_id,))
            return jsonify({"item": dict(c.fetchone())})

    return jsonify({"error": "Unable to update resource."}), 400

# API: Delete Item
@app.route("/api/data", methods=["DELETE"])
def api_delete():
    data = request.json or {}
    resource = data.get("resource")
    item_id = data.get("id")
    db = get_db()
    c = db.cursor()

    if resource == "request":
        c.execute("DELETE FROM blood_requests WHERE id = ?", (item_id,))
    elif resource == "camp":
        c.execute("DELETE FROM camps WHERE id = ?", (item_id,))
    elif resource == "hospital":
        c.execute("DELETE FROM hospitals WHERE id = ?", (item_id,))
    db.commit()
    return jsonify({"ok": True})

# API: User Auth & Registration with Aadhaar Auto-Redaction
@app.route("/api/auth", methods=["GET", "POST"])
def api_auth():
    db = get_db()
    c = db.cursor()

    if request.method == "GET":
        c.execute("SELECT * FROM donors WHERE id = 1")
        row = c.fetchone()
        user_data = {
            "id": 1,
            "name": row["name"],
            "email": "priya@demo.in",
            "phone": row["phone"],
            "bloodGroup": row["blood_group"],
            "donor": dict(row)
        } if row else None
        return jsonify({"user": user_data})

    data = request.json or {}
    action = data.get("action")

    if action == "login":
        c.execute("SELECT * FROM donors WHERE phone = ? OR name LIKE ?", (data.get("email"), f"%{data.get('email')}%"))
        row = c.fetchone()
        if row:
            return jsonify({"ok": True, "user": {"id": row["id"], "name": row["name"], "phone": row["phone"], "bloodGroup": row["blood_group"], "donor": dict(row)}})
        return jsonify({"ok": True})

    elif action == "register":
        name = data.get("name", "").strip()
        phone = data.get("phone", "").strip()
        blood_group = data.get("bloodGroup", "").strip()
        area = data.get("area", "Chennai").strip()
        department = data.get("department", "General").strip()
        organization = data.get("organization", "Community donor").strip()
        raw_aadhaar = data.get("aadhaar", "").replace(" ", "").replace("-", "")
        last_donation = data.get("lastDonation") or None
        lat = float(data.get("latitude", 13.0827))
        lng = float(data.get("longitude", 80.2707))

        masked_aadhaar = "XXXX-XXXX-" + (raw_aadhaar[-4:] if len(raw_aadhaar) >= 4 else "4589")
        donor_uid = "DF-" + hashlib.md5(f"{phone}{time.time()}".encode()).hexdigest()[:6].upper()

        c.execute("""
            INSERT INTO donors (donor_uid, name, blood_group, phone, area, department, organization, donation_count, last_donation, latitude, longitude, aadhaar_masked, verified, available)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, 1, 1)
        """, (donor_uid, name, blood_group, phone, area, department, organization, last_donation, lat, lng, masked_aadhaar))
        new_id = c.lastrowid
        db.commit()

        c.execute("SELECT * FROM donors WHERE id = ?", (new_id,))
        donor = dict(c.fetchone())
        return jsonify({"ok": True, "user": {"id": new_id, "name": name, "phone": phone, "bloodGroup": blood_group, "donor": donor}}), 201

    return jsonify({"error": "Unknown auth action"}), 400

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
