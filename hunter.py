"""
hunter.py — Trouve les emails RH d'une entreprise via Hunter.io API
"""

import os
import requests

HUNTER_API_KEY = os.environ.get("HUNTER_API_KEY", "25432bcf023d8760f920b39e8f4a3e96d8ef02cb")
BASE_URL = "https://api.hunter.io/v2"


def _domain_search(domaine: str) -> dict | None:
    """Appelle Hunter domain-search pour un domaine. Retourne le meilleur email ou None."""
    try:
        resp = requests.get(
            f"{BASE_URL}/domain-search",
            params={
                "domain": domaine,
                "api_key": HUNTER_API_KEY,
                "limit": 10,
                "type": "personal",
            },
            timeout=10,
        )
        data = resp.json().get("data", {})
        emails = data.get("emails", [])
        if not emails:
            return None

        mots_rh = ["rh", "hr", "recrutement", "recruitment", "talent", "people", "careers", "emploi", "jobs"]
        for email_info in emails:
            nom_dep = (email_info.get("department") or "").lower()
            position = (email_info.get("position") or "").lower()
            adresse = (email_info.get("value") or "").lower()
            if any(m in nom_dep or m in position or m in adresse for m in mots_rh):
                return {
                    "email": email_info["value"],
                    "nom": f"{email_info.get('first_name', '')} {email_info.get('last_name', '')}".strip(),
                    "confiance": email_info.get("confidence", 0),
                    "domaine": domaine,
                }
        meilleur = max(emails, key=lambda e: e.get("confidence", 0))
        return {
            "email": meilleur["value"],
            "nom": f"{meilleur.get('first_name', '')} {meilleur.get('last_name', '')}".strip(),
            "confiance": meilleur.get("confidence", 0),
            "domaine": domaine,
        }
    except Exception:
        return None


def trouver_email_recruteur(entreprise: str, domaine: str = None) -> dict | None:
    """
    Cherche l'email RH/recrutement d'une entreprise.
    Retourne {"email": ..., "confiance": ..., "nom": ...} ou None.
    Stratégie : domain-search .fr → domain-search .com → adresses génériques RH
    """
    # Étape 1 : trouver le domaine si pas fourni
    if not domaine:
        domaine = trouver_domaine(entreprise)
    if not domaine:
        return None

    # Étape 2 : domain-search sur le domaine trouvé
    result = _domain_search(domaine)
    if result:
        return result

    # Étape 3 : si le domaine est .fr, essayer aussi .com (et vice versa)
    if domaine.endswith(".fr"):
        alt = domaine[:-3] + ".com"
    elif domaine.endswith(".com"):
        alt = domaine[:-4] + ".fr"
    else:
        alt = None

    if alt:
        result = _domain_search(alt)
        if result:
            return result
        domaine = alt  # utilise l'alt pour la suite

    # Étape 4 : essayer des adresses RH génériques via email-verifier
    prefixes_rh = ["recrutement", "rh", "emploi", "jobs", "careers", "talent"]
    for prefix in prefixes_rh:
        email_test = f"{prefix}@{domaine}"
        try:
            resp = requests.get(
                f"{BASE_URL}/email-verifier",
                params={"email": email_test, "api_key": HUNTER_API_KEY},
                timeout=10,
            )
            statut = resp.json().get("data", {}).get("status", "")
            if statut in ("valid", "accept_all"):
                print(f"   ✅ Email générique trouvé : {email_test}")
                return {
                    "email": email_test,
                    "nom": "",
                    "confiance": 50,
                    "domaine": domaine,
                }
        except Exception:
            continue

    return None


