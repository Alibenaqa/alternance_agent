"""
scraper_labonnealternance.py — API La Bonne Alternance (beta.gouv.fr)
API 100% gratuite, sans compte, dédiée à l'alternance en France.

Doc : https://labonnealternance.apprentissage.beta.gouv.fr/api/v1/docs
Usage:
    python scraper_labonnealternance.py
"""

import requests

# ────────────────────────────────────────────────
# CONFIGURATION
# ────────────────────────────────────────────────

BASE_URL = "https://labonnealternance.apprentissage.beta.gouv.fr/api/v1/jobs"

# Codes ROME pour les métiers data/IA/dev
# M1805 = Études et développement informatique
# M1811 = Responsable technique informatique (Data)
# M1810 = Production et exploitation SI
# M1803 = Direction des systèmes d'information
ROME_CODES = [
    "M1805",  # Études et développement info → Dev, Fullstack
    "M1811",  # Systèmes d'information → Data Engineer
    "M1810",  # Production SI
    "M1806",  # Conseil et MOA SI
]

# Paris (coordonnées + INSEE)
LATITUDE  = 48.8566
LONGITUDE = 2.3522
RAYON_KM  = 300
INSEE_PARIS = "75056"

PAUSE = 2  # secondes entre requêtes


# ────────────────────────────────────────────────
# FONCTIONS
# ────────────────────────────────────────────────

def fetch_offres(rome: str) -> list[dict]:
    """Récupère les offres d'alternance pour un code ROME via l'API LBA."""
    try:
        resp = requests.get(
            BASE_URL,
            params={
                "romes":      rome,
                "longitude":  LONGITUDE,
                "latitude":   LATITUDE,
                "radius":     RAYON_KM,
                "insee":      INSEE_PARIS,
                "sources":    "offres,matcha",   # offres PE + entreprises LBA
                "caller":     "alternance_agent_ali",
            },
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"   ⚠️  LBA status {resp.status_code} pour ROME {rome}")
            return []
        return resp.json()
    except Exception as e:
        print(f"   ❌ LBA erreur : {e}")
        return []


def parser_offres_pe(data: dict) -> list[dict]:
    """Parse les offres Pôle Emploi retournées par LBA."""
    offres = []
    for item in data.get("peJobs", {}).get("results", []):
        try:
            job = item.get("job", {})
            place = item.get("place", {})
            company = item.get("company", {})

            url = job.get("url") or f"https://labonnealternance.apprentissage.beta.gouv.fr/recherche-emploi?display=list&job={job.get('id', '')}"
            titre = job.get("title", "")
            if not titre or not url:
                continue

            offres.append({
                "source":           "labonnealternance",
                "url":              url,
                "titre":            titre,
                "entreprise":       company.get("name", ""),
                "localisation":     place.get("city", "Paris"),
                "description":      job.get("description", "")[:1000],
                "date_publication": job.get("creationDate", ""),
                "score_pertinence": 0.0,
            })
        except Exception:
            continue
    return offres


def parser_offres_matcha(data: dict) -> list[dict]:
    """Parse les offres Matcha (entreprises qui cherchent des alternants) retournées par LBA."""
    offres = []
    for item in data.get("matchas", {}).get("results", []):
        try:
            jobs = item.get("jobs", [{}])
            place = item.get("place", {})
            company = item.get("company", {})

            for job in jobs:
                url = f"https://labonnealternance.apprentissage.beta.gouv.fr/recherche-emploi?display=list&job={job.get('id', '')}"
                titre = job.get("title", "")
                if not titre:
                    continue

                offres.append({
                    "source":           "labonnealternance",
                    "url":              url,
                    "titre":            titre,
                    "entreprise":       company.get("name", ""),
                    "localisation":     place.get("city", "Paris"),
                    "description":      job.get("description", "")[:1000],
                    "date_publication": "",
                    "score_pertinence": 0.0,
                })
        except Exception:
            continue
    return offres


def scraper_labonnealternance() -> int:
    """
    API LBA (labonnealternance.apprentissage.beta.gouv.fr) — endpoint /api/v1/jobs supprimé.
    Remplacé par alternance.emploi.gouv.fr mais sans API publique documentée.
    Désactivé jusqu'à trouver le nouveau endpoint.
    """
    print("⚠️  La Bonne Alternance : API /api/v1/jobs supprimée — scraper désactivé")
    return 0


# ────────────────────────────────────────────────
# LANCEMENT
# ────────────────────────────────────────────────

if __name__ == "__main__":
    scraper_labonnealternance()
