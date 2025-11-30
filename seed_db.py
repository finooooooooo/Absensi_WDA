from app import app, db, User
import os

def seed():
    print("Starting Database Seeding...")
    # Setup context
    with app.app_context():
        # Create Tables
        db.create_all()
        print("Tables created.")

        # Check if users exist
        if not User.query.filter_by(username='admin').first():
            print("Creating Admin User...")
            admin = User(username='admin', role='ADMIN', full_name='Administrator')
            admin.set_password('admin123')
            db.session.add(admin)
        else:
            print("Admin already exists.")

        if not User.query.filter_by(username='spv').first():
            print("Creating SPV User...")
            spv = User(username='spv', role='SPV', full_name='Supervisor Wine')
            spv.set_password('spv123')
            db.session.add(spv)

        if not User.query.filter_by(username='staff').first():
            print("Creating Staff User...")
            staff = User(username='staff', role='STAFF', full_name='Staff Member')
            staff.set_password('staff123')
            db.session.add(staff)

        db.session.commit()
        print("Database Seeded Successfully!")
        print("Credentials:")
        print("  Admin: admin / admin123")
        print("  SPV: spv / spv123")
        print("  Staff: staff / staff123")

if __name__ == '__main__':
    seed()