def trouver_domaine(entreprise: str) -> str | None:
    """Devine le domaine web d'une entreprise."""
    DOMAINES_CONNUS = {
        "capgemini": "capgemini.com",
        "sopra": "soprasteria.com",
        "sopra steria": "soprasteria.com",
        "accenture": "accenture.com",
        "thales": "thalesgroup.com",
        "bnp paribas": "bnpparibas.com",
        "bnpparibas": "bnpparibas.com",
        "société générale": "societegenerale.com",
        "societe generale": "societegenerale.com",
        "axa": "axa.com",
        "allianz": "allianz.fr",
        "grdf": "grdf.fr",
        "edf": "edf.fr",
        "orange": "orange.com",
        "sncf": "sncf.com",
        "airbus": "airbus.com",
        "dassault": "dassault-systemes.com",
        "michelin": "michelin.com",
        "total": "totalenergies.com",
        "totalenergies": "totalenergies.com",
        "lvmh": "lvmh.com",
        "l'oréal": "loreal.com",
        "loreal": "loreal.com",
        "danone": "danone.com",
        "sanofi": "sanofi.com",
        "boursobank": "boursobank.com",
        "bforbank": "bforbank.com",
        "canal+": "canalplus.com",
        "canal plus": "canalplus.com",
        "chanel": "chanel.com",
        "hermes": "hermes.com",
        "hermès": "hermes.com",
        "lacoste": "lacoste.com",
        "dior": "dior.com",
        "christian dior": "dior.com",
        "volkswagen": "vwfs.fr",
        "samsung": "samsung.com",
        "servier": "servier.com",
        "bpce": "bpce.fr",
        "klesia": "klesia.fr",
        "sogeti": "sogeti.fr",
        "upsa": "upsa.fr",
        "aon": "aon.com",
        "natixis": "natixis.com",
        "cgi": "cgi.com",
        "kpmg": "kpmg.fr",
        "deloitte": "deloitte.fr",
        "pwc": "pwc.fr",
        "ey": "ey.com",
        "mazars": "mazars.fr",
        "sia partners": "sia-partners.com",
        "wavestone": "wavestone.com",
        "onepoint": "groupeonepoint.com",
        "manpower": "manpower.fr",
        "randstad": "randstad.fr",
        "adecco": "adecco.fr",
        "michael page": "michaelpage.fr",
        "hays": "hays.fr",
        "safran": "safran-group.com",
        "schneider": "se.com",
        "schneider electric": "se.com",
        "renault": "renault.com",
        "peugeot": "stellantis.com",
        "stellantis": "stellantis.com",
        "bouygues": "bouygues.com",
        "vinci": "vinci.com",
        "saint-gobain": "saint-gobain.com",
        "saint gobain": "saint-gobain.com",
        "engie": "engie.com",
        "veolia": "veolia.com",
        "suez": "suez.com",
        "ibm": "ibm.com",
        "microsoft": "microsoft.com",
        "google": "google.com",
        "meta": "meta.com",
        "amazon": "amazon.fr",
        "aws": "amazon.com",
        "datadog": "datadoghq.com",
        "confluent": "confluent.io",
        "snowflake": "snowflake.com",
        "databricks": "databricks.com",
        "sap": "sap.com",
        "oracle": "oracle.com",
        "salesforce": "salesforce.com",
        "malt": "malt.com",
        "doctolib": "doctolib.fr",
        "alan": "alan.com",
        "qonto": "qonto.com",
        "payfit": "payfit.com",
        "contentsquare": "contentsquare.com",
        "leboncoin": "leboncoin.fr",
        "cdiscount": "cdiscount.com",
        "fnac": "fnacdarty.com",
        "decathlon": "decathlon.com",
        "maif": "maif.fr",
        "credit agricole": "credit-agricole.com",
        "crédit agricole": "credit-agricole.com",
        "ca": "credit-agricole.com",
        "lcl": "lcl.fr",
        "la poste": "laposte.fr",
        "laposte": "laposte.fr",
        "in extenso": "inextenso.fr",
    }

    nom = entreprise.lower().strip()
    for cle, domaine in DOMAINES_CONNUS.items():
        if cle in nom or nom in cle:
            return domaine

    # Fallback intelligent : nettoie le nom et génère plusieurs variantes
    import re as _re
    # Supprime les mots génériques et les formes juridiques
    mots_supprimer = ["france", "group", "groupe", "sas", "sa", "sarl", "srl",
                      "inc", "llc", "ltd", "corp", "gmbh", "ag", "nv"]
    mots = nom.split()
    mots_filtres = [m for m in mots if m not in mots_supprimer and len(m) > 1]
    base = mots_filtres[0] if mots_filtres else mots[0] if mots else nom
    base = _re.sub(r"[^a-z0-9]", "", base)

    if base:
        return f"{base}.fr"  # préfère .fr pour les entreprises françaises
    return None


def verifier_email(email: str) -> bool:
    """Vérifie qu'un email est valide avant d'envoyer."""
    try:
        resp = requests.get(
            f"{BASE_URL}/email-verifier",
            params={"email": email, "api_key": HUNTER_API_KEY},
            timeout=10,
        )
        statut = resp.json().get("data", {}).get("status", "")
        return statut in ("valid", "accept_all")
    except Exception:
        return True  # en cas d'erreur, on tente quand même


if __name__ == "__main__":
    # Test rapide
    entreprises = ["BoursoBank", "Capgemini", "GRDF"]
    for e in entreprises:
        print(f"\n🔍 {e}...")
        result = trouver_email_recruteur(e)
        if result:
            print(f"   ✅ {result['email']} ({result['nom']}) — confiance {result['confiance']}%")
        else:
            print(f"   ❌ Aucun email trouvé")
