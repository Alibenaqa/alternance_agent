"""
scraper_france_travail.py — API officielle France Travail (ex Pôle Emploi)
API gratuite, très complète, couvre toutes les offres du service public.

Inscription (2 min) : https://francetravail.io/data/api/offres-emploi
Variables Railway à ajouter :
  FRANCE_TRAVAIL_CLIENT_ID
  FRANCE_TRAVAIL_CLIENT_SECRET

Usage:
    python scraper_france_travail.py
"""

import os
import time
import requests
from memory import Memory

# ────────────────────────────────────────────────
# CONFIGURATION
# ────────────────────────────────────────────────

CLIENT_ID     = os.environ.get("FRANCE_TRAVAIL_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("FRANCE_TRAVAIL_CLIENT_SECRET", "")

AUTH_URL  = "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
API_URL   = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"

MOTS_CLES = [
    "Data Analyst",
    "Data Scientist",
    "Data Engineer",
    "Machine Learning",
    "AI Developer",
    "Développeur IA",
    "MLOps",
    "Développeur Full Stack",
    "Business Intelligence",
    "Intelligence Artificielle",
]

# Type contrat CA = Contrat d'Apprentissage (alternance)
TYPE_CONTRAT   = "CA"
CODE_DEPT      = "75"    # Paris (+ 92, 93, 94 pour l'IDF)
DEPTS_IDF      = ["75", "92", "93", "94", "78", "91", "95", "77"]
RESULTATS_MAX  = 150     # max par requête selon l'API

PAUSE = 2


# ────────────────────────────────────────────────
# AUTHENTIFICATION OAUTH2
# ────────────────────────────────────────────────

_access_token  = None
_token_expires = 0


def _get_token() -> str | None:
    """Obtient un access token OAuth2 France Travail."""
    global _access_token, _token_expires

    if not CLIENT_ID or not CLIENT_SECRET:
        print("   ⚠️  FRANCE_TRAVAIL_CLIENT_ID ou CLIENT_SECRET manquant — skip")
        return None

    import time as t
    if _access_token and t.time() < _token_expires - 60:
        return _access_token

    try:
        resp = requests.post(
            AUTH_URL,
            params={"realm": "/partenaire"},
            data={
                "grant_type":    "client_credentials",
                "client_id":     CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "scope":         (
                    "api_offresdemploiv2 "
                    "application_offresdemploiv2 "
                    "o2dsoffre"
                ),
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        _access_token  = data.get("access_token")
        _token_expires = t.time() + data.get("expires_in", 1400)
        return _access_token
    except Exception as e:
        print(f"   ❌ France Travail auth : {e}")
        return None


# ────────────────────────────────────────────────
# REQUÊTES API
# ────────────────────────────────────────────────

def fetch_offres(keyword: str, dept: str, start: int = 0) -> dict | None:
    """Appelle l'API France Travail et retourne le JSON."""
    token = _get_token()
    if not token:
        return None

    try:
        resp = requests.get(
            API_URL,
            headers={"Authorization": f"Bearer {token}"},
            params={
                "motsCles":                keyword,
                "lieuTravail.departement": dept,
                "typeContrat":             TYPE_CONTRAT,
                "range":                   f"{start}-{min(start + 149, RESULTATS_MAX - 1)}",
                "sort":                    "1",  # tri par date
            },
            timeout=15,
        )

        if resp.status_code == 206:  # résultats partiels = normal
            return resp.json()
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 204:  # no content
            return {"resultats": []}

        print(f"   ⚠️  France Travail status {resp.status_code} — {resp.text[:100]}")
        return None

    except Exception as e:
        print(f"   ❌ France Travail requête : {e}")
        return None


def parser_offres(data: dict) -> list[dict]:
    """Parse les résultats de l'API France Travail."""
    offres = []
    for item in data.get("resultats", []):
        try:
            id_offre = item.get("id", "")
            if not id_offre:
                continue

            url = f"https://www.francetravail.fr/offres/recherche/detail/{id_offre}"

            lieu = item.get("lieuTravail", {})
            offres.append({
                "source":           "france_travail",
                "url":              url,
                "titre":            item.get("intitule", ""),
                "entreprise":       item.get("entreprise", {}).get("nom", ""),
                "localisation":     lieu.get("libelle", ""),
                "description":      item.get("description", "")[:1000],
                "date_publication": item.get("dateCreation", ""),
                "score_pertinence": 0.0,
            })
        except Exception:
            continue
    return offres


# ────────────────────────────────────────────────
# SCRAPER PRINCIPAL
# ────────────────────────────────────────────────

def scraper_france_travail() -> int:
    """
    Lance le scraping France Travail sur tous les mots-clés et départements IDF.
    Retourne le nombre de nouvelles offres ajoutées.
    """
    if not CLIENT_ID or not CLIENT_SECRET:
        print("⚠️  France Travail : variables CLIENT_ID/SECRET manquantes — scraper désactivé")
        return 0

    mem = Memory()
    total_nouvelles = 0

    for mot_cle in MOTS_CLES:
        for dept in DEPTS_IDF:
            print(f"\n🔍 France Travail : '{mot_cle}' dept {dept}...")
            data = fetch_offres(mot_cle, dept)
            if not data:
                continue

            offres = parser_offres(data)
            nb_total = data.get("Content-Range", len(offres))
            print(f"   → {len(offres)} offres récupérées")

            nouvelles = 0
            for offre in offres:
                if not offre["titre"] or mem.offre_existe(offre["url"]):
                    continue
                oid = mem.add_offre(offre)
                if oid:
                    nouvelles += 1
                    total_nouvelles += 1
                    print(f"   ➕ {offre['titre']} — {offre['entreprise']}")

            print(f"   ✅ {nouvelles} nouvelles")
            time.sleep(PAUSE)

        time.sleep(PAUSE)

    print(f"\n✅ France Travail terminé — {total_nouvelles} nouvelles offres ajoutées.")
    return total_nouvelles


# ────────────────────────────────────────────────
# LANCEMENT
# ────────────────────────────────────────────────

if __name__ == "__main__":
    scraper_france_travail()
