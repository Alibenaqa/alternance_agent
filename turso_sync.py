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
        _turso("""
            CREATE TABLE IF NOT EXISTS candidatures_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT,
                entreprise TEXT,
                titre TEXT,
                canal TEXT,
                email_dest TEXT,
                objet_email TEXT,
                date_candidature TEXT,
                statut TEXT DEFAULT 'envoyée',
                nb_relances INTEGER DEFAULT 0
            )
        """)
        _turso("""
            CREATE TABLE IF NOT EXISTS alumni_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                prenom TEXT,
                nom TEXT,
                entreprise TEXT,
                poste_actuel TEXT,
                email TEXT,
                statut_contact TEXT,
                date_contact TEXT
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
    Synchronise les candidatures locales vers Turso (offres + détails candidatures + alumni).
    Appelé après chaque cycle pour garder Turso à jour.
    """
    try:
        mem = Memory()
        with mem._connect() as conn:
            postulees = conn.execute("""
                SELECT o.url, o.entreprise, o.titre
                FROM offres o WHERE o.statut = 'postulé'
            """).fetchall()

            candidatures = conn.execute("""
                SELECT c.canal, c.email_dest, c.objet_email, c.date_candidature,
                       c.statut, c.nb_relances, o.url, o.entreprise, o.titre
                FROM candidatures c
                LEFT JOIN offres o ON c.offre_id = o.id
                ORDER BY c.date_candidature DESC
            """).fetchall()

            alumni = conn.execute("""
                SELECT prenom, nom, entreprise, poste_actuel, email,
                       statut_contact, date_contact
                FROM alumni WHERE contacte = 1
            """).fetchall()

        # Sync offres postulées
        for o in postulees:
            marquer_postule_turso(o["url"], o["entreprise"], o["titre"])

        # Sync candidatures complètes (INSERT OR IGNORE sur url+date)
        for c in candidatures:
            try:
                _turso("""
                    INSERT OR IGNORE INTO candidatures_log
                        (url, entreprise, titre, canal, email_dest, objet_email,
                         date_candidature, statut, nb_relances)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    c["url"] or "", c["entreprise"] or "", c["titre"] or "",
                    c["canal"] or "", c["email_dest"] or "", c["objet_email"] or "",
                    c["date_candidature"] or "", c["statut"] or "envoyée",
                    c["nb_relances"] or 0,
                ])
            except Exception:
                pass

        # Sync alumni contactés
        for a in alumni:
            try:
                _turso("""
                    INSERT OR IGNORE INTO alumni_log
                        (prenom, nom, entreprise, poste_actuel, email,
                         statut_contact, date_contact)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, [
                    a["prenom"] or "", a["nom"] or "", a["entreprise"] or "",
                    a["poste_actuel"] or "", a["email"] or "",
                    a["statut_contact"] or "", a["date_contact"] or "",
                ])
            except Exception:
                pass

        print(f"✅ Turso sync : {len(postulees)} offres, {len(candidatures)} candidatures, {len(alumni)} alumni")
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


def restaurer_tout_depuis_turso():
    """
    Restaure complètement la DB locale depuis Turso au démarrage.
    Restaure : offres postulées + candidatures + alumni.
    Appelé immédiatement au démarrage de main.py.
    """
    # 1. Offres postulées (stubs anti-doublon)
    nb_offres = restaurer_statuts_depuis_turso()

    mem = Memory()

    # 2. Candidatures complètes
    try:
        result = _turso(
            "SELECT url, entreprise, titre, canal, email_dest, objet_email, "
            "date_candidature, statut, nb_relances FROM candidatures_log "
            "ORDER BY date_candidature DESC LIMIT 100"
        )
        rows = result["results"][0]["response"]["result"]["rows"]
        nb_cands = 0
        with mem._connect() as conn:
            for row in rows:
                url        = row[0]["value"] or ""
                entreprise = row[1]["value"] or ""
                titre      = row[2]["value"] or ""
                canal      = row[3]["value"] or ""
                email_dest = row[4]["value"] or ""
                objet      = row[5]["value"] or ""
                date_cand  = row[6]["value"] or ""
                statut     = row[7]["value"] or "envoyée"
                nb_rel     = int(row[8]["value"] or 0)

                # Récupère ou crée l'offre stub
                offre = conn.execute(
                    "SELECT id FROM offres WHERE url = ?", (url,)
                ).fetchone()
                if not offre:
                    conn.execute(
                        "INSERT OR IGNORE INTO offres "
                        "(source, url, titre, entreprise, localisation, statut, score_pertinence) "
                        "VALUES ('turso', ?, ?, ?, '', 'postulé', 0.0)",
                        (url, titre, entreprise)
                    )
                    offre = conn.execute(
                        "SELECT id FROM offres WHERE url = ?", (url,)
                    ).fetchone()

                if offre:
                    existing = conn.execute(
                        "SELECT id FROM candidatures WHERE offre_id = ? AND date_candidature = ?",
                        (offre["id"], date_cand)
                    ).fetchone()
                    if not existing:
                        conn.execute(
                            "INSERT OR IGNORE INTO candidatures "
                            "(offre_id, canal, email_dest, objet_email, date_candidature, statut, nb_relances) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (offre["id"], canal, email_dest, objet, date_cand, statut, nb_rel)
                        )
                        nb_cands += 1
        print(f"✅ Turso restauré : {nb_offres} offres, {nb_cands} candidatures")
    except Exception as e:
        print(f"⚠️  Turso restaurer_candidatures : {e}")

    # 3. Alumni contactés
    try:
        result = _turso(
            "SELECT prenom, nom, entreprise, poste_actuel, email, "
            "statut_contact, date_contact FROM alumni_log LIMIT 50"
        )
        rows = result["results"][0]["response"]["result"]["rows"]
        nb_alumni = 0
        with mem._connect() as conn:
            for row in rows:
                prenom        = row[0]["value"] or ""
                nom           = row[1]["value"] or ""
                entreprise    = row[2]["value"] or ""
                poste_actuel  = row[3]["value"] or ""
                email         = row[4]["value"] or ""
                statut        = row[5]["value"] or "mail envoyé"
                date_contact  = row[6]["value"] or ""

                conn.execute(
                    "INSERT OR IGNORE INTO alumni "
                    "(prenom, nom, entreprise, poste_actuel, email, statut_contact, date_contact, contacte) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                    (prenom, nom, entreprise, poste_actuel, email, statut, date_contact)
                )
                nb_alumni += 1
        if nb_alumni:
            print(f"✅ Turso restauré : {nb_alumni} alumni")
    except Exception as e:
        print(f"⚠️  Turso restaurer_alumni : {e}")


if __name__ == "__main__":
    init_turso()
    print(f"URLs postulées : {get_urls_postulees()}")
