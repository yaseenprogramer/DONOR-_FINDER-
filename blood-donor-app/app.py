import os
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
  conn.execute("""
        CREATE TABLE IF NOT EXISTS donors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            blood TEXT NOT NULL,
            location TEXT NOT NULL,
            phone TEXT NOT NULL,
            lat REAL,
            lng REAL,
            last_donation TEXT
        )
    """)
  conn.commit()
  conn.close()


@app.route("/")
def index():
  return render_template("index.html")


@app.route("/api/search", methods=["GET"])
def search_donors():
  blood = request.args.get("blood", "").strip()
  location = request.args.get("location", "").strip()

  conn = get_db_connection()
  query = "SELECT * FROM donors WHERE 1=1"
  params = []

  if blood and blood != "All":
    query += " AND blood = ?"
    params.append(blood)

  if location:
    query += " AND location LIKE ?"
    params.append(f"%{location}%")

  donors = conn.execute(query, params).fetchall()
  conn.close()

  return jsonify([dict(row) for row in donors])


@app.route("/api/register", methods=["POST"])
def register_donor():
  data = request.json
  name = data.get("name")
  blood = data.get("blood")
  location = data.get("location")
  phone = data.get("phone")
  lat = data.get("lat")
  lng = data.get("lng")
  last_donation = data.get("last_donation", "Recently")

  if not all([name, blood, location, phone]):
    return jsonify({"error": "Missing required fields"}), 400

  conn = get_db_connection()
  conn.execute(
      """
        INSERT INTO donors (name, blood, location, phone, lat, lng, last_donation)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
      (name, blood, location, phone, lat, lng, last_donation),
  )
  conn.commit()
  conn.close()

  return jsonify({"success": True, "message": "Donor registered successfully!"})


if __name__ == "__main__":
  init_db()
  app.run(host="0.0.0.0", port=5000, debug=True)
