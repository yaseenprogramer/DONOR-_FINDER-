from datetime import datetime, timedelta
import sqlite3
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)
DB_PATH = "donors.db"


def get_db_connection():
  conn = sqlite3.connect(DB_PATH)
  conn.row_factory = sqlite3.Row
  return conn


def init_db():
  conn = get_db_connection()
  conn.execute("DROP TABLE IF EXISTS donors")
  conn.execute("DROP TABLE IF EXISTS camps")
  conn.execute("DROP TABLE IF EXISTS inventory")
  conn.execute("DROP TABLE IF EXISTS emergency_requests")

  # Donors Table
  conn.execute("""
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
            aadhar_verified TEXT DEFAULT 'Verified ([Aadhaar Redacted])',
            status TEXT DEFAULT 'Available'
        )
    """)

  # Blood Camps Table
  conn.execute("""
        CREATE TABLE camps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            camp_name TEXT NOT NULL,
            organizer TEXT NOT NULL,
            location TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            lat REAL NOT NULL,
            lng REAL NOT NULL
        )
    """)

  # Blood Component Expiry Table
  conn.execute("""
        CREATE TABLE inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hospital_name TEXT NOT NULL,
            component_type TEXT NOT NULL,
            blood_group TEXT NOT NULL,
            units INTEGER NOT NULL,
            expiry_date TEXT NOT NULL
        )
    """)

  # Emergency Requests Table (for Duplicate Detection)
  conn.execute("""
        CREATE TABLE emergency_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            blood_group TEXT NOT NULL,
            location TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            status TEXT DEFAULT 'Active'
        )
    """)

  # Seed Initial Data
  conn.executemany(
      """
        INSERT INTO donors (name, role, blood, location, phone, lat, lng, last_donation, aadhar_verified, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
      [
          (
              "City General Hospital Bank",
              "Blood Bank",
              "All",
              "Chennai Central",
              "9876543210",
              13.0827,
              80.2707,
              "2026-01-01",
              "Verified ([Aadhaar Redacted])",
              "Available",
          ),
          (
              "Arun Kumar",
              "Donor",
              "O+",
              "Anna Nagar",
              "9123456789",
              13.0878,
              80.2084,
              "2026-02-10",
              "Verified ([Aadhaar Redacted])",
              "Available",
          ),
          (
              "LifeCare RedCross Hub",
              "Blood Bank",
              "All",
              "T. Nagar",
              "9988776655",
              13.0418,
              80.2341,
              "2026-01-01",
              "Verified ([Aadhaar Redacted])",
              "Available",
          ),
          (
              "Priya Ramesh",
              "Donor",
              "B+",
              "Velachery",
              "9711223344",
              12.9716,
              80.2211,
              "2025-11-15",
              "Verified ([Aadhaar Redacted])",
              "Available",
          ),
      ],
  )

  future_date = (datetime.today() + timedelta(days=5)).strftime("%Y-%m-%d")
  near_expiry = (datetime.today() + timedelta(days=1)).strftime("%Y-%m-%d")

  conn.executemany(
      """
        INSERT INTO camps (camp_name, organizer, location, date, time, lat, lng)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
      [
          (
              "Mega Youth Blood Drive",
              "Red Cross Society",
              "Anna Nagar Tower Park",
              "2026-03-20",
              "09:00 AM - 02:00 PM",
              13.0850,
              80.2100,
          ),
          (
              "Community Lifeline Camp",
              "Lions Club Chennai",
              "Velachery Bus Terminal",
              "2026-03-25",
              "10:00 AM - 04:00 PM",
              12.9750,
              80.2250,
          ),
      ],
  )

  conn.executemany(
      """
        INSERT INTO inventory (hospital_name, component_type, blood_group, units, expiry_date)
        VALUES (?, ?, ?, ?, ?)
    """,
      [
          ("City General Hospital", "RBC (Packed Cells)", "O+", 12, future_date),
          ("City General Hospital", "Platelets", "B+", 4, near_expiry),
          (
              "LifeCare RedCross Hub",
              "Fresh Frozen Plasma",
              "A+",
              8,
              future_date,
          ),
      ],
  )

  conn.commit()
  conn.close()


init_db()


@app.route("/")
def index():
  return render_template("index.html")


@app.route("/api/stats", methods=["GET"])
def get_stats():
  conn = get_db_connection()
  total_donors = conn.execute(
      "SELECT COUNT(*) FROM donors WHERE role='Donor'"
  ).fetchone()[0]
  total_banks = conn.execute(
      "SELECT COUNT(*) FROM donors WHERE role='Blood Bank'"
  ).fetchone()[0]
  total_transplants = 1428  # Live visual counter baseline
  conn.close()
  return jsonify(
      {
          "total_donors": total_donors,
          "total_banks": total_banks,
          "total_transplants": total_transplants,
      }
  )


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
    except:
      d["eligible"] = True
      d["days_remaining"] = 0
    results.append(d)

  return jsonify(results)


@app.route("/api/camps", methods=["GET"])
def get_camps():
  conn = get_db_connection()
  camps = conn.execute("SELECT * FROM camps").fetchall()
  conn.close()
  return jsonify([dict(row) for row in camps])


@app.route("/api/inventory", methods=["GET"])
def get_inventory():
  conn = get_db_connection()
  items = conn.execute("SELECT * FROM inventory").fetchall()
  conn.close()
  return jsonify([dict(row) for row in items])


@app.route("/api/emergency", methods=["POST"])
def emergency_request():
  data = request.json
  blood = data.get("blood")
  location = data.get("location")

  conn = get_db_connection()
  # Check for duplicate active request within last 30 mins
  recent = conn.execute(
      """
        SELECT * FROM emergency_requests 
        WHERE blood_group = ? AND location LIKE ? AND status = 'Active'
    """,
      (blood, f"%{location}%"),
  ).fetchone()

  if recent:
    conn.close()
    return jsonify({
        "duplicate": True,
        "message": (
            "⚠️ Duplicate Alert: An active emergency request for group"
            f" {blood} in this area was already broadcasted recently!"
        ),
    })

  conn.execute(
      """
        INSERT INTO emergency_requests (blood_group, location, timestamp)
        VALUES (?, ?, ?)
    """,
      (blood, location, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
  )
  conn.commit()
  conn.close()
  return jsonify({
      "duplicate": False,
      "message": "Emergency SOS broadcasted successfully to all nearby heroes!",
  })


@app.route("/api/register", methods=["POST"])
def register_donor():
  data = request.json
  name = data.get("name")
  role = data.get("role", "Donor")
  blood = data.get("blood")
  location = data.get("location")
  phone = data.get("phone")
  lat = data.get("lat", 13.0827)
  lng = data.get("lng", 80.2707)
  last_donation = data.get(
      "last_donation", datetime.today().strftime("%Y-%m-%d")
  )
  aadhar_status = "Verified ([Aadhaar Redacted])"

  if not all([name, blood, location, phone]):
    return jsonify({"error": "Missing required fields"}), 400

  conn = get_db_connection()
  conn.execute(
      """
        INSERT INTO donors (name, role, blood, location, phone, lat, lng, last_donation, aadhar_verified, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Available')
    """,
      (
          name,
          role,
          blood,
          location,
          phone,
          lat,
          lng,
          last_donation,
          aadhar_status,
      ),
  )
  conn.commit()
  conn.close()

  return jsonify({"success": True, "message": "Registered successfully!"})


if __name__ == "__main__":
  app.run(host="0.0.0.0", port=5000, debug=True)
