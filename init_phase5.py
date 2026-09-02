"""Initialize Phase 5 database"""
import os

if os.path.exists('med_setu.db'):
    os.remove('med_setu.db')
    print("Old database deleted")

from database.db import init_db
init_db()
print("Database initialized with seed data")

from database.db import get_session
from database.models import User
db = get_session()
users = db.query(User).all()
print(f"\nUsers created: {len(users)}")
for u in users:
    print(f"  - {u.username} ({u.role.value})")
db.close()
print("\n✓ Ready for Phase 5 tests")
