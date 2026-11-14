from datetime import datetime, timedelta
import os
import sqlite3
from flask import Flask, jsonify, render_template, request
from werkzeug.utils import secure_filename

app = Flask(__name__)
DB_PATH = "donors.db"
UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


def get_db_connection():
  conn = sqlite3.connect(DB_PATH)
  conn.row_factory = sqlite3.Row
  return conn


def init_db():
  conn = get_db_connection()
  conn.executescript("""
        DROP TABLE IF EXISTS donors;
        DROP TABLE IF EXISTS camps;
        DROP TABLE IF EXISTS emergency_requests;
        DROP TABLE IF EXISTS inventory;
        DROP TABLE IF EXISTS metrics;

        CREATE TABLE donors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            role TEXT NOT NULL,
            blood TEXT NOT NULL,
            location TEXT NOT NULL,
            phone TEXT NOT NULL,
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            last_donation TEXT NOT NULL,
            verified INTEGER DEFAULT 1,
            doc_filename TEXT DEFAULT 'verified_pass.png'
        );

        CREATE TABLE camps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            organizer TEXT NOT NULL,
            location TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            lat REAL NOT NULL,
            lng REAL NOT NULL
        );

        CREATE TABLE emergency_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_name TEXT NOT NULL,
            blood TEXT NOT NULL,
            hospital TEXT NOT NULL,
            phone TEXT NOT NULL,
            units INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            status TEXT DEFAULT 'Active'
        );

        CREATE TABLE inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bank_name TEXT NOT NULL,
            component TEXT NOT NULL,
            blood TEXT NOT NULL,
            units INTEGER NOT NULL,
            expiry_date TEXT NOT NULL
        );

        CREATE TABLE metrics (
            id INTEGER PRIMARY KEY,
            successful_transplants INTEGER DEFAULT 1428
        );
    """)

  # Seed Donors & Hospitals
  conn.executemany(
      """
        INSERT INTO donors (name, role, blood, location, phone, lat, lng, last_donation, verified)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
      [
          (
              "Apollo Specialty Hospital",
              "Blood Bank",
              "All",
              "Greams Road, Chennai",
              "9876543210",
              13.0632,
              80.2518,
              "2026-01-01",
              1,
          ),
          (
              "Arun Kumar",
              "Donor",
              "O-",
              "Anna Nagar, Chennai",
              "9123456789",
              13.0850,
              80.2101,
              "2026-05-10",
              1,
          ),
          (
              "Tamil Nadu Govt Blood Bank",
              "Blood Bank",
              "All",
              "Egmore, Chennai",
              "9988776655",
              13.0732,
              80.2609,
              "2026-01-01",
              1,
          ),
          (
              "Priya Ramesh",
              "Donor",
              "B+",
              "Velachery, Chennai",
              "9711223344",
              12.9815,
              80.2180,
              "2026-10-15",
              1,
          ),
          (
              "Karthik Subramanian",
              "Donor",
              "A+",
              "Pattabiram, Chennai",
              "9840112233",
              13.1189,
              80.0628,
              "2026-04-01",
              1,
          ),
      ],
  )

  # Seed Blood Camps
  conn.executemany(
      """
        INSERT INTO camps (title, organizer, location, date, time, lat, lng)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
      [
          (
              "Mega Youth Blood Drive 2026",
              "Immanuel MHSS & Red Cross",
              "Pattabiram, Chennai",
              "2026-11-20",
              "09:00 AM - 04:00 PM",
              13.1195,
              80.0640,
          ),
          (
              "Chennai Central Life-Savers Camp",
              "Rotary Club of Madras",
              "T. Nagar, Chennai",
              "2026-11-22",
              "10:00 AM - 05:00 PM",
              13.0418,
              80.2341,
          ),
          (
              "IT Corridor Emergency Drive",
              "Lions Blood Foundation",
              "OMR Sholinganallur, Chennai",
              "2026-11-25",
              "09:30 AM - 03:30 PM",
              12.9010,
              80.2279,
          ),
      ],
  )

  # Seed Blood Component Inventory with Expiry Dates
  today = datetime.today()
  conn.executemany(
      """
        INSERT INTO inventory (bank_name, component, blood, units, expiry_date)
        VALUES (?, ?, ?, ?, ?)
    """,
      [
          (
              "Apollo Specialty Hospital",
              "Platelets (RDP)",
              "O+",
              12,
              (today + timedelta(days=2)).strftime("%Y-%m-%d"),
          ),
          (
              "Apollo Specialty Hospital",
              "Packed Red Cells (PRBC)",
              "A-",
              8,
              (today + timedelta(days=28)).strftime("%Y-%m-%d"),
          ),
          (
              "Tamil Nadu Govt Blood Bank",
              "Fresh Frozen Plasma (FFP)",
              "AB+",
              25,
              (today + timedelta(days=180)).strftime("%Y-%m-%d"),
          ),
          (
              "Tamil Nadu Govt Blood Bank",
              "Platelets (SDP)",
              "B-",
              4,
              (today + timedelta(days=1)).strftime("%Y-%m-%d"),
          ),
      ],
  )

  # Seed Initial Transplant Counter
  conn.execute("INSERT INTO metrics (id, successful_transplants) VALUES (1, 1428)")
  conn.commit()
  conn.close()


