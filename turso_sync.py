"""
turso_sync.py — Synchronisation SQLite local ↔ Turso cloud
Utilisé pour persister les données entre les déploiements Railway.

Stratégie :
- On garde SQLite local comme DB principale (rapide, compatible)
- On synchronise les offres postulées vers Turso au début de chaque cycle
- Au démarrage, on récupère les URLs postulées depuis Turso pour éviter les doublons
"""

import os
import requests
from memory import Memory

TURSO_URL   = os.environ.get("TURSO_URL", "https://alternancebot-alibenaqa.aws-eu-west-1.turso.io")
TURSO_TOKEN = os.environ.get("TURSO_TOKEN", "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJnaWQiOiI3MGZmYTc4My0wM2RkLTQ3ZWEtYTEzNS01MzkwYWIyNjlhYmIiLCJpYXQiOjE3NzUwNzYwMjQsInJpZCI6IjQyZWY5YWY0LWY3OWUtNDFlOS1iZmY4LWNkYzUyYzMyYWQ4NiJ9.jjQL3snXiOgpvsRBzK70vAwOt8a2hZNjrNhjVD5QjQYb7eW52GMH4tqox9VattPM80lOvnshJ0mwl9YLe9RtCg")


def _turso(sql: str, args: list = None) -> dict:
    """Exécute une requête SQL sur Turso via HTTP."""
    stmt = {"sql": sql}
    if args:
        stmt["args"] = [{"type": "text", "value": str(a)} for a in args]

    resp = requests.post(
        f"{TURSO_URL}/v2/pipeline",
        headers={
            "Authorization": f"Bearer {TURSO_TOKEN}",
            "Content-Type": "application/json",
        },
        json={"requests": [
            {"type": "execute", "stmt": stmt},
            {"type": "close"},
        ]},
        timeout=15,
    )
    return resp.json()


def init_turso():
    """Crée les tables sur Turso si elles n'existent pas."""
    try:
        _turso("""
            CREATE TABLE IF NOT EXISTS offres_postulees (
                url TEXT PRIMARY KEY,
                entreprise TEXT,
                titre TEXT,
                date_candidature TEXT DEFAULT (datetime('now'))
            )
        """)
        _turso("""
            CREATE TABLE IF NOT EXISTS emails_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                destinataire TEXT,
                objet TEXT,
                date_envoi TEXT DEFAULT (datetime('now'))
            )
        """)
        print("✅ Turso initialisé")
    except Exception as e:
        print(f"⚠️  Turso init : {e}")


def marquer_postule_turso(url: str, entreprise: str, titre: str):
    """Enregistre une candidature dans Turso."""
    try:
        _turso(
            "INSERT OR IGNORE INTO offres_postulees (url, entreprise, titre) VALUES (?, ?, ?)",
            [url, entreprise, titre]
        )
    except Exception as e:
        print(f"⚠️  Turso marquer_postule : {e}")


def deja_postule_turso(url: str) -> bool:
    """Vérifie si on a déjà postulé à cette offre."""
    try:
        result = _turso(
            "SELECT 1 FROM offres_postulees WHERE url = ?",
            [url]
        )
        rows = result["results"][0]["response"]["result"]["rows"]
        return len(rows) > 0
    except Exception as e:
        print(f"⚠️  Turso check : {e}")
        return False


def get_urls_postulees() -> set:
    """Récupère toutes les URLs déjà postulées depuis Turso."""
    try:
        result = _turso("SELECT url FROM offres_postulees")
        rows = result["results"][0]["response"]["result"]["rows"]
        return {row[0]["value"] for row in rows}
    except Exception as e:
        print(f"⚠️  Turso get_urls : {e}")
        return set()


def sync_candidatures_vers_turso():
    """
    Synchronise les candidatures locales vers Turso.
    Appelé après chaque cycle pour garder Turso à jour.
    """
    try:
        mem = Memory()
        with mem._connect() as conn:
            postulees = conn.execute("""
                SELECT o.url, o.entreprise, o.titre
                FROM offres o
                WHERE o.statut = 'postulé'
            """).fetchall()

        for o in postulees:
            marquer_postule_turso(o["url"], o["entreprise"], o["titre"])

        print(f"✅ Turso sync : {len(postulees)} candidatures synchronisées")
    except Exception as e:
        print(f"⚠️  Turso sync : {e}")


def restaurer_statuts_depuis_turso():
    """
    Au démarrage, récupère les URLs postulées depuis Turso
    et marque ces offres comme 'postulé' dans la DB locale.
    Évite de renvoyer des emails aux mêmes recruteurs.
    """
    try:
        urls = get_urls_postulees()
        if not urls:
            print("ℹ️  Turso : aucune candidature précédente")
            return 0

        mem = Memory()
        with mem._connect() as conn:
            # Marque les offres déjà en base comme postulées
            for url in urls:
                conn.execute(
                    "UPDATE offres SET statut = 'postulé' WHERE url = ? AND statut != 'postulé'",
                    (url,)
                )
            # Insère les URLs manquantes avec statut postulé pour éviter re-scraping
            for url in urls:
                conn.execute("""
                    INSERT OR IGNORE INTO offres
                        (source, url, titre, entreprise, localisation, statut, score_pertinence)
                    VALUES ('turso', ?, 'déjà postulé', '', '', 'postulé', 0.0)
                """, (url,))

        print(f"✅ Turso restauré : {len(urls)} candidatures précédentes chargées")
        return len(urls)
    except Exception as e:
        print(f"⚠️  Turso restaurer : {e}")
        return 0


if __name__ == "__main__":
    init_turso()
    print(f"URLs postulées : {get_urls_postulees()}")
