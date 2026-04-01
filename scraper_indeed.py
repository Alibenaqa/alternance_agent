"""
scraper_indeed.py — Scraper Indeed France (HTML)
Cherche les offres d'alternance data/IA sur Indeed et les sauvegarde en base.

Usage:
    python scraper_indeed.py
"""

import time
import re
import requests
from bs4 import BeautifulSoup
from memory import Memory

# ────────────────────────────────────────────────
# CONFIGURATION
# ────────────────────────────────────────────────

BASE_URL = "https://fr.indeed.com/jobs"

MOTS_CLES = [
    "Data Analyst alternance",
    "Data Scientist alternance",
    "Data Engineer alternance",
    "Machine Learning alternance",
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
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

PAUSE        = 4    # secondes entre requêtes
OFFRES_MAX   = 40   # résultats par mot-clé (Indeed pagine par 10)


# ────────────────────────────────────────────────
# FONCTIONS
# ────────────────────────────────────────────────

def fetch_page(keyword: str, start: int = 0) -> str | None:
    """Récupère une page de résultats Indeed."""
    params = {
        "q":       keyword,
        "l":       "Paris, Île-de-France",
        "sort":    "date",
        "fromage": "30",       # 30 derniers jours
        "start":   start,
    }
    try:
        resp = requests.get(BASE_URL, headers=HEADERS, params=params, timeout=15)
        if resp.status_code == 200:
            return resp.text
        print(f"   ⚠️  Indeed status {resp.status_code} pour '{keyword}' (start={start})")
        return None
    except requests.RequestException as e:
        print(f"   ❌ Erreur réseau Indeed : {e}")
        return None


def parser_offres(html: str) -> list[dict]:
    """Parse le HTML Indeed et extrait les offres."""
    soup = BeautifulSoup(html, "html.parser")
    offres = []

    # Cherche les cartes offres (plusieurs sélecteurs pour gérer les changements HTML)
    cards = (
        soup.find_all("li", class_=re.compile(r"css-.*")) or
        soup.find_all("div", attrs={"data-jk": True}) or
        soup.find_all("div", class_=re.compile(r"job_seen_beacon"))
    )

    # Fallback : cherche tous les éléments avec data-jk
    if not cards:
        cards = soup.find_all(attrs={"data-jk": True})

    for card in cards:
        try:
            # Job ID (pour construire l'URL)
            job_id = card.get("data-jk") or ""
            if not job_id:
                # Cherche dans les enfants
                el = card.find(attrs={"data-jk": True})
                job_id = el.get("data-jk", "") if el else ""

            if not job_id:
                continue

            url = f"https://fr.indeed.com/viewjob?jk={job_id}"

            # Titre
            titre_el = (
                card.find("h2", class_=re.compile(r"jobTitle")) or
                card.find("a", attrs={"data-jk": job_id}) or
                card.find("span", attrs={"title": True})
            )
            if titre_el:
                span = titre_el.find("span", attrs={"title": True})
                titre = span.get("title") if span else titre_el.get_text(strip=True)
            else:
                titre = ""

            if not titre:
                continue

            # Entreprise
            entreprise_el = (
                card.find("span", attrs={"data-testid": "company-name"}) or
                card.find("span", class_=re.compile(r"companyName")) or
                card.find("a", attrs={"data-tn-element": "companyName"})
            )
            entreprise = entreprise_el.get_text(strip=True) if entreprise_el else ""

            # Localisation
            lieu_el = (
                card.find("div", attrs={"data-testid": "text-location"}) or
                card.find("div", class_=re.compile(r"companyLocation"))
            )
            localisation = lieu_el.get_text(strip=True) if lieu_el else "Paris"

            # Description courte
            desc_el = card.find("div", class_=re.compile(r"underShelfFooter|job-snippet"))
            description = desc_el.get_text(strip=True) if desc_el else ""

            offres.append({
                "source":          "indeed",
                "url":             url,
                "titre":           titre,
                "entreprise":      entreprise,
                "localisation":    localisation,
                "description":     description,
                "date_publication": "",
                "score_pertinence": 0.0,
            })

        except Exception:
            continue

    return offres


def scraper_indeed() -> int:
    """
    Lance le scraping Indeed sur tous les mots-clés.
    Retourne le nombre de nouvelles offres ajoutées.
    """
    mem = Memory()
    total_nouvelles = 0

    for mot_cle in MOTS_CLES:
        print(f"\n🔍 Indeed : '{mot_cle}'...")
        start = 0
        pages_vides = 0

        while start < OFFRES_MAX:
            html = fetch_page(mot_cle, start)
            if not html:
                break

            offres = parser_offres(html)
            if not offres:
                pages_vides += 1
                if pages_vides >= 2:
                    break
                time.sleep(PAUSE)
                continue

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

            if len(offres) < 10:
                break

            start += 10
            time.sleep(PAUSE)

        time.sleep(PAUSE)

    print(f"\n✅ Indeed terminé — {total_nouvelles} nouvelles offres ajoutées.")
    return total_nouvelles


# ────────────────────────────────────────────────
# LANCEMENT
# ────────────────────────────────────────────────

if __name__ == "__main__":
    scraper_indeed()
