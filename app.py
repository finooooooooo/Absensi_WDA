import os
import datetime
import pytz
import base64
import io
import pandas as pd
from PIL import Image
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import extract, func

# Initialize App
app = Flask(__name__)
app.secret_key = 'wine_dental_secure_key_123'  # Change for production

# Database Configuration
# Default to PostgreSQL as requested for final code
DEFAULT_DB_URI = 'postgresql://postgres:5432@localhost:5432/wine_db'
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', DEFAULT_DB_URI)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Constants & Configuration
TIMEZONE = pytz.timezone('Asia/Jakarta')

# Geofencing Placeholders (Mock)
CLINIC_LAT = -6.123456
CLINIC_LNG = 106.123456
GEOFENCE_RADIUS_METERS = 100  # Example radius

# Shift Rules
SHIFT_RULES = {
    'Pagi': {'start': '10:00', 'end': '16:00', 'ops_pulang': '16:00', 'code_staff': 'P', 'code_spv': '1'},
    'Siang': {'start': '12:00', 'end': '20:00', 'ops_pulang': '20:00', 'code_staff': 'S', 'code_spv': '2'},
    'Sore': {'start': '16:00', 'end': '22:00', 'ops_pulang': '22:00', 'code_staff': 'M', 'code_spv': '2'},
}

# --- MODELS ---

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'STAFF' or 'SPV' or 'ADMIN'
    full_name = db.Column(db.String(100), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Attendance(db.Model):
    __tablename__ = 'attendance'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)

    # Check-In Data
    shift_type = db.Column(db.String(20)) # Pagi, Siang, Sore
    check_in_time = db.Column(db.DateTime(timezone=True))
    check_in_photo = db.Column(db.Text) # Base64 or path
    check_in_lat = db.Column(db.Float)
    check_in_lng = db.Column(db.Float)

    # Check-Out Data
    check_out_time = db.Column(db.DateTime(timezone=True))
    check_out_photo = db.Column(db.Text)
    check_out_lat = db.Column(db.Float)
    check_out_lng = db.Column(db.Float)

    # Status
    status = db.Column(db.String(20)) # Hadir, Terlambat
    is_overtime = db.Column(db.Boolean, default=False)
    duration_minutes = db.Column(db.Integer, default=0)

    user = db.relationship('User', backref='attendances')

# --- HELPERS ---

def get_server_time():
    return datetime.datetime.now(TIMEZONE)

def is_overtime_enabled():
    now = get_server_time()
    # Overtime enabled if server time >= 16:00
    cutoff = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return now >= cutoff

def calculate_status(check_in_time, shift_type):
    # Simple logic: if check_in > shift start + grace period (e.g. 15 mins), Terlambat
    # Parsing shift start
    if not shift_type or shift_type not in SHIFT_RULES:
        return "Hadir"

    start_str = SHIFT_RULES[shift_type]['start']
    start_hour, start_minute = map(int, start_str.split(':'))

    shift_start = check_in_time.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)

    # 15 minutes grace period
    grace_period = datetime.timedelta(minutes=15)

    if check_in_time > (shift_start + grace_period):
        return "Terlambat"
    return "Hadir"

