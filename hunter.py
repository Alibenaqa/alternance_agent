"""
hunter.py — Trouve les emails RH d'une entreprise
Stratégie :
  1. Pattern guessing + validation SMTP (gratuit, sans API)
  2. Apollo.io fallback (50 crédits/mois gratuits)
  3. Hunter.io en dernier recours (si crédits dispo)
"""

import os
import smtplib
import socket
import requests

HUNTER_API_KEY = os.environ.get("HUNTER_API_KEY", "25432bcf023d8760f920b39e8f4a3e96d8ef02cb")
APOLLO_API_KEY = os.environ.get("APOLLO_API_KEY", "")
BASE_URL = "https://api.hunter.io/v2"

PREFIXES_RH = [
    "recrutement", "rh", "hr", "recruitment", "talent", "careers",
    "emploi", "jobs", "drh", "people", "hiring",
]


# ─────────────────────────────────────────────────────
# OPTION 1 : Pattern guessing + validation SMTP
# ─────────────────────────────────────────────────────

def _smtp_check(email: str) -> bool:
    """
    Vérifie qu'un email existe via SMTP (RCPT TO) sans envoyer de message.
    Connexion au MX du domaine, envoi EHLO + MAIL FROM + RCPT TO.
    Retourne True si le serveur répond 250 (valide) ou 'accept_all'.
    """
    domaine = email.split("@")[1]
    try:
        # Trouve le serveur MX via DNS (fallback sur le domaine directement)
        mx = _get_mx(domaine)
        if not mx:
            return False

        with smtplib.SMTP(timeout=6) as smtp:
            smtp.connect(mx, 25)
            smtp.ehlo("alternance-agent.fr")
            smtp.mail("noreply@alternance-agent.fr")
            code, _ = smtp.rcpt(email)
            return code == 250

    except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected,
            socket.timeout, ConnectionRefusedError, OSError):
        # Serveur inaccessible → on ne peut pas valider, on retourne False
        return False
    except Exception:
        return False


def _get_mx(domaine: str) -> str | None:
    """Récupère l'enregistrement MX du domaine via DNS."""
    try:
        import dns.resolver
        records = dns.resolver.resolve(domaine, "MX")
        mx = sorted(records, key=lambda r: r.preference)[0].exchange.to_text().rstrip(".")
        return mx
    except Exception:
        # dnspython pas installé ou pas de MX → utilise le domaine directement
        return domaine


def _pattern_guess(domaine: str) -> dict | None:
    """
    Essaie les préfixes RH courants sur le domaine et valide via SMTP.
    Retourne le premier email validé, ou None si aucun ne passe.
    """
    for prefix in PREFIXES_RH:
        email = f"{prefix}@{domaine}"
        if _smtp_check(email):
            print(f"   ✅ Pattern SMTP validé : {email}")
            return {
                "email": email,
                "nom": "",
                "confiance": 60,
                "domaine": domaine,
                "source": "pattern_smtp",
            }
    return None


# ─────────────────────────────────────────────────────
# OPTION 2 : Apollo.io
# ─────────────────────────────────────────────────────

def _apollo_search(domaine: str) -> dict | None:
    """
    Cherche un email RH via Apollo.io People Search.
    Filtre par titre RH/recrutement sur le domaine de l'entreprise.
    Plan gratuit : 50 révélations d'emails/mois.
    """
    if not APOLLO_API_KEY:
        return None

    try:
        # Recherche les personnes RH dans l'entreprise
        resp = requests.post(
            "https://api.apollo.io/v1/mixed_people/search",
            json={
                "person_titles": [
                    "recruteur", "recruiter", "talent acquisition",
                    "rh", "hr", "chro", "drh", "people",
                    "talent manager", "hiring manager",
                ],
                "q_organization_domains": [domaine],
                "per_page": 5,
            },
            headers={
                "X-Api-Key": APOLLO_API_KEY,
                "Content-Type": "application/json",
            },
            timeout=10,
        )

        if resp.status_code != 200:
            return None

        people = resp.json().get("people", [])
        for person in people:
            email = person.get("email")
            if email and "@" in email:
                prenom = person.get("first_name", "")
                nom    = person.get("last_name", "")
                print(f"   ✅ Apollo email trouvé : {email} ({prenom} {nom})")
                return {
                    "email": email,
                    "nom": f"{prenom} {nom}".strip(),
                    "confiance": 75,
                    "domaine": domaine,
                    "source": "apollo",
                }

    except Exception as e:
        print(f"   ⚠️ Apollo erreur : {e}")

    return None


# ─────────────────────────────────────────────────────
# OPTION 3 : Hunter.io (si crédits disponibles)
# ─────────────────────────────────────────────────────

