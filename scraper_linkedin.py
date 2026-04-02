"""
scraper_linkedin.py — Scraper LinkedIn Jobs (sans compte)
Utilise l'endpoint public guest de LinkedIn pour récupérer les offres d'alternance.

Usage:
    python scraper_linkedin.py
"""

import time
import requests
from bs4 import BeautifulSoup
from memory import Memory

# ────────────────────────────────────────────────
# CONFIGURATION
# ────────────────────────────────────────────────

MOTS_CLES = [
    "Data Analyst alternance",
    "Data Scientist alternance",
    "Data Engineer alternance",
    "Machine Learning alternance",
    "AI Engineer alternance",
    "AI Developer alternance",
    "Développeur IA alternance",
    "MLOps alternance",
    "Développeur Full Stack alternance",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Endpoint public LinkedIn (pas besoin de compte)
BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

PAUSE = 3  # secondes entre requêtes
OFFRES_PAR_PAGE = 25


# ────────────────────────────────────────────────
# FONCTIONS
# ────────────────────────────────────────────────

def fetch_page(keyword: str, start: int = 0) -> str | None:
    """Récupère une page de résultats LinkedIn. Retourne le HTML ou None."""
    params = {
        "keywords": keyword,
        "location": "France",
        "f_TPR": "r2592000",  # 30 derniers jours
        "start": start,
    }
    try:
        resp = requests.get(BASE_URL, headers=HEADERS, params=params, timeout=15)
        if resp.status_code == 200:
            return resp.text
        print(f"   ⚠️  Status {resp.status_code} pour '{keyword}' (start={start})")
        return None
    except requests.RequestException as e:
        print(f"   ❌ Erreur réseau : {e}")
        return None


def parser_offres(html: str) -> list[dict]:
    """Parse le HTML LinkedIn et extrait les offres."""
    soup = BeautifulSoup(html, "html.parser")
    offres = []

    for card in soup.find_all("li"):
        try:
            # Titre
            titre_el = card.find("h3", class_="base-search-card__title")
            if not titre_el:
                continue
            titre = titre_el.get_text(strip=True)

            # Entreprise
            entreprise_el = card.find("h4", class_="base-search-card__subtitle")
            entreprise = entreprise_el.get_text(strip=True) if entreprise_el else ""

            # Localisation
            lieu_el = card.find("span", class_="job-search-card__location")
            localisation = lieu_el.get_text(strip=True) if lieu_el else ""

            # URL
            lien_el = card.find("a", class_="base-card__full-link")
            if not lien_el or not lien_el.get("href"):
                continue
            url = lien_el["href"].split("?")[0]  # Nettoie les paramètres tracking

            # Date
            date_el = card.find("time")
            date_pub = date_el.get("datetime", "") if date_el else ""

            offres.append({
                "source": "linkedin",
                "url": url,
                "titre": titre,
                "entreprise": entreprise,
                "localisation": localisation,
                "description": "",
                "date_publication": date_pub,
                "score_pertinence": 0.0,
            })
        except Exception:
            continue

    return offres


def scraper_linkedin() -> int:
    """
    Lance le scraping LinkedIn sur tous les mots-clés.
    Retourne le nombre de nouvelles offres ajoutées.
    """
    mem = Memory()
    total_nouvelles = 0

    for mot_cle in MOTS_CLES:
        print(f"\n🔍 LinkedIn : '{mot_cle}'...")
        start = 0
        pages_vides = 0

        while pages_vides < 2:
            html = fetch_page(mot_cle, start)
            if not html:
                break

            offres = parser_offres(html)
            if not offres:
                pages_vides += 1
                break

            nouvelles = 0
            for offre in offres:
                if mem.offre_existe(offre["url"]):
                    continue
                oid = mem.add_offre(offre)
                if oid:
                    nouvelles += 1
                    total_nouvelles += 1
                    print(f"   ➕ {offre['titre']} — {offre['entreprise']}")

            print(f"   📄 start={start} — {nouvelles} nouvelles / {len(offres)} offres")

            if len(offres) < OFFRES_PAR_PAGE:
                break

            start += OFFRES_PAR_PAGE
            time.sleep(PAUSE)

        time.sleep(PAUSE)

    print(f"\n✅ LinkedIn terminé — {total_nouvelles} nouvelles offres ajoutées.")
    mem.print_dashboard()
    return total_nouvelles


# ────────────────────────────────────────────────
# LANCEMENT
# ────────────────────────────────────────────────

if __name__ == "__main__":
    scraper_linkedin()
