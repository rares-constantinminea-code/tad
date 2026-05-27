import os
import random
import requests
import pymysql
import pymysql.cursors
from flask import Flask, jsonify, request, render_template, Response

app = Flask(__name__)

OPENWEATHER_KEY = os.environ.get("OPENWEATHER_KEY")
WAQI_TOKEN = os.environ.get("WAQI_TOKEN")

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


def get_conn():
    return pymysql.connect(
        host=os.environ.get("MYSQLHOST"),
        port=int(os.environ.get("MYSQLPORT", 3306)),
        user=os.environ.get("MYSQLUSER"),
        password=os.environ.get("MYSQLPASSWORD"),
        database=os.environ.get("MYSQLDATABASE"),
        cursorclass=pymysql.cursors.DictCursor,
        charset="utf8mb4",
        autocommit=True,
    )


def db_exec(query, args=(), fetchall=False, fetchone=False):
    conn = get_conn()
    try:
        with conn.cursor() as c:
            c.execute(query, args)
            if fetchall:
                return c.fetchall()
            if fetchone:
                return c.fetchone()
            return c.lastrowid
    finally:
        conn.close()


def init_db():
    conn = get_conn()
    try:
        with conn.cursor() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS measurements (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    oras VARCHAR(100),
                    temperatura FLOAT,
                    pm25 FLOAT,
                    lat FLOAT,
                    lon FLOAT,
                    descriere TEXT,
                    recomandare TEXT,
                    nivel_aer VARCHAR(50),
                    source VARCHAR(50),
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
    finally:
        conn.close()


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


def scor_gradinarit(temp, pm25, desc):
    score = 5
    desc = (desc or "").lower()

    if temp is not None:
        if 18 <= temp <= 25:
            score += 3
        elif 15 <= temp <= 28:
            score += 2
        elif 10 <= temp <= 32:
            score += 1
        elif temp < 5 or temp > 35:
            score -= 3

    if pm25 is not None:
        if pm25 <= 25:
            score += 2
        elif pm25 <= 50:
            score += 1
        elif pm25 > 100:
            score -= 2

    if any(w in desc for w in ["ploaie", "rain", "furtuna", "storm"]):
        score -= 2

    if any(w in desc for w in ["senin", "clear", "soare"]):
        score += 1

    return max(0, min(10, score))


def recomandare_detaliata(temp, pm25, desc):
    desc = (desc or "").lower()

    if pm25 is None:
        aer = "Date AQI indisponibile."
    elif pm25 > 100:
        aer = "Aer foarte poluat - evita activitatile afara."
    elif pm25 > 75:
        aer = "Aer poluat - limiteaza timpul afara."
    elif pm25 > 50:
        aer = "Aer moderat - atentie daca ai probleme respiratorii."
    else:
        aer = "Aer curat - conditii bune pentru exterior."

    if "ploaie" in desc or "rain" in desc:
        act = "Ploua - verifica scurgerile si evita lucrarile in gradina."
    elif temp is None:
        act = "Temperatura indisponibila."
    elif temp < 0:
        act = "Inghet - protejeaza plantele."
    elif temp < 15:
        act = "Racoare - potrivit pentru plante rezistente."
    elif temp < 30:
        act = "Conditii bune pentru gradinarit."
    else:
        act = "Caldura mare - uda plantele dimineata sau seara."

    return f"{aer} | {act}"


def get_weather(city):
    if not OPENWEATHER_KEY:
        raise Exception("OPENWEATHER_KEY lipseste din Railway Variables")

    url = (
        "https://api.openweathermap.org/data/2.5/weather"
        f"?q={city}&appid={OPENWEATHER_KEY}&units=metric&lang=ro"
    )

    r = requests.get(url, timeout=10)
    d = r.json()

    if "main" not in d:
        raise Exception(d.get("message", "Eroare OpenWeather"))

    return {
        "temp": d["main"]["temp"],
        "humidity": d["main"]["humidity"],
        "wind": d["wind"]["speed"],
        "desc": d["weather"][0]["description"],
        "icon": d["weather"][0]["icon"],
        "lat": d["coord"]["lat"],
        "lon": d["coord"]["lon"],
    }


def get_pm25(city):
    if not WAQI_TOKEN:
        return None

    try:
        url = f"https://api.waqi.info/feed/{city}/?token={WAQI_TOKEN}"
        r = requests.get(url, timeout=10)
        d = r.json()
        return d["data"]["iaqi"]["pm25"]["v"]
    except Exception:
        return None


def save_measurement(oras, temp, pm25, lat, lon, desc, source):
    nivel = nivel_calitate_aer(pm25)
    rec = recomandare_detaliata(temp, pm25, desc)

    db_exec("""
        INSERT INTO measurements
        (oras, temperatura, pm25, lat, lon, descriere, recomandare, nivel_aer, source)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (oras, temp, pm25, lat, lon, desc, rec, nivel, source))

    return nivel, rec


@app.route("/")
def home():
    return render_template("HTMLPage1.html")


@app.route("/api/meteo/live/<city>")
def api_live(city):
    try:
        w = get_weather(city)
        pm = get_pm25(city)
        nivel, rec = save_measurement(
            city,
            w["temp"],
            pm,
            w["lat"],
            w["lon"],
            w["desc"],
            "live",
        )

        return jsonify({
            "oras": city,
            "temperatura": w["temp"],
            "umiditate": w["humidity"],
            "vant": w["wind"],
            "pm25": pm,
            "lat": w["lat"],
            "lon": w["lon"],
            "descriere": w["desc"],
            "icon": w["icon"],
            "nivel_aer": nivel,
            "recomandare": rec,
            "scor_gradinarit": scor_gradinarit(w["temp"], pm, w["desc"]),
            "source": "live",
        })

    except Exception as e:
        return jsonify({"eroare": str(e)}), 500


@app.route("/api/random-city")
def random_city():
    city = random.choice(CITY_NAMES)
    return api_live(city)


@app.route("/api/measurements", methods=["GET"])
def get_measurements():
    limit = request.args.get("limit", 80, type=int)
    source = request.args.get("source")

    query = "SELECT * FROM measurements"
    args = []

    if source:
        query += " WHERE source=%s"
        args.append(source)

    query += " ORDER BY id DESC LIMIT %s"
    args.append(limit)

    rows = db_exec(query, tuple(args), fetchall=True)

    for r in rows:
        if r.get("timestamp"):
            r["timestamp"] = str(r["timestamp"])

    return jsonify(rows)


@app.route("/api/measurements", methods=["POST"])
def add_manual():
    d = request.json or {}

    oras = d.get("oras")
    temp = d.get("temperatura")
    pm25 = d.get("pm25")

    if not oras or temp is None or pm25 is None:
        return jsonify({"eroare": "oras, temperatura si pm25 sunt obligatorii"}), 400

    nivel, rec = save_measurement(
        oras,
        temp,
        pm25,
        d.get("lat"),
        d.get("lon"),
        d.get("descriere", "manual"),
        "manual",
    )

    return jsonify({
        "mesaj": "adaugat",
        "nivel_aer": nivel,
        "recomandare": rec,
        "scor_gradinarit": scor_gradinarit(temp, pm25, d.get("descriere", "")),
    }), 201


@app.route("/api/measurements/<int:id>", methods=["DELETE"])
def delete_measurement(id):
    db_exec("DELETE FROM measurements WHERE id=%s", (id,))
    return jsonify({"mesaj": "sters"})


@app.route("/api/measurements/clear", methods=["POST"])
def clear_measurements():
    db_exec("DELETE FROM measurements")
    return jsonify({"mesaj": "istoric sters"})


@app.route("/generate/<int:n>", methods=["POST"])
def generate_n(n):
    n = min(n, 20)
    results = []

    for _ in range(n):
        city, lat, lon = random.choice(ROMANIA_CITIES)
        temp = round(random.uniform(-5, 38), 1)
        pm = round(random.uniform(5, 160), 1)
        desc = random.choice([
            "cer senin",
            "noros",
            "ploaie usoara",
            "ceata",
            "vant moderat",
            "soare puternic",
        ])

        nivel, rec = save_measurement(city, temp, pm, lat, lon, desc, "simulator")

        results.append({
            "oras": city,
            "temperatura": temp,
            "pm25": pm,
            "nivel_aer": nivel,
            "recomandare": rec,
        })

    return jsonify({
        "generat": len(results),
        "results": results,
    })


@app.route("/generate", methods=["POST"])
def generate_one():
    return generate_n(1)


@app.route("/api/stats")
def stats():
    total = db_exec("SELECT COUNT(*) AS n FROM measurements", fetchone=True).get("n", 0)
    avg_t = db_exec("SELECT ROUND(AVG(temperatura),1) AS v FROM measurements", fetchone=True).get("v")
    avg_pm = db_exec("SELECT ROUND(AVG(pm25),1) AS v FROM measurements", fetchone=True).get("v")
    max_pm = db_exec("SELECT MAX(pm25) AS v FROM measurements", fetchone=True).get("v")
    min_t = db_exec("SELECT MIN(temperatura) AS v FROM measurements", fetchone=True).get("v")
    max_t = db_exec("SELECT MAX(temperatura) AS v FROM measurements", fetchone=True).get("v")

    by_source = db_exec("""
        SELECT source, COUNT(*) AS nr
        FROM measurements
        GROUP BY source
    """, fetchall=True)

    return jsonify({
        "total": total,
        "avg_temp": avg_t,
        "avg_pm": avg_pm,
        "max_pm": max_pm,
        "min_temp": min_t,
        "max_temp": max_t,
        "by_source": by_source,
    })


@app.route("/api/top/romania")
def top_romania():
    results = []

    for city, lat, lon in ROMANIA_CITIES:
        try:
            w = get_weather(city)
            pm = get_pm25(city)
            nivel, rec = save_measurement(
                city,
                w["temp"],
                pm,
                w["lat"],
                w["lon"],
                w["desc"],
                "top_romania",
            )

            results.append({
                "oras": city,
                "temperatura": w["temp"],
                "pm25": pm,
                "descriere": w["desc"],
                "nivel_aer": nivel,
                "recomandare": rec,
                "scor_gradinarit": scor_gradinarit(w["temp"], pm, w["desc"]),
            })
        except Exception:
            pass

    valid_pm = [r for r in results if r["pm25"] is not None]

    return jsonify({
        "best_air": sorted(valid_pm, key=lambda x: x["pm25"])[:5],
        "worst_air": sorted(valid_pm, key=lambda x: x["pm25"], reverse=True)[:5],
        "best_garden": sorted(results, key=lambda x: x["scor_gradinarit"], reverse=True)[:5],
        "hottest": sorted(results, key=lambda x: x["temperatura"], reverse=True)[:3],
        "coldest": sorted(results, key=lambda x: x["temperatura"])[:3],
    })


@app.route("/api/export/csv")
def export_csv():
    rows = db_exec("SELECT * FROM measurements ORDER BY id DESC", fetchall=True)

    csv_data = "id,oras,temperatura,pm25,lat,lon,descriere,recomandare,nivel_aer,source,timestamp\n"

    for r in rows:
        csv_data += (
            f'{r.get("id","")},'
            f'{r.get("oras","")},'
            f'{r.get("temperatura","")},'
            f'{r.get("pm25","")},'
            f'{r.get("lat","")},'
            f'{r.get("lon","")},'
            f'"{r.get("descriere","")}",'
            f'"{r.get("recomandare","")}",'
            f'{r.get("nivel_aer","")},'
            f'{r.get("source","")},'
            f'{r.get("timestamp","")}\n'
        )

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=meteo_export.csv"},
    )


try:
    init_db()
except Exception as e:
    print("INIT DB FAILED:", e)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
