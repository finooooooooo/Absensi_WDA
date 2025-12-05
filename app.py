import os
import datetime
import pytz
import io
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'wine_dental_secure_key_prod' 

# Database Config
database_url = os.environ.get('DATABASE_URL', 'postgresql://postgres:5432@localhost:5432/wine_db')
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
TIMEZONE = pytz.timezone('Asia/Jakarta')

SHIFT_RULES = {
    'Pagi': {'start': '10:00', 'end': '16:00', 'ops_pulang': '16:00'},
    'Siang': {'start': '12:00', 'end': '20:00', 'ops_pulang': '20:00'},
    'Sore': {'start': '16:00', 'end': '22:00', 'ops_pulang': '22:00'},
}

# --- MODELS ---
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), nullable=False) 
    branch = db.Column(db.String(50), nullable=True) 
    is_approved = db.Column(db.Boolean, default=False)
    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)

class Attendance(db.Model):
    __tablename__ = 'attendance'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    shift_type = db.Column(db.String(20))
    check_in_time = db.Column(db.DateTime(timezone=True))
    check_in_photo = db.Column(db.Text)
    check_in_lat = db.Column(db.Float)
    check_in_lng = db.Column(db.Float)
    check_out_time = db.Column(db.DateTime(timezone=True))
    check_out_photo = db.Column(db.Text)
    check_out_lat = db.Column(db.Float)
    check_out_lng = db.Column(db.Float)
    status = db.Column(db.String(20))
    is_overtime = db.Column(db.Boolean, default=False)
    user = db.relationship('User', backref='attendances')

class UserSchedule(db.Model):
    __tablename__ = 'user_schedules'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False) 
    description = db.Column(db.String(255), nullable=True)
    user = db.relationship('User', backref='schedules')

# --- HELPERS ---
def get_server_time(): return datetime.datetime.now(TIMEZONE)
def ensure_timezone(dt):
    if dt is None: return None
    if dt.tzinfo is None: return TIMEZONE.localize(dt)
    return dt.astimezone(TIMEZONE)
def calculate_status(check_in_time, shift_type):
    if not shift_type or shift_type not in SHIFT_RULES: return "Hadir"
    start_str = SHIFT_RULES[shift_type]['start']
    start_hour, start_minute = map(int, start_str.split(':'))
    shift_start = check_in_time.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
    if check_in_time > (shift_start + datetime.timedelta(minutes=1)): return "Terlambat"
    return "Hadir"