def _domain_search(domaine: str) -> dict | None:
    """Appelle Hunter domain-search pour un domaine."""
    try:
        resp = requests.get(
            f"{BASE_URL}/domain-search",
            params={
                "domain": domaine,
                "api_key": HUNTER_API_KEY,
                "limit": 20,
                "type": "personal",
                "department": "human resources",
            },
            timeout=10,
        )
        data = resp.json().get("data", {})

        # Détecte épuisement des crédits Hunter
        errors = resp.json().get("errors", [])
        if any("quota" in str(e).lower() or "limit" in str(e).lower() for e in errors):
            print("   ⚠️ Hunter crédits épuisés")
            return None

        emails = data.get("emails", [])
        if not emails:
            return None

        mots_rh_forts  = ["rh", "hr", "recrutement", "recruitment", "talent", "people", "drh", "chro"]
        mots_rh_larges = ["careers", "emploi", "jobs", "hiring", "staffing", "people ops"]
        mots_exclus    = ["ceo", "cto", "coo", "cfo", "directeur", "director", "president",
                          "commercial", "sales", "marketing", "finance", "comptable", "juridique",
                          "legal", "communication", "it ", "dev", "engineer", "data", "tech"]

        candidats_rh = []
        for email_info in emails:
            nom_dep  = (email_info.get("department") or "").lower()
            position = (email_info.get("position") or "").lower()
            adresse  = (email_info.get("value") or "").lower()
            texte    = f"{nom_dep} {position} {adresse}"

            if any(m in texte for m in mots_exclus):
                continue

            score_rh = 0
            if any(m in texte for m in mots_rh_forts):
                score_rh = 2
            elif any(m in texte for m in mots_rh_larges):
                score_rh = 1

            if score_rh > 0:
                candidats_rh.append({
                    "email": email_info["value"],
                    "nom": f"{email_info.get('first_name', '')} {email_info.get('last_name', '')}".strip(),
                    "confiance": email_info.get("confidence", 0),
                    "domaine": domaine,
                    "source": "hunter",
                    "_score_rh": score_rh,
                })

        if not candidats_rh:
            return None

        candidats_rh.sort(key=lambda x: (x["_score_rh"], x["confiance"]), reverse=True)
        meilleur = candidats_rh[0]
        meilleur.pop("_score_rh")
        return meilleur

    except Exception:
        return None


# ─────────────────────────────────────────────────────
# FONCTION PRINCIPALE
# ─────────────────────────────────────────────────────

def trouver_email_recruteur(entreprise: str, domaine: str = None) -> dict | None:
    """
    Cherche l'email RH/recrutement d'une entreprise.
    Retourne {"email": ..., "confiance": ..., "nom": ..., "source": ...} ou None.

    Stratégie :
      1. Trouver le domaine
      2. Pattern guessing + SMTP (gratuit)
      3. Apollo.io (50 crédits/mois gratuits)
      4. Hunter.io (si crédits disponibles)
    """
    # Étape 1 : domaine
    if not domaine:
        domaine = trouver_domaine(entreprise)
    if not domaine:
        return None

    print(f"   🔍 Domaine : {domaine}")

    # Étape 2 : pattern guessing SMTP
    result = _pattern_guess(domaine)
    if result:
        return result

    # Variante TLD (.fr ↔ .com)
    alt = None
    if domaine.endswith(".fr"):
        alt = domaine[:-3] + ".com"
    elif domaine.endswith(".com"):
        alt = domaine[:-4] + ".fr"

    if alt:
        result = _pattern_guess(alt)
        if result:
            return result

    # Étape 3 : Apollo.io
    result = _apollo_search(domaine)
    if result:
        return result
    if alt:
        result = _apollo_search(alt)
        if result:
            return result

    # Étape 4 : Hunter.io (dernier recours)
    result = _domain_search(domaine)
    if result:
        return result
    if alt:
        result = _domain_search(alt)
        if result:
            return result

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

    import re as _re
    mots_supprimer = ["france", "group", "groupe", "sas", "sa", "sarl", "srl",
                      "inc", "llc", "ltd", "corp", "gmbh", "ag", "nv"]
    mots = nom.split()
    mots_filtres = [m for m in mots if m not in mots_supprimer and len(m) > 1]
    base = mots_filtres[0] if mots_filtres else mots[0] if mots else nom
    base = _re.sub(r"[^a-z0-9]", "", base)

    if base:
        return f"{base}.fr"
    return None


def verifier_email(email: str) -> bool:
    """Vérifie qu'un email est valide (SMTP ou Hunter)."""
    # Essaie d'abord SMTP (gratuit)
    if _smtp_check(email):
        return True
    # Fallback Hunter
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
    entreprises = ["BoursoBank", "Capgemini", "GRDF", "Doctolib"]
    for e in entreprises:
        print(f"\n🔍 {e}...")
        result = trouver_email_recruteur(e)
        if result:
            print(f"   ✅ {result['email']} ({result['nom']}) — confiance {result['confiance']}% — source: {result.get('source')}")
        else:
            print(f"   ❌ Aucun email trouvé")