init_db()


@app.route("/")
def index():
  return render_template("index.html")


@app.route("/api/dashboard", methods=["GET"])
def dashboard_data():
  conn = get_db_connection()
  donors = conn.execute(
      "SELECT COUNT(*) FROM donors WHERE role='Donor'"
  ).fetchone()[0]
  banks = conn.execute(
      "SELECT COUNT(*) FROM donors WHERE role='Blood Bank'"
  ).fetchone()[0]
  transplants = conn.execute(
      "SELECT successful_transplants FROM metrics WHERE id=1"
  ).fetchone()[0]
  reqs = conn.execute(
      "SELECT * FROM emergency_requests ORDER BY id DESC"
  ).fetchall()
  camps = conn.execute("SELECT * FROM camps").fetchall()
  inv = conn.execute("SELECT * FROM inventory ORDER BY expiry_date ASC").fetchall()
  conn.close()

  today = datetime.today()
  inv_list = []
  for item in inv:
    d = dict(item)
    exp = datetime.strptime(d["expiry_date"], "%Y-%m-%d")
    days_left = (exp - today).days
    d["days_left"] = max(0, days_left)
    d["urgent_expiry"] = days_left <= 3
    inv_list.append(d)

  return jsonify(
      {
          "stats": {
              "donors": donors,
              "banks": banks,
              "transplants": transplants,
          },
          "requests": [dict(r) for r in reqs],
          "camps": [dict(c) for c in camps],
          "inventory": inv_list,
      }
  )


@app.route("/api/transplant/increment", methods=["POST"])
def increment_transplant():
  conn = get_db_connection()
  conn.execute(
      "UPDATE metrics SET successful_transplants = successful_transplants + 1 WHERE id=1"
  )
  new_val = conn.execute(
      "SELECT successful_transplants FROM metrics WHERE id=1"
  ).fetchone()[0]
  conn.commit()
  conn.close()
  return jsonify({"success": True, "transplants": new_val})


@app.route("/api/search", methods=["GET"])
def search_donors():
  blood = request.args.get("blood", "").strip()
  location = request.args.get("location", "").strip()
  role = request.args.get("role", "").strip()

  conn = get_db_connection()
  query = "SELECT * FROM donors WHERE 1=1"
  params = []

  if blood and blood != "All":
    query += " AND (blood = ? OR blood = 'All')"
    params.append(blood)
  if location:
    query += " AND location LIKE ?"
    params.append(f"%{location}%")
  if role and role != "All":
    query += " AND role = ?"
    params.append(role)

  donors = conn.execute(query, params).fetchall()
  conn.close()

  today = datetime.today()
  results = []
  for row in donors:
    d = dict(row)
    try:
      last_date = datetime.strptime(d["last_donation"], "%Y-%m-%d")
      days_passed = (today - last_date).days
      d["eligible"] = days_passed >= 90 or d["role"] == "Blood Bank"
      d["days_remaining"] = (
          0 if d["role"] == "Blood Bank" else max(0, 90 - days_passed)
      )
    except Exception:
      d["eligible"] = True
      d["days_remaining"] = 0
    results.append(d)

  return jsonify(results)


