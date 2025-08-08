from flask import Flask, render_template, request, jsonify, flash
import qrcode
import os
from datetime import datetime
import psycopg2
import uuid  # ✅ for unique IDs

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # For flash messaging

# ✅ PostgreSQL database connection
def connect_db():
    return psycopg2.connect(
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT")
    )

# Ensure database tables exist
def init_tables():
    conn = connect_db()
    cur = conn.cursor()

    # Staff table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS staff (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100),
            department VARCHAR(100),
            user_id VARCHAR(100) UNIQUE NOT NULL,
            qr_code_path TEXT,
            image_path TEXT
        )
    """)

    # Attendance table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS qr_attendance (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR(255) NOT NULL,
            check_in_time TIMESTAMP,
            check_out_time TIMESTAMP,
            day_of_week VARCHAR(10),
            date DATE NOT NULL,
            FOREIGN KEY (user_id) REFERENCES staff(user_id)
        )
    """)

    conn.commit()
    cur.close()
    conn.close()

# Call at startup
init_tables()

# 🏠 Home/Registration page
@app.route('/')
def home():
    return render_template('register.html')

# 📝 Handle registration
@app.route('/register', methods=['POST'])
def register():
    name = request.form.get('name', '').strip()
    department = request.form.get('department', '').strip()
    image = request.files.get('image')

    if not name or not department or not image:
        flash('Please provide name, department and an image.', 'danger')
        return render_template('register.html')

    # ✅ Generate unique short ID
    user_id = str(uuid.uuid4())[:8]
    qr_data = user_id

    # Create folders
    qr_folder = 'static/qr_codes'
    image_folder = 'static/staff_images'
    os.makedirs(qr_folder, exist_ok=True)
    os.makedirs(image_folder, exist_ok=True)

    # Save QR code
    qr_filename = f"{user_id}.png"
    qr_path = os.path.join(qr_folder, qr_filename)
    qrcode.make(qr_data).save(qr_path)

    # Save uploaded image
    image_ext = os.path.splitext(image.filename)[1]
    image_filename = f"{user_id}{image_ext}"
    image_path = os.path.join(image_folder, image_filename)
    image.save(image_path)

    try:
        conn = connect_db()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO staff (name, department, user_id, qr_code_path, image_path)
            VALUES (%s, %s, %s, %s, %s)
        """, (name, department, user_id, qr_path, image_path))
        conn.commit()

        cur.close()
        conn.close()

        return render_template('success.html',
                               name=name,
                               department=department,
                               filename=qr_filename,
                               image_path='/' + image_path)

    except Exception as e:
        return f"❌ Error saving to database: {e}", 500


# ✅ AJAX endpoint for camera scanner (expects JSON { qr_data: "<user_id>" })
@app.route('/mark_attendance', methods=['POST'])
def mark_attendance():
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"message": "❌ Invalid request — expected JSON body."}), 400

        raw = data.get('qr_data') or data.get('staff_id') or ''
        staff_id = str(raw).strip().lower()
        if not staff_id:
            return jsonify({"message": "❌ No QR data provided"}), 400

        conn = connect_db()
        cur = conn.cursor()

        # Make sure staff exists
        cur.execute("SELECT name FROM staff WHERE user_id = %s", (staff_id,))
        staff_row = cur.fetchone()
        if not staff_row:
            cur.close()
            conn.close()
            return jsonify({"message": "❌ User not found"}), 404

        name = staff_row[0]
        now = datetime.now()
        today = now.date()
        day_name = now.strftime('%A')

        # Check today's record
        cur.execute("""
            SELECT id, check_in_time, check_out_time
            FROM qr_attendance
            WHERE user_id = %s AND date = %s
        """, (staff_id, today))
        record = cur.fetchone()

        if record is None:
            cur.execute("""
                INSERT INTO qr_attendance (user_id, check_in_time, day_of_week, date)
                VALUES (%s, %s, %s, %s)
            """, (staff_id, now, day_name, today))
            message = f"✅ {name} signed in at {now.strftime('%H:%M:%S')} on {day_name}"

        elif record[1] and not record[2]:
            cur.execute("""
                UPDATE qr_attendance
                SET check_out_time = %s
                WHERE id = %s
            """, (now, record[0]))
            message = f"✅ {name} signed out at {now.strftime('%H:%M:%S')} on {day_name}"

        else:
            message = f"⚠️ {name} already signed in and out today"

        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"message": message})

    except Exception as e:
        return jsonify({"message": f"❌ Error recording attendance: {e}"}), 500


# 📷 QR Scanner page — GET shows table, POST handles form-based scans
@app.route('/scan', methods=['GET', 'POST'])
def scan():
    if request.method == 'POST':
        if request.is_json:
            data = request.get_json(silent=True) or {}
            staff_id = (data.get('qr_data') or data.get('staff_id') or '').strip().lower()
        else:
            staff_id = (request.form.get('staff_id') or '').strip().lower()

        if staff_id:
            now = datetime.now()
            today = now.date()
            day_name = now.strftime('%A')

            try:
                conn = connect_db()
                cur = conn.cursor()

                cur.execute("SELECT 1 FROM staff WHERE user_id = %s", (staff_id,))
                if cur.fetchone():
                    cur.execute("""
                        SELECT id, check_in_time, check_out_time
                        FROM qr_attendance
                        WHERE user_id = %s AND date = %s
                    """, (staff_id, today))
                    record = cur.fetchone()

                    if record is None:
                        cur.execute("""
                            INSERT INTO qr_attendance (user_id, check_in_time, day_of_week, date)
                            VALUES (%s, %s, %s, %s)
                        """, (staff_id, now, day_name, today))
                        flash('✅ Check-in recorded successfully!', 'success')

                    elif record[1] and not record[2]:
                        cur.execute("""
                            UPDATE qr_attendance
                            SET check_out_time = %s
                            WHERE id = %s
                        """, (now, record[0]))
                        flash('✅ Check-out recorded successfully!', 'success')

                    else:
                        flash('⚠️ Already checked in and out today.', 'warning')

                    conn.commit()
                else:
                    flash('❌ Staff not registered.', 'danger')

                cur.close()
                conn.close()

            except Exception as e:
                flash(f'❌ Error recording attendance: {e}', 'danger')

    try:
        conn = connect_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT a.user_id, s.name, s.department, s.image_path,
                   a.check_in_time, a.check_out_time, a.date, a.day_of_week
            FROM qr_attendance a
            LEFT JOIN staff s ON a.user_id = s.user_id
            ORDER BY a.date DESC, a.check_in_time DESC
        """)
        attendance_records = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        return f"❌ Error loading table: {e}", 500

    return render_template('scan.html', attendance_records=attendance_records)


# 📋 Full attendance table page
@app.route('/table')
def table():
    try:
        conn = connect_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT a.user_id, s.name, s.department, s.image_path,
                   a.check_in_time, a.check_out_time, a.date, a.day_of_week
            FROM qr_attendance a
            LEFT JOIN staff s ON a.user_id = s.user_id
            ORDER BY a.date DESC, a.check_in_time DESC
        """)
        records = cur.fetchall()
        cur.close()
        conn.close()
        return render_template('table.html', records=records)
    except Exception as e:
        return f"❌ Error loading table: {e}", 500

# Set secret key from environment or fallback (avoid hardcoding in production)
app.secret_key = os.getenv('SECRET_KEY', 'your_default_fallback_secret_key')

# 🚀 Run Flask server
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.getenv("FLASK_DEBUG", "False").lower() in ("true", "1", "t")
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
