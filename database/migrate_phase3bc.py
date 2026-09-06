"""Phase 3B+3C: Backward-compatible migration.

Adds columns for worker-submitted intake tracking and worker follow-up
outcome tracking. All new columns are nullable, so existing data is preserved.

Run once: python -m database.migrate_phase3bc
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "med_setu.db")

COLUMNS_TO_ADD = [
    # PatientCase columns (Phase 3B)
    ("patient_cases", "submitted_by_worker_id", "INTEGER"),
    ("patient_cases", "submitted_at", "DATETIME"),
    ("patient_cases", "worker_notes", "TEXT DEFAULT ''"),
    # FollowUp columns (Phase 3C)
    ("follow_ups", "worker_outcome", "TEXT DEFAULT ''"),
    ("follow_ups", "worker_outcome_at", "DATETIME"),
    ("follow_ups", "worker_outcome_by_id", "INTEGER"),
    ("follow_ups", "worker_outcome_notes", "TEXT DEFAULT ''"),
    ("follow_ups", "escalated", "BOOLEAN DEFAULT 0"),
    ("follow_ups", "escalated_at", "DATETIME"),
]


def _column_exists(cursor, table, column):
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def migrate():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}. Skipping migration.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    added = 0
    for table, column, col_type in COLUMNS_TO_ADD:
        if not _column_exists(cursor, table, column):
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            added += 1
            print(f"  + Added {table}.{column}")

    conn.commit()
    conn.close()

    if added:
        print(f"[OK] Phase 3B+3C migration complete: {added} column(s) added.")
    else:
        print("[OK] Phase 3B+3C migration already applied. No changes needed.")


if __name__ == "__main__":
    migrate()
