"""
scorer.py — Scoring des offres d'alternance par Claude
Lit les offres 'nouveau' en base, leur donne un score 0.0-1.0 et met à jour le statut.

Usage:
    python scorer.py
"""

import json
import os
import time
from pathlib import Path

import anthropic
from memory import Memory

# ────────────────────────────────────────────────
# CONFIGURATION
# ────────────────────────────────────────────────

PROFIL_PATH = Path(__file__).parent / "profil_ali.json"
SCORE_MIN_INTERESSANT = 0.65   # en dessous → 'ignoré', au dessus → 'intéressant'
PAUSE_ENTRE_APPELS    = 0.5    # secondes entre chaque appel API
BATCH_SIZE            = 50     # nombre max d'offres à scorer par lancement


# ────────────────────────────────────────────────
# CHARGEMENT DU PROFIL
# ────────────────────────────────────────────────

def charger_profil() -> dict:
    with open(PROFIL_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def resumer_profil(profil: dict) -> str:
    """Génère un résumé court du profil pour le prompt Claude."""
    r = profil["recherche_alternance"]
    return f"""
Candidat : {profil['identite']['prenom']} {profil['identite']['nom']}
Formation : Bachelor Data & IA — Hetic Montreuil (2e année, 3e année dès sept. 2026)
Niveau actuel : Bac+2 | Sera en Bac+3 dès septembre 2026
Début alternance : {r['disponibilite']} | Durée : {r['duree_contrat']} | Rythme : 3j entreprise / 2j école
Postes ciblés : {', '.join(r['poste_cible'])}
Mobilité : France entière, télétravail/hybride préféré
Compétences : Python, SQL, Power BI, ETL, JavaScript, Node.js, React, PHP, MySQL, PostgreSQL, MongoDB, Git, Docker (bases), Make, ChatGPT API, Claude API
Expériences : Data Analyst freelance Techwin Services (ETL Python), Reporting Analyst stage Mamda Assurance (Power BI/PHP), Data Analyst BNC Corporation (KPI/EViews)
Projets : Alternance Agent (Python/Claude API/Railway/Telegram), AniData Lab (ETL/Airflow/ELK/Docker), Dream Interpreter (LLM/Whisper/Stable Diffusion), Data Refinement (Pandas/Jupyter), Jeu de dames (Python/Pygame/OOP)
Langues : Français bilingue, Anglais B2/C1, Espagnol A1/A2
NOTE : Les offres demandant Bac+3 minimum sont PRIORITAIRES car Ali sera en Bac+3 dès sept. 2026
""".strip()


# ────────────────────────────────────────────────
# SCORING
# ────────────────────────────────────────────────

PROMPT_SYSTEME = """Tu es un assistant de recherche d'emploi.
Tu dois évaluer si une offre d'alternance correspond au profil d'un candidat.
Tu réponds UNIQUEMENT en JSON valide, sans texte autour."""

def construire_prompt(offre: dict, resume_profil: str) -> str:
    return f"""Évalue cette offre d'alternance pour ce candidat.

=== PROFIL CANDIDAT ===
{resume_profil}

=== OFFRE ===
Titre : {offre['titre']}
Entreprise : {offre['entreprise']}
Localisation : {offre['localisation']}
Description : {offre['description'][:1500] if offre['description'] else 'Non disponible'}

=== TÂCHE ===
Donne un score de pertinence entre 0.0 et 1.0 selon ces critères :
- 0.9-1.0 : Parfaitement aligné (poste data/IA/dev/ML, n'importe quelle ville France, alternance Bac+3 ou ouvert)
- 0.7-0.8 : Très bon match (poste proche, quelques différences mineures)
- 0.5-0.6 : Match moyen (poste connexe, domaine adjacent)
- 0.0-0.4 : Mauvais match (hors domaine data/IA/dev, trop senior, ou pas alternance)

BONUS +0.05 : si l'offre mentionne explicitement Bac+3 ou Master 1 (Ali sera en Bac+3 (3e année Bachelor) dès sept. 2026)
BONUS +0.05 : si l'offre mentionne télétravail, remote, ou hybride
MALUS -0.1 : si l'offre exige Bac+4/5 ou Master 2 minimum
MALUS -0.15 : si ce n'est PAS une alternance (CDI/CDD/stage sauf si titre du poste le confirme clairement)
MALUS -0.2 : si le poste est hors domaine (comptabilité, marketing, juridique, RH non-data, etc.)

Réponds en JSON :
{{
  "score": 0.0,
  "raison": "explication courte en 1 phrase"
}}"""


def scorer_offre(client: anthropic.Anthropic, offre: dict, resume_profil: str) -> tuple[float, str]:
    """Appelle Claude pour scorer une offre. Retourne (score, raison)."""
    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            system=PROMPT_SYSTEME,
            messages=[
                {"role": "user", "content": construire_prompt(offre, resume_profil)}
            ],
        )
        raw = message.content[0].text.strip()
        # Enlève les balises markdown si présentes (```json ... ```)
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw.strip())
        score = float(result.get("score", 0.0))
        raison = result.get("raison", "")
        return max(0.0, min(1.0, score)), raison

    except (json.JSONDecodeError, KeyError, ValueError) as e:
        print(f"      ⚠️  Erreur parsing réponse : {e}")
        return 0.0, "erreur parsing"
    except anthropic.APIError as e:
        print(f"      ⚠️  Erreur API : {e}")
        return 0.0, "erreur API"


