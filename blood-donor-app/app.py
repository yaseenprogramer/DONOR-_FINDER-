from flask import Flask, render_template, request, redirect, url_for, jsonify
import sqlite3
import os

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "donors.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Enterprise-grade database initialization with auto-repair & coordinates."""
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS donors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                blood_group TEXT NOT NULL,
                location TEXT NOT NULL,
                phone TEXT NOT NULL,
                last_donation TEXT DEFAULT 'Ready to Donate',
                lat REAL DEFAULT 13.1143,
                lng REAL DEFAULT 80.1113
            )
        """)
        cursor = conn.execute("PRAGMA table_info(donors)")
        columns = [c[1] for c in cursor.fetchall()]
        if 'lat' not in columns:
            conn.execute("ALTER TABLE donors ADD COLUMN lat REAL DEFAULT 13.1143")
        if 'lng' not in columns:
            conn.execute("ALTER TABLE donors ADD COLUMN lng REAL DEFAULT 80.1113")
        conn.commit()

init_db()

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/register', methods=['POST'])
def register():
    name = request.form.get('name', '').strip().title()
    blood = request.form.get('blood', '').upper()
    location = request.form.get('location', '').strip().capitalize()
    phone = "".join(filter(str.isdigit, request.form.get('phone', '')))
    last_d = request.form.get('last_donation', '').strip() or "Ready to Donate"
    
    lat = 13.0827 + (hash(location) % 20) * 0.01
    lng = 80.2707 + (hash(name) % 20) * 0.01

    if name and blood and location and phone:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO donors (name, blood_group, location, phone, last_donation, lat, lng) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name, blood, location, phone, last_d, lat, lng)
            )
            conn.commit()
        return redirect(url_for('home', registered='success'))
    
    return "Invalid submission parameters", 400

@app.route('/api/search')
def api_search():
    blood = request.args.get('blood', '').upper()
    location = request.args.get('location', '').strip().capitalize()
    
    query = "SELECT * FROM donors WHERE blood_group = ?"
    params = [blood]
    
    if location:
        query += " AND location LIKE ?"
        params.append(f"%{location}%")
        
    with get_db() as conn:
        donors = conn.execute(query + " ORDER BY id DESC", params).fetchall()
        return jsonify([dict(row) for row in donors])

if __name__ == '__main__':
    app.run(debug=True, port=5000)