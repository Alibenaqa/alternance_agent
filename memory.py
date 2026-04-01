"""
memory.py — Mémoire persistante de l'agent IA de recherche d'alternance
Gère : offres scrappées, candidatures, alumni contactés, conversations recruteurs

Usage:
    from memory import Memory
    mem = Memory()
    mem.add_offre({...})
    offres = mem.get_offres_non_postulees()
"""

import sqlite3
import json
import os
from datetime import datetime
from pathlib import Path


DB_PATH = Path(__file__).parent / "agent_memory.db"


class Memory:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or DB_PATH
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # accès par nom de colonne
        conn.execute("PRAGMA journal_mode=WAL")  # écriture concurrente
        return conn

    def _init_db(self):
        """Crée toutes les tables si elles n'existent pas."""
        with self._connect() as conn:
            conn.executescript("""
                -- ───────────────────────────────────────────────
                -- OFFRES D'EMPLOI
                -- ───────────────────────────────────────────────
                CREATE TABLE IF NOT EXISTS offres (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    source          TEXT NOT NULL,          -- linkedin, indeed, wttj, hellowork
                    url             TEXT UNIQUE NOT NULL,
                    titre           TEXT NOT NULL,
                    entreprise      TEXT NOT NULL,
                    localisation    TEXT,
                    description     TEXT,
                    date_scrape     TEXT DEFAULT (datetime('now')),
                    date_publication TEXT,
                    score_pertinence REAL DEFAULT 0.0,      -- 0.0 à 1.0, évalué par Claude
                    statut          TEXT DEFAULT 'nouveau', -- nouveau | intéressant | ignoré | postulé | refusé | entretien | offre
                    notif_envoyee   INTEGER DEFAULT 0,      -- 0 = pas encore notifié
                    notes           TEXT
                );

                -- ───────────────────────────────────────────────
                -- CANDIDATURES
                -- ───────────────────────────────────────────────
                CREATE TABLE IF NOT EXISTS candidatures (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    offre_id        INTEGER REFERENCES offres(id),
                    date_candidature TEXT DEFAULT (datetime('now')),
                    canal           TEXT,                   -- email | formulaire_web | linkedin
                    email_dest      TEXT,
                    objet_email     TEXT,
                    corps_email     TEXT,
                    statut          TEXT DEFAULT 'envoyée',  -- envoyée | vue | réponse | relance | refus | entretien
                    date_relance    TEXT,
                    nb_relances     INTEGER DEFAULT 0,
                    notes           TEXT
                );

                -- ───────────────────────────────────────────────
                -- ALUMNI HETIC
                -- ───────────────────────────────────────────────
                CREATE TABLE IF NOT EXISTS alumni (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    prenom          TEXT,
                    nom             TEXT,
                    poste_actuel    TEXT,
                    entreprise      TEXT,
                    linkedin_url    TEXT UNIQUE,
                    email           TEXT,
                    promotion       TEXT,
                    date_scrape     TEXT DEFAULT (datetime('now')),
                    contacte        INTEGER DEFAULT 0,       -- 0 = pas encore contacté
                    date_contact    TEXT,
                    statut_contact  TEXT DEFAULT 'non contacté', -- non contacté | mail envoyé | répondu | relancé
                    notes           TEXT
                );

                -- ───────────────────────────────────────────────
                -- EMAILS ENVOYÉS (log global)
                -- ───────────────────────────────────────────────
                CREATE TABLE IF NOT EXISTS emails_log (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    date_envoi      TEXT DEFAULT (datetime('now')),
                    destinataire    TEXT NOT NULL,
                    objet           TEXT NOT NULL,
                    corps           TEXT,
                    type_email      TEXT,                    -- candidature | alumni | relance | remerciement
                    ref_id          INTEGER,                 -- id de l'offre ou alumni associé
                    ref_type        TEXT,                    -- 'offre' ou 'alumni'
                    statut          TEXT DEFAULT 'envoyé'
                );

                -- ───────────────────────────────────────────────
                -- CONVERSATIONS RECRUTEURS
                -- ───────────────────────────────────────────────
                CREATE TABLE IF NOT EXISTS conversations (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    offre_id        INTEGER REFERENCES offres(id),
                    recruteur_nom   TEXT,
                    recruteur_email TEXT,
                    recruteur_entreprise TEXT,
                    date_premier_contact TEXT DEFAULT (datetime('now')),
                    historique      TEXT,                    -- JSON array de messages
                    statut          TEXT DEFAULT 'en cours', -- en cours | archivé | offre reçue
                    notes           TEXT
                );

                -- ───────────────────────────────────────────────
                -- STATISTIQUES / TABLEAU DE BORD
                -- ───────────────────────────────────────────────
                CREATE TABLE IF NOT EXISTS stats_journalieres (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    date            TEXT DEFAULT (date('now')),
                    offres_scrappees INTEGER DEFAULT 0,
                    offres_interessantes INTEGER DEFAULT 0,
                    candidatures_envoyees INTEGER DEFAULT 0,
                    alumni_contactes INTEGER DEFAULT 0,
                    reponses_recues INTEGER DEFAULT 0
                );

                -- ───────────────────────────────────────────────
                -- MÉMOIRE DU CHAT TELEGRAM
                -- ───────────────────────────────────────────────
                CREATE TABLE IF NOT EXISTS chat_history (
                    id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    date    TEXT DEFAULT (datetime('now')),
                    role    TEXT NOT NULL,   -- 'user' ou 'assistant'
                    content TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS bot_memory (
                    id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    date    TEXT DEFAULT (datetime('now')),
                    cle     TEXT UNIQUE NOT NULL,
                    valeur  TEXT NOT NULL
                );

                -- Index pour les requêtes fréquentes
                CREATE INDEX IF NOT EXISTS idx_offres_statut ON offres(statut);
                CREATE INDEX IF NOT EXISTS idx_offres_score ON offres(score_pertinence DESC);
                CREATE INDEX IF NOT EXISTS idx_alumni_contacte ON alumni(contacte);
                CREATE INDEX IF NOT EXISTS idx_candidatures_statut ON candidatures(statut);
            """)
        print(f"✅ Base de données initialisée : {self.db_path}")

    # ────────────────────────────────────────────────────────────
    # OFFRES
    # ────────────────────────────────────────────────────────────

    def add_offre(self, offre: dict) -> int | None:
        """Ajoute une offre. Retourne l'id créé, ou None si déjà existante."""
        sql = """
            INSERT OR IGNORE INTO offres
                (source, url, titre, entreprise, localisation, description, date_publication, score_pertinence)
            VALUES
                (:source, :url, :titre, :entreprise, :localisation, :description, :date_publication, :score_pertinence)
        """
        with self._connect() as conn:
            cur = conn.execute(sql, {
                "source": offre.get("source", ""),
                "url": self._normaliser_url(offre["url"]),
                "titre": offre.get("titre", ""),
                "entreprise": offre.get("entreprise", ""),
                "localisation": offre.get("localisation", ""),
                "description": offre.get("description", ""),
                "date_publication": offre.get("date_publication"),
                "score_pertinence": offre.get("score_pertinence", 0.0),
            })
            return cur.lastrowid if cur.rowcount else None

    def get_offres_non_notifiees(self) -> list[dict]:
        """Retourne les offres intéressantes pas encore notifiées sur le tel."""
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT * FROM offres
                WHERE statut = 'intéressant' AND notif_envoyee = 0
                ORDER BY score_pertinence DESC
            """).fetchall()
        return [dict(r) for r in rows]

    def get_offres_non_postulees(self, score_min: float = 0.6) -> list[dict]:
        """Retourne les offres au-dessus du score, pas encore postulées."""
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT * FROM offres
                WHERE statut = 'intéressant'
                  AND score_pertinence >= ?
                ORDER BY score_pertinence DESC
            """, (score_min,)).fetchall()
        return [dict(r) for r in rows]

    def update_offre_statut(self, offre_id: int, statut: str, notes: str = None):
        """Met à jour le statut d'une offre (ex: 'postulé', 'refusé', 'entretien')."""
        with self._connect() as conn:
            conn.execute("""
                UPDATE offres SET statut = ?, notes = COALESCE(?, notes)
                WHERE id = ?
            """, (statut, notes, offre_id))

    def marquer_notif_envoyee(self, offre_id: int):
        with self._connect() as conn:
            conn.execute("UPDATE offres SET notif_envoyee = 1 WHERE id = ?", (offre_id,))

    @staticmethod
    def _normaliser_url(url: str) -> str:
        """Normalise une URL pour éviter les faux doublons (tracking params, slash final...)."""
        from urllib.parse import urlparse, urlunparse
        try:
            p = urlparse(url)
            # Retire les paramètres de tracking courants
            path = p.path.rstrip("/")
            return urlunparse((p.scheme, p.netloc.lower(), path, "", "", ""))
        except Exception:
            return url.split("?")[0].rstrip("/")

    def offre_existe(self, url: str) -> bool:
        url_norm = self._normaliser_url(url)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM offres WHERE url = ? OR url = ?", (url, url_norm)
            ).fetchone()
        return row is not None

    # ────────────────────────────────────────────────────────────
    # CANDIDATURES
    # ────────────────────────────────────────────────────────────

    def add_candidature(self, candidature: dict) -> int:
        sql = """
            INSERT INTO candidatures
                (offre_id, canal, email_dest, objet_email, corps_email, date_relance)
            VALUES
                (:offre_id, :canal, :email_dest, :objet_email, :corps_email, :date_relance)
        """
        with self._connect() as conn:
            cur = conn.execute(sql, {
                "offre_id": candidature.get("offre_id"),
                "canal": candidature.get("canal", "email"),
                "email_dest": candidature.get("email_dest", ""),
                "objet_email": candidature.get("objet_email", ""),
                "corps_email": candidature.get("corps_email", ""),
                "date_relance": candidature.get("date_relance"),
            })
            # Met aussi à jour le statut de l'offre
            if candidature.get("offre_id"):
                conn.execute(
                    "UPDATE offres SET statut = 'postulé' WHERE id = ?",
                    (candidature["offre_id"],)
                )
            return cur.lastrowid

    def get_candidatures_a_relancer(self) -> list[dict]:
        """Retourne les candidatures dont la date de relance est passée."""
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT c.*, o.titre, o.entreprise, o.url
                FROM candidatures c
                LEFT JOIN offres o ON c.offre_id = o.id
                WHERE c.statut = 'envoyée'
                  AND c.date_relance <= datetime('now')
                  AND c.nb_relances < 2
            """).fetchall()
        return [dict(r) for r in rows]

    # ────────────────────────────────────────────────────────────
    # ALUMNI
    # ────────────────────────────────────────────────────────────

    def add_alumni(self, alumni: dict) -> int | None:
        sql = """
            INSERT OR IGNORE INTO alumni
                (prenom, nom, poste_actuel, entreprise, linkedin_url, email, promotion)
            VALUES
                (:prenom, :nom, :poste_actuel, :entreprise, :linkedin_url, :email, :promotion)
        """
        with self._connect() as conn:
            cur = conn.execute(sql, {
                "prenom": alumni.get("prenom", ""),
                "nom": alumni.get("nom", ""),
                "poste_actuel": alumni.get("poste_actuel", ""),
                "entreprise": alumni.get("entreprise", ""),
                "linkedin_url": alumni.get("linkedin_url", ""),
                "email": alumni.get("email", ""),
                "promotion": alumni.get("promotion", ""),
            })
            return cur.lastrowid if cur.rowcount else None

    def get_alumni_non_contactes(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT * FROM alumni
                WHERE contacte = 0 AND email IS NOT NULL AND email != ''
                ORDER BY entreprise
            """).fetchall()
        return [dict(r) for r in rows]

    def marquer_alumni_contacte(self, alumni_id: int, email_envoye: str = None):
        with self._connect() as conn:
            conn.execute("""
                UPDATE alumni
                SET contacte = 1,
                    date_contact = datetime('now'),
                    statut_contact = 'mail envoyé'
                WHERE id = ?
            """, (alumni_id,))

    # ────────────────────────────────────────────────────────────
    # EMAILS LOG
    # ────────────────────────────────────────────────────────────

    def log_email(self, email: dict):
        sql = """
            INSERT INTO emails_log (destinataire, objet, corps, type_email, ref_id, ref_type)
            VALUES (:destinataire, :objet, :corps, :type_email, :ref_id, :ref_type)
        """
        with self._connect() as conn:
            conn.execute(sql, {
                "destinataire": email.get("destinataire", ""),
                "objet": email.get("objet", ""),
                "corps": email.get("corps", ""),
                "type_email": email.get("type_email", ""),
                "ref_id": email.get("ref_id"),
                "ref_type": email.get("ref_type"),
            })

    # ────────────────────────────────────────────────────────────
    # MÉMOIRE DU CHAT TELEGRAM
    # ────────────────────────────────────────────────────────────

    def save_message(self, role: str, content: str):
        """Sauvegarde un message de la conversation Telegram."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO chat_history (role, content) VALUES (?, ?)",
                (role, content)
            )

    def load_history(self, limit: int = 40) -> list[dict]:
        """Charge les N derniers messages de la conversation."""
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT role, content FROM chat_history
                ORDER BY id DESC LIMIT ?
            """, (limit,)).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    def clear_history(self):
        """Efface tout l'historique du chat."""
        with self._connect() as conn:
            conn.execute("DELETE FROM chat_history")

    def remember(self, cle: str, valeur: str):
        """Mémorise une info clé/valeur (ex: 'salaire_souhaite', '1200€')."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO bot_memory (cle, valeur) VALUES (?, ?)",
                (cle, valeur)
            )

    def recall(self, cle: str) -> str | None:
        """Récupère une info mémorisée."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT valeur FROM bot_memory WHERE cle = ?", (cle,)
            ).fetchone()
        return row["valeur"] if row else None

    def recall_all(self) -> dict:
        """Retourne toutes les infos mémorisées."""
        with self._connect() as conn:
            rows = conn.execute("SELECT cle, valeur FROM bot_memory").fetchall()
        return {r["cle"]: r["valeur"] for r in rows}

    # ────────────────────────────────────────────────────────────
    # STATS / DASHBOARD
    # ────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Retourne un résumé global pour le dashboard."""
        with self._connect() as conn:
            offres = conn.execute("""
                SELECT statut, COUNT(*) as nb FROM offres GROUP BY statut
            """).fetchall()
            total_alumni = conn.execute("SELECT COUNT(*) FROM alumni").fetchone()[0]
            alumni_contactes = conn.execute(
                "SELECT COUNT(*) FROM alumni WHERE contacte = 1"
            ).fetchone()[0]
            total_candidatures = conn.execute("SELECT COUNT(*) FROM candidatures").fetchone()[0]
            entretiens = conn.execute(
                "SELECT COUNT(*) FROM offres WHERE statut = 'entretien'"
            ).fetchone()[0]

        offres_par_statut = {row["statut"]: row["nb"] for row in offres}

        return {
            "offres_par_statut": offres_par_statut,
            "total_offres": sum(offres_par_statut.values()),
            "total_alumni": total_alumni,
            "alumni_contactes": alumni_contactes,
            "total_candidatures": total_candidatures,
            "entretiens": entretiens,
            "taux_reponse": round(entretiens / total_candidatures * 100, 1) if total_candidatures else 0,
        }

    def print_dashboard(self):
        """Affiche un résumé dans le terminal."""
        stats = self.get_stats()
        print("\n" + "="*50)
        print("📊  DASHBOARD — Recherche Alternance Ali")
        print("="*50)
        print(f"  📋 Offres scrappées      : {stats['total_offres']}")
        for statut, nb in stats["offres_par_statut"].items():
            print(f"     └─ {statut:<18}: {nb}")
        print(f"  📧 Candidatures envoyées : {stats['total_candidatures']}")
        print(f"  🎓 Alumni trouvés        : {stats['total_alumni']}")
        print(f"  📨 Alumni contactés      : {stats['alumni_contactes']}")
        print(f"  💼 Entretiens obtenus    : {stats['entretiens']}")
        print(f"  📈 Taux de réponse       : {stats['taux_reponse']}%")
        print("="*50 + "\n")