# ────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────

def scorer_offres_nouvelles() -> dict:
    """
    Score toutes les offres au statut 'nouveau'.
    Retourne un résumé {interessantes, ignorees, erreurs}.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "❌ Variable ANTHROPIC_API_KEY manquante.\n"
            "   Lance : export ANTHROPIC_API_KEY='sk-ant-...'"
        )

    client = anthropic.Anthropic(api_key=api_key)
    mem = Memory()
    profil = charger_profil()
    resume_profil = resumer_profil(profil)

    # Récupère les offres non encore scorées
    with mem._connect() as conn:
        rows = conn.execute("""
            SELECT * FROM offres
            WHERE statut = 'nouveau'
            ORDER BY id ASC
            LIMIT ?
        """, (BATCH_SIZE,)).fetchall()

    offres = [dict(r) for r in rows]
    total = len(offres)

    if total == 0:
        print("ℹ️  Aucune offre nouvelle à scorer.")
        return {"interessantes": 0, "ignorees": 0, "erreurs": 0}

    print(f"🤖 Scoring de {total} offres avec Claude Haiku...\n")

    interessantes = ignorees = erreurs = 0

    for i, offre in enumerate(offres, 1):
        print(f"  [{i}/{total}] {offre['titre']} — {offre['entreprise']}")

        score, raison = scorer_offre(client, offre, resume_profil)

        if score == 0.0 and raison in ("erreur parsing", "erreur API"):
            erreurs += 1
            statut = "nouveau"  # on réessaiera plus tard
        elif score >= SCORE_MIN_INTERESSANT:
            interessantes += 1
            statut = "intéressant"
            print(f"     ✅ Score {score:.2f} — {raison}")
        else:
            ignorees += 1
            statut = "ignoré"
            print(f"     ⏭️  Score {score:.2f} — {raison}")

        # Mise à jour en base
        with mem._connect() as conn:
            conn.execute("""
                UPDATE offres
                SET score_pertinence = ?, statut = ?, notes = ?
                WHERE id = ?
            """, (score, statut, raison, offre["id"]))

        time.sleep(PAUSE_ENTRE_APPELS)

    print(f"""
✅ Scoring terminé
   ✅ Intéressantes : {interessantes}
   ⏭️  Ignorées      : {ignorees}
   ⚠️  Erreurs       : {erreurs}
""")
    mem.print_dashboard()

    return {"interessantes": interessantes, "ignorees": ignorees, "erreurs": erreurs}


if __name__ == "__main__":
    scorer_offres_nouvelles()
