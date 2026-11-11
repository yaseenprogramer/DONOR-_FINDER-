from datetime import datetime
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
            status TEXT DEFAULT 'Available'
        )
    """)
  # Seed default verified locations
  conn.executemany(
      """
        INSERT INTO donors (name, role, blood, location, phone, lat, lng, last_donation, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
      [
          (
              "City General Hospital",
              "Blood Bank",
              "All",
              "Chennai Central",
              "9876543210",
              13.0827,
              80.2707,
              "2026-01-01",
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
              "Available",
          ),
      ],
  )
  conn.commit()
  conn.close()


init_db()


@app.route("/")
def index():
  return render_template("index.html")


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

  if not all([name, blood, location, phone]):
    return jsonify({"error": "Missing required fields"}), 400

  conn = get_db_connection()
  conn.execute(
      """
        INSERT INTO donors (name, role, blood, location, phone, lat, lng, last_donation, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Available')
    """,
      (name, role, blood, location, phone, lat, lng, last_donation),
  )
  conn.commit()
  conn.close()

  return jsonify({"success": True, "message": "Registered successfully!"})


if __name__ == "__main__":
  app.run(host="0.0.0.0", port=5000, debug=True)
