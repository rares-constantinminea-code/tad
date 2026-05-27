import os
import random
import requests
import pymysql
import pymysql.cursors

from flask import Flask, jsonify, request, render_template, Response

app = Flask(__name__)

# ═══════════════════════ ENV VARIABLES ═══════════════════════

OPENWEATHER_KEY = os.environ.get("OPENWEATHER_KEY")
WAQI_TOKEN = os.environ.get("WAQI_TOKEN")

# ═══════════════════════ ORASE ═══════════════════════

ROMANIA_CITIES = [
    ("Bucuresti", 44.43, 26.10),
    ("Cluj-Napoca", 46.77, 23.59),
    ("Iasi", 47.16, 27.58),
    ("Brasov", 45.65, 25.61),
    ("Constanta", 44.18, 28.64),
    ("Timisoara", 45.75, 21.23),
    ("Sibiu", 45.79, 24.15),
    ("Oradea", 47.05, 21.93),
]

CITY_NAMES = [c[0] for c in ROMANIA_CITIES]

# ═══════════════════════ MYSQL ═══════════════════════

def get_conn():
    return pymysql.connect(
        host=os.environ.get("MYSQLHOST"),
        port=int(os.environ.get("MYSQLPORT", 3306)),
        user=os.environ.get("MYSQLUSER"),
        password=os.environ.get("MYSQLPASSWORD"),
        database=os.environ.get("MYSQLDATABASE"),
        cursorclass=pymysql.cursors.DictCursor,
        charset="utf8mb4",
        autocommit=True
    )

def init_db():
    try:
        conn = get_conn()

        with conn.cursor() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS measurements (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    oras VARCHAR(100),
                    temperatura FLOAT,
                    pm25 FLOAT,
                    descriere TEXT,
                    nivel_aer VARCHAR(50),
                    source VARCHAR(50),
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

        conn.close()

    except Exception as e:
        print("DB ERROR:", e)

def db_exec(query, args=(), fetch=False):
    try:
        conn = get_conn()

        with conn.cursor() as c:
            c.execute(query, args)

            if fetch:
                result = c.fetchall()
            else:
                result = None

        conn.close()
        return result

    except Exception as e:
        print("DB QUERY ERROR:", e)
        return []

# ═══════════════════════ LOGICA ═══════════════════════

def nivel_calitate_aer(pm25):
    if pm25 is None:
        return "necunoscut"

    if pm25 <= 25:
        return "excelent"

    if pm25 <= 50:
        return "bun"

    if pm25 <= 75:
        return "moderat"

    if pm25 <= 100:
        return "slab"

    return "foarte slab"

# ═══════════════════════ API EXTERNE ═══════════════════════

def get_weather(city):
    url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={OPENWEATHER_KEY}&units=metric&lang=ro"

    r = requests.get(url, timeout=10)
    d = r.json()

    return {
        "temp": d["main"]["temp"],
        "humidity": d["main"]["humidity"],
        "wind": d["wind"]["speed"],
        "desc": d["weather"][0]["description"],
        "icon": d["weather"][0]["icon"],
        "lat": d["coord"]["lat"],
        "lon": d["coord"]["lon"]
    }

def get_pm25(city):
    url = f"https://api.waqi.info/feed/{city}/?token={WAQI_TOKEN}"

    r = requests.get(url, timeout=10)
    d = r.json()

    try:
        return d["data"]["iaqi"]["pm25"]["v"]
    except:
        return None

# ═══════════════════════ ROUTES ═══════════════════════

@app.route("/")
def home():
    return render_template("HTMLPage1.html")

@app.route("/api/meteo/live/<city>")
def api_live(city):
    try:
        w = get_weather(city)
        pm = get_pm25(city)

        nivel = nivel_calitate_aer(pm)

        try:
            db_exec("""
                INSERT INTO measurements
                (oras, temperatura, pm25, descriere, nivel_aer, source)
                VALUES (%s,%s,%s,%s,%s,%s)
            """, (
                city,
                w["temp"],
                pm,
                w["desc"],
                nivel,
                "live"
            ))
        except:
            pass

        return jsonify({
            "oras": city,
            "temperatura": w["temp"],
            "umiditate": w["humidity"],
            "vant": w["wind"],
            "pm25": pm,
            "descriere": w["desc"],
            "icon": w["icon"],
            "nivel_aer": nivel
        })

    except Exception as e:
        return jsonify({
            "eroare": str(e)
        }), 500

@app.route("/api/random-city")
def random_city():
    city = random.choice(CITY_NAMES)
    return api_live(city)

@app.route("/api/measurements")
def measurements():
    rows = db_exec(
        "SELECT * FROM measurements ORDER BY id DESC LIMIT 50",
        fetch=True
    )

    return jsonify(rows)

@app.route("/generate", methods=["POST"])
def generate():
    city, lat, lon = random.choice(ROMANIA_CITIES)

    temp = round(random.uniform(-5, 38), 1)
    pm = round(random.uniform(5, 160), 1)

    nivel = nivel_calitate_aer(pm)

    return jsonify({
        "city": city,
        "temp": temp,
        "pm": pm,
        "lat": lat,
        "lon": lon,
        "nivel_aer": nivel
    })

@app.route("/api/export/csv")
def export_csv():
    rows = db_exec(
        "SELECT * FROM measurements ORDER BY id DESC",
        fetch=True
    )

    csv_data = "id,oras,temperatura,pm25,nivel_aer,source,timestamp\n"

    for r in rows:
        csv_data += f'{r["id"]},{r["oras"]},{r["temperatura"]},{r["pm25"]},{r["nivel_aer"]},{r["source"]},{r["timestamp"]}\n'

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={
            "Content-Disposition":
            "attachment; filename=meteo_export.csv"
        }
    )

# ═══════════════════════ START ═══════════════════════

try:
    init_db()
except Exception as e:
    print("INIT DB FAILED:", e)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
