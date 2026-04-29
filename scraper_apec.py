"""
scraper_apec.py — API APEC (Association Pour l'Emploi des Cadres)
Offres de qualité, beaucoup de postes data/IA en alternance.

Usage:
    python scraper_apec.py
"""

import requests

# ────────────────────────────────────────────────
# CONFIGURATION
# ────────────────────────────────────────────────

# API interne APEC (non officielle mais stable)
SEARCH_URL = "https://www.apec.fr/cms/webservices/rechercheOffre/results"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.apec.fr/candidat/recherche-emploi.html",
    "Origin":  "https://www.apec.fr",
}

MOTS_CLES = [
    "Data Analyst alternance",
    "Data Scientist alternance",
    "Data Engineer alternance",
    "Machine Learning alternance",
    "Développeur IA alternance",
    "AI Engineer alternance",
    "MLOps alternance",
    "Développeur Full Stack alternance",
    "Business Intelligence alternance",
]

# Codes contrat APEC : 204 = Alternance/Apprentissage
# Codes niveau : 634 = Bac+3/4, 631 = Bac+2
PARAMS_BASE = {
    "typesCodification":  "NORMAL",
    "selectedContrats":   "204",
    "selectedNiveaux":    "634,631",
    "nbParPage":          30,
    "tri":                1,        # tri par date
    "debut":              0,
}

PAGES_MAX = 3   # max pages par mot-clé (30 offres/page → 90 max)

PAUSE = 2


# ────────────────────────────────────────────────
# FONCTIONS
# ────────────────────────────────────────────────

def fetch_page(keyword: str, debut: int = 0) -> dict | None:
    """Appelle l'API APEC et retourne le JSON."""
    params = {**PARAMS_BASE, "motsCles": keyword, "debut": debut}
    try:
        resp = requests.get(SEARCH_URL, headers=HEADERS, params=params, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        print(f"   ⚠️  APEC status {resp.status_code} pour '{keyword}'")
        return None
    except Exception as e:
        print(f"   ❌ APEC erreur : {e}")
        return None


def parser_offres(data: dict) -> list[dict]:
    """Parse les résultats APEC."""
    offres = []
    for item in data.get("resultats", []):
        try:
            num = item.get("numeroOffre", "")
            if not num:
                continue

            url = f"https://www.apec.fr/candidat/recherche-emploi.html/emploi/{num}"

            lieu = item.get("lieuTravail", {})
            localisation = lieu.get("libelle", "") if isinstance(lieu, dict) else str(lieu)

            offres.append({
                "source":           "apec",
                "url":              url,
                "titre":            item.get("intitule", ""),
                "entreprise":       item.get("nomEntreprise", ""),
                "localisation":     localisation,
                "description":      item.get("texteHtml", "")[:1000] if item.get("texteHtml") else "",
                "date_publication": item.get("datePublication", ""),
                "score_pertinence": 0.0,
            })
        except Exception:
            continue
    return offres


def scraper_apec() -> int:
    """
    API APEC /cms/webservices/rechercheOffre/results — retourne 404 depuis 2025.
    Désactivé jusqu'à trouver le nouveau endpoint.
    """
    print("⚠️  APEC : API /cms/webservices supprimée — scraper désactivé")
    return 0


# ────────────────────────────────────────────────
# LANCEMENT
# ────────────────────────────────────────────────

if __name__ == "__main__":
    scraper_apec()