# ────────────────────────────────────────────────────────────────
# TEST RAPIDE
# ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    mem = Memory(db_path="test_memory.db")

    # Ajout d'une offre de test
    offre_test = {
        "source": "wttj",
        "url": "https://www.welcometothejungle.com/fr/jobs/test-123",
        "titre": "Alternant Data Scientist - IA générative",
        "entreprise": "Criteo",
        "localisation": "Paris 9e",
        "description": "Rejoins notre équipe ML pour travailler sur des modèles de recommandation...",
        "score_pertinence": 0.87,
    }
    oid = mem.add_offre(offre_test)
    print(f"✅ Offre ajoutée avec id={oid}")

    # Mise à jour statut
    if oid:
        mem.update_offre_statut(oid, "intéressant")
        print(f"✅ Statut mis à jour → intéressant")

    # Alumni de test
    alumni_test = {
        "prenom": "Sarah",
        "nom": "M.",
        "poste_actuel": "Data Analyst",
        "entreprise": "BNP Paribas",
        "linkedin_url": "https://linkedin.com/in/sarah-m-hetic",
        "email": "sarah.m@bnpparibas.com",
        "promotion": "2024",
    }
    aid = mem.add_alumni(alumni_test)
    print(f"✅ Alumni ajouté avec id={aid}")

    # Dashboard
    mem.print_dashboard()

    # Nettoyage fichier test
    import os
    os.remove("test_memory.db")
    print("🧹 Fichier test supprimé")
