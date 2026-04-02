"""
scraper_wttj.py — Scraper Welcome to the Jungle via API Algolia
Cherche les offres d'alternance data/IA en France et les sauvegarde en base.

Usage:
    python scraper_wttj.py
"""

import requests
import time
from memory import Memory

# ────────────────────────────────────────────────
# CONFIGURATION ALGOLIA (clés publiques du site)
# ────────────────────────────────────────────────

ALGOLIA_APP_ID  = "CSEKHVMS53"
ALGOLIA_API_KEY = "4bd8f6215d0cc52b26430765769e65a0"
ALGOLIA_INDEX   = "wttj_jobs_production_fr"

ALGOLIA_URL = (
    f"https://{ALGOLIA_APP_ID.lower()}-dsn.algolia.net"
    f"/1/indexes/{ALGOLIA_INDEX}/query"
)

HEADERS = {
    "X-Algolia-Application-Id": ALGOLIA_APP_ID,
    "X-Algolia-API-Key": ALGOLIA_API_KEY,
    "Content-Type": "application/json",
    "Referer": "https://www.welcometothejungle.com/",
    "Origin": "https://www.welcometothejungle.com",
}

# Mots-clés à rechercher
MOTS_CLES = [
    "Data Analyst",
    "Data Scientist",
    "Data Engineer",
    "Machine Learning",
    "AI Engineer",
    "AI Developer",
    "Développeur IA",
    "Business Intelligence",
    "MLOps",
    "Développeur Full Stack",
    "Développeur Web",
]

# Mobilité France entière
VILLES_CIBLES = None  # None = pas de filtre géographique

HITS_PAR_PAGE   = 50
PAUSE_REQUETES  = 1.5  # secondes entre chaque requête


# ────────────────────────────────────────────────
# FONCTIONS
# ────────────────────────────────────────────────

def fetch_page(keyword: str, page: int = 0) -> dict:
    """Interroge Algolia et retourne le JSON brut d'une page de résultats."""
    body = {
        "query": keyword,
        "page": page,
        "hitsPerPage": HITS_PAR_PAGE,
        "filters": "contract_type:apprenticeship",
    }
    response = requests.post(ALGOLIA_URL, headers=HEADERS, json=body, timeout=15)
    response.raise_for_status()
    return response.json()


def parser_offre(hit: dict) -> dict:
    """Extrait les champs utiles d'un résultat Algolia WTTJ."""
    offices = hit.get("offices") or []
    ville = offices[0].get("city", "") if offices else ""

    return {
        "source": "wttj",
        "url": f"https://www.welcometothejungle.com/fr/companies/{hit.get('organization', {}).get('slug', '')}/jobs/{hit.get('slug', '')}",
        "titre": hit.get("name", ""),
        "entreprise": hit.get("organization", {}).get("name", ""),
        "localisation": ville,
        "description": hit.get("description", ""),
        "date_publication": hit.get("published_at", ""),
        "score_pertinence": 0.0,
    }


def est_en_france(offre: dict) -> bool:
    """Retourne True — mobilité France entière acceptée."""
    return True


def scraper_wttj() -> int:
    """
    Lance le scraping sur tous les mots-clés.
    Retourne le nombre de nouvelles offres ajoutées en base.
    """
    mem = Memory()
    total_nouvelles = 0

    for mot_cle in MOTS_CLES:
        print(f"\n🔍 Recherche : '{mot_cle}'...")
        page = 0

        while True:
            try:
                data = fetch_page(mot_cle, page)
            except requests.HTTPError as e:
                print(f"   ❌ Erreur HTTP : {e}")
                break
            except requests.RequestException as e:
                print(f"   ❌ Erreur réseau : {e}")
                break

            hits = data.get("hits", [])
            nb_pages = data.get("nbPages", 1)

            if not hits:
                break

            nouvelles_cette_page = 0
            for hit in hits:
                offre = parser_offre(hit)

                # Filtre géographique

                # Dédoublonnage
                if not offre["url"] or mem.offre_existe(offre["url"]):
                    continue

                oid = mem.add_offre(offre)
                if oid:
                    nouvelles_cette_page += 1
                    total_nouvelles += 1
                    print(f"   ➕ {offre['titre']} — {offre['entreprise']} ({offre['localisation']})")

            print(f"   📄 Page {page + 1}/{nb_pages} — {nouvelles_cette_page} nouvelles")

            if page + 1 >= nb_pages:
                break

            page += 1
            time.sleep(PAUSE_REQUETES)

        time.sleep(PAUSE_REQUETES)

    print(f"\n✅ Scraping terminé — {total_nouvelles} nouvelles offres ajoutées.")
    mem.print_dashboard()
    return total_nouvelles


# ────────────────────────────────────────────────
# LANCEMENT
# ────────────────────────────────────────────────

if __name__ == "__main__":
    scraper_wttj()
