from app import app, db, User
from werkzeug.security import generate_password_hash

def seed():
    print(">>> MEMULAI RESET DATABASE TOTAL...")
    with app.app_context():
        db.drop_all()
        db.create_all()
        print(">>> TABEL BERHASIL DIBUAT ULANG.")

        # 1. OWNER (Pusat, No Absen)
        owner = User(username='owner', full_name='Big Boss', role='OWNER', branch='Pusat', is_approved=True)
        owner.set_password('123')
        db.session.add(owner)

        # 2. MANAGER (Pusat, Wajib Absen, Lihat Semua)
        manager = User(username='manager', full_name='General Manager', role='MANAGER', branch='Pusat', is_approved=True)
        manager.set_password('123')
        db.session.add(manager)

        # 3. SPV (Cabang, Wajib Absen, Lihat Cabang Sendiri)
        spv = User(username='spv_jakbar', full_name='SPV Jakarta Barat', role='SPV', branch='Jakbar', is_approved=True)
        spv.set_password('123')
        db.session.add(spv)

        # 4. STAFF
        staff = User(username='maryam', full_name='Maryam', role='STAFF', branch='Jakbar', is_approved=True)
        staff.set_password('123')
        db.session.add(staff)

        db.session.commit()
        print(">>> SUKSES! Login: owner / 123")

if __name__ == '__main__':
    seed()