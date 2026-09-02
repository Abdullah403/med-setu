import sqlite3

conn = sqlite3.connect("med_setu.db")
c = conn.cursor()

c.execute("UPDATE users SET role = 'RECEPTIONIST' WHERE role = 'receptionist'")
print(f"Normalized {c.rowcount} receptionist row(s)")

c.execute("UPDATE users SET role = 'DOCTOR' WHERE role = 'doctor'")
print(f"Normalized {c.rowcount} doctor row(s)")

c.execute("UPDATE users SET role = 'HOSPITAL_ADMIN' WHERE role = 'hospital_admin'")
c.execute("UPDATE users SET role = 'GOVERNMENT_ADMIN' WHERE role = 'government_admin'")

conn.commit()

print("\nCurrent users table contents:")
for row in c.execute("SELECT id, username, role, full_name, facility_id FROM users").fetchall():
    print(row)

conn.close()
