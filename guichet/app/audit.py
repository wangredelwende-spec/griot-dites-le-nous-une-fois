"""Journal d'audit (SQLite) en ajout seul, repris du sprint.

Des déclencheurs SQLite refusent toute modification ou suppression.
Base du futur journal chaîné du médiateur (phase 1).
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class Journal:
    def __init__(self, chemin: Path):
        self._db = sqlite3.connect(chemin, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                horodatage TEXT NOT NULL,   -- UTC
                acteur TEXT NOT NULL,
                action TEXT NOT NULL,
                cible TEXT NOT NULL,
                resultat TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS journal_sans_modification BEFORE UPDATE ON journal
                BEGIN SELECT RAISE(ABORT, 'journal en ajout seul'); END;
            CREATE TRIGGER IF NOT EXISTS journal_sans_suppression BEFORE DELETE ON journal
                BEGIN SELECT RAISE(ABORT, 'journal en ajout seul'); END;
        """)

    def ecrire(self, acteur: str, action: str, cible: str, resultat: str):
        self._db.execute(
            "INSERT INTO journal (horodatage, acteur, action, cible, resultat) VALUES (?, ?, ?, ?, ?)",
            (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), acteur, action, cible, resultat),
        )

    def lire(self, limite: int = 500) -> list[sqlite3.Row]:
        return self._db.execute("SELECT * FROM journal ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