# --- ROUTES ---
@app.route('/')
def index(): return redirect(url_for('login') if 'user_id' not in session else url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and user.check_password(request.form['password']):
            if not user.is_approved:
                flash("Akun belum disetujui Owner.", "warning")
                return render_template('login.html')
            session['user_id'] = user.id
            session['user_role'] = user.role
            session['user_branch'] = user.branch
            session['user_name'] = user.full_name
            return redirect(url_for('dashboard'))
        flash("Login Gagal.", "danger")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if User.query.filter_by(username=request.form['username']).first():
            flash("Username sudah ada", "danger")
            return redirect(url_for('register'))
        new_user = User(
            username=request.form['username'],
            full_name=request.form['full_name'],
            role=request.form.get('role', 'STAFF'),
            branch=request.form['branch'],
            is_approved=False
        )
        new_user.set_password(request.form['password'])
        db.session.add(new_user)
        db.session.commit()
        flash("Registrasi Sukses! Tunggu Approval.", "success")
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    role = session['user_role']

    # 1. STAFF DASHBOARD
    if role == 'STAFF':
        return render_template('dashboard_staff.html', user_name=session['user_name'], role=role, server_date=get_server_time().strftime("%d %B %Y"))

    # 2. LOGIC ADMIN/MANAGER/SPV
    pending_users = []
    if role in ['OWNER', 'MANAGER']:
        pending_users = User.query.filter_by(is_approved=False).all()

    today = get_server_time().date()
    query = Attendance.query.join(User).filter(Attendance.date == today)
    
    # SPV hanya lihat cabangnya
    if role == 'SPV': query = query.filter(User.branch == session['user_branch'])
    
    monitoring_data = []
    for att in query.all():
        pot_overtime = ""
        if att.check_out_time and att.shift_type in SHIFT_RULES:
            ops_str = SHIFT_RULES[att.shift_type]['ops_pulang']
            ops_time = datetime.datetime.strptime(ops_str, "%H:%M").time()
            checkout_local = ensure_timezone(att.check_out_time)
            ops_dt = checkout_local.replace(hour=ops_time.hour, minute=ops_time.minute, second=0)
            if checkout_local > ops_dt:
                diff = (checkout_local - ops_dt).total_seconds() / 60
                if diff > 0: pot_overtime = f"{int(diff // 60)}h {int(diff % 60)}m"

        monitoring_data.append({
            'id': att.id, 'name': att.user.full_name, 'role': att.user.role, 'branch': att.user.branch,
            'shift': att.shift_type, 'status': att.status, 'is_overtime': att.is_overtime, 'potential_overtime': pot_overtime,
            'in': ensure_timezone(att.check_in_time).strftime("%H:%M") if att.check_in_time else "-",
            'out': ensure_timezone(att.check_out_time).strftime("%H:%M") if att.check_out_time else "-",
            'photo_in': att.check_in_photo, 'photo_out': att.check_out_photo
        })

    # 3. MANAGER & SPV -> DASHBOARD OPERASIONAL (WAJIB ABSEN)
    if role in ['MANAGER', 'SPV']:
        return render_template('dashboard_manager.html', 
                               user_name=session['user_name'], role=role, 
                               pending_users=pending_users, monitoring_data=monitoring_data, 
                               server_date=get_server_time().strftime("%d %B %Y"))

    # 4. OWNER -> DASHBOARD ADMIN (NO ABSEN)
    return render_template('dashboard_admin.html', 
                           user_name=session['user_name'], role=role, 
                           pending_users=pending_users, monitoring_data=monitoring_data, 
                           server_date=get_server_time().strftime("%d %B %Y"))

# --- ACTIONS ---
@app.route('/approve_user/<int:user_id>', methods=['POST'])
def approve_user(user_id):
    if session['user_role'] in ['OWNER', 'MANAGER']:
        User.query.get(user_id).is_approved = True
        db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/approve_overtime/<int:att_id>', methods=['POST'])
def approve_overtime(att_id):
    if session['user_role'] != 'STAFF':
        Attendance.query.get(att_id).is_overtime = True
        db.session.commit()
    return redirect(url_for('dashboard'))

# --- SCHEDULES ---
@app.route('/admin')
def admin_panel():
    if session['user_role'] == 'STAFF': return redirect(url_for('dashboard'))
    users = User.query.filter_by(branch=session['user_branch']).all() if session['user_role'] == 'SPV' else User.query.all()
    return render_template('admin.html', users=users, schedules=UserSchedule.query.order_by(UserSchedule.date.desc()).all())

@app.route('/add_schedule', methods=['POST'])
def add_schedule():
    if session['user_role'] == 'STAFF': return "Unauthorized", 403
    uid = None if request.form['user_id'] == 'global' else int(request.form['user_id'])
    db.session.add(UserSchedule(user_id=uid, date=datetime.datetime.strptime(request.form['date'], '%Y-%m-%d').date(), status=request.form['status'], description=request.form['description']))
    db.session.commit()
    return redirect(url_for('admin_panel'))

@app.route('/delete_schedule/<int:id>', methods=['POST'])
def delete_schedule(id):
    db.session.delete(UserSchedule.query.get(id))
    db.session.commit()
    return redirect(url_for('admin_panel'))

# --- API ---
@app.route('/api/status')
def api_status():
    if 'user_id' not in session: return jsonify({'error': 'Unauthorized'}), 401
    att = Attendance.query.filter_by(user_id=session['user_id'], date=get_server_time().date()).first()
    stat = "CheckedOut" if att and att.check_out_time else ("CheckedIn" if att else "None")
    return jsonify({'status': stat, 'shift': att.shift_type if att else "", 'check_in_time': ensure_timezone(att.check_in_time).strftime("%H:%M") if att and att.check_in_time else None, 'check_out_time': ensure_timezone(att.check_out_time).strftime("%H:%M") if att and att.check_out_time else None})

@app.route('/api/check_in', methods=['POST'])
def api_check_in():
    data, uid, now = request.json, session['user_id'], get_server_time()
    if Attendance.query.filter_by(user_id=uid, date=now.date()).first(): return jsonify({'success': False, 'message': 'Sudah check-in'}), 400
    db.session.add(Attendance(user_id=uid, date=now.date(), shift_type=data.get('shift'), check_in_time=now, check_in_photo=data.get('photo'), check_in_lat=data.get('lat'), check_in_lng=data.get('lng'), status=calculate_status(now, data.get('shift'))))
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/check_out', methods=['POST'])
def api_check_out():
    att = Attendance.query.filter_by(user_id=session['user_id'], date=get_server_time().date()).first()
    if not att or att.check_out_time: return jsonify({'success': False, 'message': 'Gagal checkout'}), 400
    att.check_out_time = get_server_time()
    att.check_out_photo = request.json.get('photo')
    att.check_out_lat, att.check_out_lng = request.json.get('lat'), request.json.get('lng')
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/history')
def api_history():
    history = Attendance.query.filter_by(user_id=session['user_id']).order_by(Attendance.date.desc()).limit(10).all()
    return jsonify([{'date': h.date.strftime("%d %b %Y"), 'shift': h.shift_type, 'in': ensure_timezone(h.check_in_time).strftime("%H:%M") if h.check_in_time else "-", 'out': ensure_timezone(h.check_out_time).strftime("%H:%M") if h.check_out_time else "-", 'status': h.status} for h in history])

@app.route('/export')
def export():
    if session['user_role'] == 'STAFF': return "Unauthorized", 403
    q = Attendance.query.join(User)
    if session['user_role'] == 'SPV': q = q.filter(User.branch == session['user_branch'])
    data = [{'Nama': a.user.full_name, 'Role': a.user.role, 'Branch': a.user.branch, 'Tanggal': a.date, 'Shift': a.shift_type, 'Check In': ensure_timezone(a.check_in_time), 'Check Out': ensure_timezone(a.check_out_time), 'Status': a.status, 'Lembur': 'YA' if a.is_overtime else 'TIDAK'} for a in q.all()]
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer: pd.DataFrame(data).to_excel(writer, index=False, sheet_name='Laporan')
    output.seek(0)
    return send_file(output, as_attachment=True, download_name='Laporan_Absensi.xlsx')

if __name__ == '__main__':
    with app.app_context(): db.create_all()
    app.run(debug=True, host='0.0.0.0', port=5000)