@app.route("/api/register", methods=["POST"])
def register_donor():
  name = request.form.get("name")
  role = request.form.get("role", "Donor")
  blood = request.form.get("blood")
  location = request.form.get("location")
  phone = request.form.get("phone")
  lat = float(request.form.get("lat", 13.0827))
  lng = float(request.form.get("lng", 80.2707))
  last_donation = request.form.get(
      "last_donation", datetime.today().strftime("%Y-%m-%d")
  )

  if not all([name, blood, location, phone]):
    return jsonify({"error": "All fields are required"}), 400

  # Handle ID Photo Upload (Simulated verification with redacted privacy)
  doc_file = request.files.get("id_photo")
  filename = "verified_id_redacted.png"
  if doc_file and doc_file.filename:
    safe_name = secure_filename(doc_file.filename)
    filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{safe_name}"
    doc_file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

  conn = get_db_connection()
  conn.execute(
      """
        INSERT INTO donors (name, role, blood, location, phone, lat, lng, last_donation, verified, doc_filename)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
    """,
      (name, role, blood, location, phone, lat, lng, last_donation, filename),
  )
  conn.commit()
  conn.close()

  return jsonify({"success": True, "verified": True})


@app.route("/api/emergency", methods=["POST"])
def create_emergency():
  data = request.json
  patient = data.get("patient_name", "").strip()
  blood = data.get("blood", "").strip()
  hospital = data.get("hospital", "").strip()
  phone = data.get("phone", "").strip()
  units = int(data.get("units", 1))
  force = data.get("force", False)

  if not all([patient, blood, hospital, phone]):
    return jsonify({"error": "Please fill all emergency details"}), 400

  conn = get_db_connection()

  # 9. Duplicate Request Alert Check (Same phone/patient + blood group + hospital)
  if not force:
    dup = conn.execute(
        """
            SELECT * FROM emergency_requests 
            WHERE (phone = ? OR LOWER(patient_name) = LOWER(?)) 
            AND blood = ? AND LOWER(hospital) = LOWER(?) AND status = 'Active'
        """,
        (phone, patient, blood, hospital),
    ).fetchone()

    if dup:
      conn.close()
      return (
          jsonify(
              {
                  "duplicate": True,
                  "message": (
                      f"Duplicate Alert: An active SOS for {blood} at"
                      f" {hospital} already exists for this contact!"
                  ),
              }
          ),
          409,
      )

  now_str = datetime.now().strftime("%d %b %Y, %I:%M %p")
  conn.execute(
      """
        INSERT INTO emergency_requests (patient_name, blood, hospital, phone, units, created_at, status)
        VALUES (?, ?, ?, ?, ?, ?, 'Active')
    """,
      (patient, blood, hospital, phone, units, now_str),
  )
  conn.commit()
  conn.close()

  return jsonify({"success": True})


@app.route("/api/inventory", methods=["POST"])
def add_inventory():
  data = request.json
  bank = data.get("bank_name")
  component = data.get("component")
  blood = data.get("blood")
  units = int(data.get("units", 1))
  expiry = data.get("expiry_date")

  if not all([bank, component, blood, expiry]):
    return jsonify({"error": "Missing component details"}), 400

  conn = get_db_connection()
  conn.execute(
      """
        INSERT INTO inventory (bank_name, component, blood, units, expiry_date)
        VALUES (?, ?, ?, ?, ?)
    """,
      (bank, component, blood, units, expiry),
  )
  conn.commit()
  conn.close()
  return jsonify({"success": True})


if __name__ == "__main__":
  app.run(host="0.0.0.0", port=5000, debug=True)