def ensure_timezone(dt):
    """Ensures datetime object has timezone info (Asia/Jakarta)"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return TIMEZONE.localize(dt)
    return dt

# --- ROUTES ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session['user_id'] = user.id
            session['user_role'] = user.role
            session['user_name'] = user.full_name
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error="Invalid username or password")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    now = get_server_time()
    today_date = now.date()

    # Check if user already checked in today
    attendance = Attendance.query.filter_by(user_id=user_id, date=today_date).first()

    current_status = "None"
    shift_type = ""

    if attendance:
        shift_type = attendance.shift_type
        if attendance.check_out_time:
            current_status = "CheckedOut"
        else:
            current_status = "CheckedIn"

    return render_template('dashboard.html',
                           user_name=session['user_name'],
                           role=session['user_role'],
                           current_status=current_status,
                           shift_type=shift_type,
                           overtime_enabled=is_overtime_enabled(),
                           server_date=now.strftime("%d %B %Y"))

# API Routes for SPA

@app.route('/api/status')
def api_status():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    user_id = session['user_id']
    now = get_server_time()
    today_date = now.date()
    attendance = Attendance.query.filter_by(user_id=user_id, date=today_date).first()

    status_code = "None"
    shift = None
    check_in_time = None
    check_out_time = None

    if attendance:
        shift = attendance.shift_type

        # Format times (handle timezone aware/naive safely)
        cin = ensure_timezone(attendance.check_in_time)
        cout = ensure_timezone(attendance.check_out_time)

        check_in_time = cin.strftime("%H:%M") if cin else None
        check_out_time = cout.strftime("%H:%M") if cout else None

        if attendance.check_out_time:
            status_code = "CheckedOut"
        else:
            status_code = "CheckedIn"

    return jsonify({
        'status': status_code,
        'shift': shift,
        'check_in_time': check_in_time,
        'check_out_time': check_out_time,
        'overtime_enabled': is_overtime_enabled()
    })

@app.route('/api/check_in', methods=['POST'])
def api_check_in():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    data = request.json
    user_id = session['user_id']
    shift = data.get('shift')
    photo_base64 = data.get('photo')
    lat = data.get('lat')
    lng = data.get('lng')

    now = get_server_time()

    # Check if already checked in
    existing = Attendance.query.filter_by(user_id=user_id, date=now.date()).first()
    if existing:
         return jsonify({'success': False, 'message': 'Already checked in for today.'}), 400

    # Logic for Geofencing would go here (mocked as per instructions)

    status = calculate_status(now, shift)

    new_attendance = Attendance(
        user_id=user_id,
        date=now.date(),
        shift_type=shift,
        check_in_time=now,
        check_in_photo=photo_base64, # In prod, save file and store path
        check_in_lat=lat,
        check_in_lng=lng,
        status=status,
        is_overtime=False
    )

    db.session.add(new_attendance)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Check-in Successful!'})

@app.route('/api/check_out', methods=['POST'])
def api_check_out():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    data = request.json
    user_id = session['user_id']
    photo_base64 = data.get('photo')
    lat = data.get('lat')
    lng = data.get('lng')
    is_overtime = data.get('is_overtime', False)

    now = get_server_time()

    attendance = Attendance.query.filter_by(user_id=user_id, date=now.date()).first()
    if not attendance:
        return jsonify({'success': False, 'message': 'No check-in record found for today.'}), 400

    if attendance.check_out_time:
        return jsonify({'success': False, 'message': 'Already checked out.'}), 400

    attendance.check_out_time = now
    attendance.check_out_photo = photo_base64
    attendance.check_out_lat = lat
    attendance.check_out_lng = lng
    attendance.is_overtime = is_overtime

    # Calculate duration
    # Ensure check_in_time has timezone info (SQLite might return naive)
    check_in_tz = ensure_timezone(attendance.check_in_time)

    # now is already timezone aware (Asia/Jakarta) from get_server_time()
    duration = (now - check_in_tz).total_seconds() / 60
    attendance.duration_minutes = int(duration)

    db.session.commit()

    return jsonify({'success': True, 'message': 'Check-out Successful!'})

@app.route('/api/history')
def api_history():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    user_id = session['user_id']
    # Last 30 days
    history = Attendance.query.filter_by(user_id=user_id).order_by(Attendance.date.desc()).limit(30).all()

    data = []
    for h in history:
        cin = ensure_timezone(h.check_in_time)
        cout = ensure_timezone(h.check_out_time)

        data.append({
            'date': h.date.strftime("%d %b %Y"),
            'shift': h.shift_type,
            'in': cin.strftime("%H:%M") if cin else "-",
            'out': cout.strftime("%H:%M") if cout else "-",
            'status': h.status
        })

    return jsonify(data)

# --- EXPORT LOGIC ---

@app.route('/export')
def export_data():
    if 'user_role' not in session or session['user_role'] not in ['ADMIN', 'SPV']:
        return "Unauthorized", 403

    # Generate the 3 reports

    users = User.query.filter(User.role != 'ADMIN').all()
    attendances = Attendance.query.all()

    # Convert to DF
    data_list = []
    for a in attendances:
        cin = ensure_timezone(a.check_in_time)
        cout = ensure_timezone(a.check_out_time)

        data_list.append({
            'user_id': a.user_id,
            'date': a.date,
            'status': a.status,
            'shift': a.shift_type,
            'check_in': cin,
            'check_out': cout
        })
    df_att = pd.DataFrame(data_list)
    if not df_att.empty:
        df_att['date'] = pd.to_datetime(df_att['date'])
        df_att['day'] = df_att['date'].dt.day

    # --- REPORT A: Absensi Harian ---
    report_a_data = []

    for i, user in enumerate(users, 1):
        row = {'NO': i, 'NAMA KARYAWAN': user.full_name}
        total_present = 0

        user_atts = df_att[df_att['user_id'] == user.id] if not df_att.empty else pd.DataFrame()

        for day in range(1, 32):
            val = ""
            if not user_atts.empty:
                att_day = user_atts[user_atts['day'] == day]
                if not att_day.empty:
                    status = att_day.iloc[0]['status']
                    if status == 'Hadir':
                        val = 'H'
                        total_present += 1
                    elif status == 'Terlambat':
                        val = 'T'
                        total_present += 1

            row[str(day)] = val

        row['Total Hari'] = total_present
        report_a_data.append(row)

    df_report_a = pd.DataFrame(report_a_data)
    cols_a = ['NO', 'NAMA KARYAWAN', 'Total Hari'] + [str(d) for d in range(1, 32)]
    for c in cols_a:
        if c not in df_report_a.columns:
            df_report_a[c] = ""
    df_report_a = df_report_a[cols_a]

    # --- REPORT B: Absensi Shift ---
    report_b_data = []

    for i, user in enumerate(users, 1):
        row = {
            'NO': i, 'NAMA': user.full_name,
            'Alpa': 0, 'Sakit': 0, 'Izin': 0, 'Shift Hadir': 0
        }

        user_atts = df_att[df_att['user_id'] == user.id] if not df_att.empty else pd.DataFrame()
        shift_hadir_count = 0

        for day in range(1, 32):
            code = ""
            if not user_atts.empty:
                att_day = user_atts[user_atts['day'] == day]
                if not att_day.empty:
                    shift = att_day.iloc[0]['shift']
                    shift_hadir_count += 1

                    if user.role == 'SPV':
                        if shift == 'Pagi': code = "1"
                        elif shift in ['Siang', 'Sore']: code = "2"
                    else: # STAFF
                        if shift == 'Pagi': code = "P"
                        elif shift == 'Siang': code = "S"
                        elif shift == 'Sore': code = "M"

            row[str(day)] = code

        row['Shift Hadir'] = shift_hadir_count
        report_b_data.append(row)

    df_report_b = pd.DataFrame(report_b_data)
    cols_b = ['NO', 'NAMA', 'Alpa', 'Sakit', 'Izin', 'Shift Hadir'] + [str(d) for d in range(1, 32)]
    for c in cols_b:
        if c not in df_report_b.columns:
            df_report_b[c] = ""
    df_report_b = df_report_b[cols_b]

    # --- REPORT C: Lembur ---
    report_c_data = []

    if not df_att.empty:
        for idx, row in df_att.iterrows():
            if pd.isna(row['check_out']): continue

            shift = row['shift']
            if not shift or shift not in SHIFT_RULES: continue

            ops_pulang_str = SHIFT_RULES[shift]['ops_pulang']
            ops_mulai_str = SHIFT_RULES[shift]['start']

            current_date = row['date']

            ops_pulang_time = datetime.datetime.strptime(ops_pulang_str, "%H:%M").time()
            ops_pulang_dt = datetime.datetime.combine(current_date, ops_pulang_time)
            ops_pulang_dt = TIMEZONE.localize(ops_pulang_dt)

            check_out_dt = row['check_out']
            # Both should now be aware in TIMEZONE

            waktu_lembur = ""
            if check_out_dt > ops_pulang_dt:
                diff = check_out_dt - ops_pulang_dt
                total_seconds = int(diff.total_seconds())
                hours, remainder = divmod(total_seconds, 3600)
                minutes, _ = divmod(remainder, 60)
                waktu_lembur = f"{hours:02}:{minutes:02}"

            report_c_data.append({
                'ID': row['user_id'],
                'TANGGAL': row['date'].strftime("%Y-%m-%d"),
                'TIPE SHIFT': shift,
                'TIMESTAMP_IN': row['check_in'].strftime("%H:%M:%S") if row['check_in'] else "",
                'OPS_MULAI': ops_mulai_str,
                'OPS_PULANG': ops_pulang_str,
                'TIMESTAMP_OUT': row['check_out'].strftime("%H:%M:%S"),
                'WAKTU_LEMBUR': waktu_lembur
            })

    df_report_c = pd.DataFrame(report_c_data)
    cols_c = ['ID', 'TANGGAL', 'TIPE SHIFT', 'TIMESTAMP_IN', 'OPS_MULAI', 'OPS_PULANG', 'TIMESTAMP_OUT', 'WAKTU_LEMBUR']
    if df_report_c.empty:
        df_report_c = pd.DataFrame(columns=cols_c)
    else:
        df_report_c = df_report_c[cols_c]

    # Save to Excel
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_report_a.to_excel(writer, sheet_name='Absensi Harian', index=False)
        df_report_b.to_excel(writer, sheet_name='Absensi Shift', index=False)
        df_report_c.to_excel(writer, sheet_name='Lembur', index=False)

    output.seek(0)

    filename = f"Laporan_WineDental_{datetime.datetime.now().strftime('%Y%m%d')}.xlsx"
    return send_file(output, as_attachment=True, download_name=filename, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0', port=5000)
