"""
main.py — Point d'entrée unique pour le déploiement cloud
Lance le bot Telegram + le cycle agent automatique (toutes les 12h)
"""

import logging
import os
import re
import io
import json
from pathlib import Path
from datetime import datetime

import anthropic
import pypdf
import requests as req
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Conflict, NetworkError
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from scraper_wttj import scraper_wttj
from scraper_linkedin import scraper_linkedin
from scraper_indeed import scraper_indeed
from scraper_hellowork import scraper_hellowork
from scraper_labonnealternance import scraper_labonnealternance
from scraper_france_travail import scraper_france_travail
from scraper_apec import scraper_apec
from scorer import scorer_offres_nouvelles
from notifier import notifier_offres, alerter_offres_top
from reponses import run_suivi_candidatures
from emailer import envoyer_email
from candidater import run_candidatures_auto, envoyer_resume_quotidien, envoyer_stats_hebdo
from turso_sync import init_turso, restaurer_statuts_depuis_turso, sync_candidatures_vers_turso, restaurer_tout_depuis_turso
from alumni_linkedin import run_alumni_outreach
from linkedin_easy_apply import run_linkedin_easy_apply
from linkedin_agent import (run_linkedin_session, generer_post_linkedin, get_commentaires_pending,
                            publier_post, poster_commentaire_approuve, get_messages_pending,
                            envoyer_reponse_message, get_dms_pending, envoyer_dm_approuve)
from memory import Memory
from dashboard import start_dashboard

# ────────────────────────────────────────────────
# CONFIG
# ────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

TELEGRAM_TOKEN    = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID  = int(os.environ["TELEGRAM_CHAT_ID"])
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GMAIL_ADDRESS     = os.environ.get("GMAIL_ADDRESS", "mohamedalibenaqa@gmail.com")
PROFIL_PATH       = Path(__file__).parent / "profil_ali.json"

INTERVALLE_HEURES = 4

conversation_history: list[dict] = []


# ────────────────────────────────────────────────
# CONTEXTE CLAUDE (identique à bot.py)
# ────────────────────────────────────────────────

def charger_contexte() -> str:
    with open(PROFIL_PATH, "r", encoding="utf-8") as f:
        profil = json.load(f)

    mem = Memory()
    stats = mem.get_stats()
    souvenirs = mem.recall_all()

    with mem._connect() as conn:
        top_offres = conn.execute("""
            SELECT titre, entreprise, localisation, score_pertinence, notes, url, id
            FROM offres WHERE statut = 'intéressant'
            ORDER BY score_pertinence DESC LIMIT 20
        """).fetchall()

    top_str = "\n".join(
        f"  - [{o['id']}] {o['titre']} chez {o['entreprise']} ({o['localisation']}) — {int(o['score_pertinence']*100)}%"
        for o in top_offres
    )
    souvenirs_str = "\n".join(f"  - {k} : {v}" for k, v in souvenirs.items()) if souvenirs else "  (aucun)"
    r = profil["recherche_alternance"]

    return f"""Tu es l'assistant IA personnel d'Ali Benaqa, qui l'aide dans sa recherche d'alternance.
Tu es intégré dans Telegram. Tu tutoies Ali. Tu es direct, concis, efficace.

=== PROFIL ===
Formation : Bachelor Data & IA — Hetic (2e année, 3e année dès sept. 2026)
Disponibilité : {r['disponibilite']} | Durée : {r['duree_contrat']}
Postes ciblés : {', '.join(r['poste_cible'])}
Secteurs préférés : {', '.join(r['secteurs_preferes'])}
Localisation : {', '.join(r['localisation'])}
Expériences : Data Analyst freelance Techwin Services (ETL Python), Reporting Analyst stage Mamda Assurance (Power BI/PHP), Data Analyst BNC Corporation (KPI/EViews)
Stack : Python, SQL, Power BI, ETL, JavaScript, Node.js, React, PHP, MySQL, PostgreSQL, MongoDB, Git, Docker, Make, ChatGPT API, Claude API
Projets : Alternance Agent (Python/Claude API/Railway), AniData Lab (ETL/Airflow/ELK/Docker), Dream Interpreter (LLM/Whisper/Stable Diffusion), Data Refinement (Pandas), Jeu de dames (Python/Pygame)
Langues : Français bilingue, Anglais B2/C1, Espagnol A1/A2

=== STATS ===
Offres : {stats['total_offres']} total | {stats['offres_par_statut'].get('intéressant', 0)} intéressantes
Candidatures : {stats['total_candidatures']} | Entretiens : {stats['entretiens']}

=== TOP OFFRES (ID entre crochets) ===
{top_str or 'Aucune offre scorée.'}

=== MÉMOIRE ===
{souvenirs_str}

=== RÈGLES ===
- COURT et DIRECT. Pas d'intro, pas de formules de politesse.
- Max 2-3 lignes sauf email ou analyse demandée explicitement.
- Pas de "Bien sûr !", "Avec plaisir !" etc.
- Si Ali dit "retiens/souviens-toi/note que..." → ajoute [RETENIR: cle=valeur] à la fin.
"""


# ────────────────────────────────────────────────
# APPELS CLAUDE
# ────────────────────────────────────────────────

def _post_process(reply: str) -> str:
    """Extrait les [RETENIR:...], les sauvegarde, nettoie le texte."""
    mem = Memory()
    souvenirs = re.findall(r'\[RETENIR:\s*([^=\]]+)=([^\]]+)\]', reply)
    for cle, valeur in souvenirs:
        mem.remember(cle.strip(), valeur.strip())
    return re.sub(r'\[RETENIR:[^\]]+\]', '', reply).strip()


def demander_claude(message_user: str) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    mem = Memory()
    mem.save_message("user", message_user)
    conversation_history.append({"role": "user", "content": message_user})
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            system=charger_contexte(),
            messages=conversation_history[-20:],
        )
        reply = _post_process(resp.content[0].text.strip())
        mem.save_message("assistant", reply)
        conversation_history.append({"role": "assistant", "content": reply})
        return reply
    except anthropic.APIError as e:
        return f"❌ Erreur API : {e}"


def demander_claude_vision(message_user: str, image_bytes: bytes, mime_type: str) -> str:
    import base64
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    mem = Memory()
    mem.save_message("user", f"[Image] {message_user}")
    conversation_history.append({"role": "user", "content": f"[Image] {message_user}"})
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            system=charger_contexte(),
            messages=[
                *conversation_history[-10:][:-1],
                {"role": "user", "content": [
                    {"type": "image", "source": {
                        "type": "base64",
                        "media_type": mime_type,
                        "data": base64.standard_b64encode(image_bytes).decode(),
                    }},
                    {"type": "text", "text": message_user or "Analyse cette image."},
                ]},
            ],
        )
        reply = _post_process(resp.content[0].text.strip())
        mem.save_message("assistant", reply)
        conversation_history.append({"role": "assistant", "content": reply})
        return reply
    except anthropic.APIError as e:
        return f"❌ Erreur API : {e}"


# ────────────────────────────────────────────────
# CYCLE AGENT
# ────────────────────────────────────────────────

def _telegram_send(texte: str):
    req.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": texte, "parse_mode": "HTML"},
        timeout=10,
    )


def run_cycle():
    log.info("🚀 Démarrage du cycle agent")
    _telegram_send("🤖 <b>Cycle agent démarré</b>")

    # Restaure les candidatures précédentes depuis Turso pour éviter doublons
    try:
        restaurer_statuts_depuis_turso()
    except Exception as e:
        log.error(f"Turso restauration : {e}")

    nb_nouvelles = 0
    try:
        nb_nouvelles += scraper_wttj()
    except Exception as e:
        log.error(f"Scraping WTTJ : {e}")
    try:
        nb_nouvelles += scraper_linkedin()
    except Exception as e:
        log.error(f"Scraping LinkedIn : {e}")
    try:
        nb_nouvelles += scraper_indeed()
    except Exception as e:
        log.error(f"Scraping Indeed : {e}")
    try:
        nb_nouvelles += scraper_hellowork()
    except Exception as e:
        log.error(f"Scraping HelloWork : {e}")
    try:
        nb_nouvelles += scraper_labonnealternance()
    except Exception as e:
        log.error(f"Scraping LaBonneAlternance : {e}")
    try:
        nb_nouvelles += scraper_france_travail()
    except Exception as e:
        log.error(f"Scraping France Travail : {e}")
    try:
        nb_nouvelles += scraper_apec()
    except Exception as e:
        log.error(f"Scraping APEC : {e}")

    try:
        stats = scorer_offres_nouvelles()
    except Exception as e:
        log.error(f"Scoring : {e}")
        stats = {"interessantes": 0, "ignorees": 0, "erreurs": 0}

    # Alerte immédiate pour les offres >90%
    try:
        alerter_offres_top()
    except Exception as e:
        log.error(f"Alerte top offres : {e}")

    try:
        nb_notifs = notifier_offres()
    except Exception as e:
        log.error(f"Notifs : {e}")
        nb_notifs = 0

    # Lecture réponses recruteurs + relances auto
    try:
        suivi = run_suivi_candidatures()
    except Exception as e:
        log.error(f"Suivi candidatures : {e}")
        suivi = {"reponses": 0, "relances": 0}

    try:
        cand_stats = run_candidatures_auto()
        nb_cands = cand_stats["email"] + cand_stats["formulaire"]
    except Exception as e:
        log.error(f"Candidatures : {e}")
        nb_cands = 0

    try:
        ea_stats = run_linkedin_easy_apply()
        nb_cands += ea_stats["candidatures"]
    except Exception as e:
        log.error(f"LinkedIn Easy Apply : {e}")

    # Synchronise les candidatures vers Turso pour persister entre déploiements
    try:
        sync_candidatures_vers_turso()
    except Exception as e:
        log.error(f"Turso sync : {e}")

    # Outreach alumni Hetic (1 fois sur 2 pour ne pas surcharger le cycle)
    nb_alumni = 0
    try:
        alumni_stats = run_alumni_outreach()
        nb_alumni = alumni_stats.get("emails_envoyes", 0)
    except Exception as e:
        log.error(f"Alumni outreach : {e}")

    resume = (
        f"✅ <b>Cycle terminé</b>\n"
        f"📡 Nouvelles : {nb_nouvelles} | ✅ Intéressantes : {stats['interessantes']}\n"
        f"📤 Candidatures : {nb_cands} | 🔄 Relances : {suivi['relances']}\n"
        f"📬 Réponses reçues : {suivi['reponses']} | 🎓 Alumni : {nb_alumni}"
    )
    _telegram_send(resume)
    log.info(f"Cycle terminé — {nb_nouvelles} nouvelles, {stats['interessantes']} intéressantes")


async def job_cycle(context: ContextTypes.DEFAULT_TYPE):
    """Tâche planifiée appelée par le JobQueue du bot."""
    import asyncio
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, run_cycle)


async def job_resume_quotidien(context: ContextTypes.DEFAULT_TYPE):
    """Résumé quotidien à 20h."""
    import asyncio
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, envoyer_resume_quotidien)


async def job_stats_hebdo(context: ContextTypes.DEFAULT_TYPE):
    """Bilan hebdomadaire chaque lundi à 09h."""
    import asyncio
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, envoyer_stats_hebdo)


async def job_linkedin_session(context: ContextTypes.DEFAULT_TYPE):
    """Lance une session LinkedIn autonome (connexions + commentaires)."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    weekday = now.weekday()  # 0=lundi, 5=samedi, 6=dimanche

    # Pas d'activité le weekend
    if weekday >= 5:
        log.info("⏸️  LinkedIn session — weekend, skip")
        return

    import asyncio
    loop = asyncio.get_event_loop()
    app = context.application
    await loop.run_in_executor(None, lambda: run_linkedin_session(app))


# ────────────────────────────────────────────────
# HANDLERS TELEGRAM
# ────────────────────────────────────────────────

def _check(update: Update) -> bool:
    return update.effective_user.id == TELEGRAM_CHAT_ID


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check(update): return
    conversation_history.clear()
    Memory().clear_history()
    reply = demander_claude(
        "Ali vient de démarrer le bot. Présente-toi en 2 lignes max et donne les stats clés."
    )
    await update.message.reply_text(reply)


async def cmd_offres(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check(update): return
    mem = Memory()
    with mem._connect() as conn:
        offres = conn.execute("""
            SELECT id, titre, entreprise, localisation, score_pertinence
            FROM offres WHERE statut = 'intéressant'
            ORDER BY score_pertinence DESC LIMIT 10
        """).fetchall()
    if not offres:
        await update.message.reply_text("Aucune offre intéressante pour l'instant.")
        return
    await update.message.reply_text("🏆 <b>Top 10 offres :</b>", parse_mode="HTML")
    for o in offres:
        pct = int(o["score_pertinence"] * 100)
        emoji = "🔥" if pct >= 90 else "✅" if pct >= 80 else "👍"
        texte = f"{emoji} <b>{o['titre']}</b>\n🏢 {o['entreprise']} — 📍 {o['localisation']} — ⭐ {pct}%"
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Intéressé", callback_data=f"ok_{o['id']}"),
            InlineKeyboardButton("❌ Ignorer",   callback_data=f"no_{o['id']}"),
            InlineKeyboardButton("📧 Email",     callback_data=f"mail_{o['id']}"),
        ]])
        await update.message.reply_text(texte, parse_mode="HTML", reply_markup=kb)


async def cmd_cycle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lance manuellement un cycle depuis Telegram."""
    if not _check(update): return
    await update.message.reply_text("🚀 Cycle lancé, je te notifie quand c'est fini...")
    import asyncio
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, run_cycle)


async def cmd_linkedin_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Force une session LinkedIn maintenant (test)."""
    if not _check(update): return
    await update.message.reply_text("🌐 Session LinkedIn lancée, je te notifie quand c'est fini...")
    import asyncio
    app = context.application
    await asyncio.get_event_loop().run_in_executor(None, lambda: run_linkedin_session(app))


async def cmd_linkedin_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Génère et propose un post LinkedIn depuis Telegram. Usage: /linkedin_post <sujet>"""
    if not _check(update): return
    sujet = " ".join(context.args) if context.args else ""
    if not sujet:
        await update.message.reply_text("Usage : /linkedin_post <décris ton projet ou sujet>\nEx: /linkedin_post j'ai terminé mon agent IA de recherche d'alternance en Python")
        return

    await update.message.reply_text("⏳ Génération du post LinkedIn en cours...")
    import asyncio
    texte = await asyncio.get_event_loop().run_in_executor(None, lambda: generer_post_linkedin(sujet))

    if not texte:
        await update.message.reply_text("❌ Erreur lors de la génération du post.")
        return

    cle = f"post_{int(__import__('time').time())}"
    from linkedin_agent import get_posts_pending
    get_posts_pending()[cle] = texte

    apercu = f"📝 <b>Post LinkedIn généré :</b>\n\n{texte}\n\n<i>Approuves-tu ce post ?</i>"
    buttons = [[
        {"text": "✅ Publier", "callback_data": f"linkedin_post_ok:{cle}"},
        {"text": "❌ Annuler", "callback_data": f"linkedin_post_cancel:{cle}"},
    ]]
    await update.message.reply_text(apercu, parse_mode="HTML", reply_markup={"inline_keyboard": buttons})


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Affiche l'état du bot et le prochain cycle."""
    if not _check(update): return
    mem = Memory()
    stats = mem.get_stats()

    # Prochain cycle auto
    jobs = context.application.job_queue.get_jobs_by_name("job_cycle")
    if jobs:
        next_run = jobs[0].next_t
        if next_run:
            from datetime import timezone
            now = datetime.now(timezone.utc)
            delta = next_run - now
            minutes = int(delta.total_seconds() // 60)
            heures = minutes // 60
            mins = minutes % 60
            prochain = f"{heures}h{mins:02d}" if heures else f"{mins} min"
        else:
            prochain = "inconnu"
    else:
        prochain = "non planifié"

    msg = (
        f"🤖 <b>Status du bot</b>\n\n"
        f"⏱ Prochain cycle auto : <b>dans {prochain}</b>\n"
        f"🔄 Intervalle : toutes les {INTERVALLE_HEURES}h\n\n"
        f"📊 <b>Statistiques</b>\n"
        f"  Offres scrapées : {stats.get('total_offres', 0)}\n"
        f"  Offres intéressantes : {stats.get('offres_interessantes', 0)}\n"
        f"  Candidatures envoyées : {stats.get('total_candidatures', 0)}\n"
        f"  Réponses reçues : {stats.get('reponses', 0)}\n"
        f"  Alumni contactés : {stats.get('alumni_contactes', 0)}\n\n"
        f"💡 /cycle pour forcer un cycle maintenant"
    )
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check(update): return
    reply = demander_claude("Stats rapides de ma recherche.")
    await update.message.reply_text(reply)


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check(update): return
    conversation_history.clear()
    Memory().clear_history()
    await update.message.reply_text("🔄 Conversation remise à zéro.")


async def cmd_candidatures(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Affiche les dernières candidatures envoyées avec leur statut."""
    if not _check(update): return
    mem = Memory()
    with mem._connect() as conn:
        cands = conn.execute("""
            SELECT c.id, c.canal, c.email_dest, c.statut, c.nb_relances,
                   c.date_candidature, o.titre, o.entreprise, o.statut as statut_offre
            FROM candidatures c
            LEFT JOIN offres o ON c.offre_id = o.id
            ORDER BY c.date_candidature DESC
            LIMIT 15
        """).fetchall()

    if not cands:
        await update.message.reply_text("Aucune candidature envoyée pour l'instant.")
        return

    icons_statut = {
        "envoyée":   "📤", "relance": "🔄", "entretien": "🎉",
        "réponse":   "📬", "refusé":  "❌", "vue":       "👁",
    }
    icons_canal = {
        "email": "📧", "formulaire_web": "🌐",
        "linkedin_easy_apply": "🔗", "formulaire": "🌐",
    }

    msg = "📋 <b>Tes candidatures :</b>\n\n"
    for c in cands:
        ic = icons_canal.get(c["canal"], "📤")
        is_ = icons_statut.get(c["statut_offre"] or c["statut"], "📤")
        date = (c["date_candidature"] or "")[:10]
        relances = f" ({c['nb_relances']} relance(s))" if c["nb_relances"] else ""
        msg += (
            f"{is_} <b>{c['titre'] or '?'}</b> — {c['entreprise'] or '?'}\n"
            f"   {ic} {c['canal']} | {date}{relances}\n\n"
        )

    stats = mem.get_stats()
    msg += (
        f"─────────────────\n"
        f"Total : <b>{stats['total_candidatures']}</b> candidatures | "
        f"<b>{stats['entretiens']}</b> entretiens | "
        f"Taux réponse : <b>{stats['taux_reponse']}%</b>"
    )
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_alumni(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Affiche les alumni Hetic contactés et leur statut."""
    if not _check(update): return
    mem = Memory()
    with mem._connect() as conn:
        tous = conn.execute("""
            SELECT prenom, nom, poste_actuel, entreprise,
                   statut_contact, date_contact, email
            FROM alumni
            ORDER BY date_contact DESC NULLS LAST, date_scrape DESC
            LIMIT 20
        """).fetchall()

    if not tous:
        await update.message.reply_text("Aucun alumni trouvé pour l'instant. Lance /cycle pour en chercher.")
        return

    icons = {
        "mail envoyé":    "📧",
        "répondu":        "💬",
        "relancé":        "🔄",
        "non contacté":   "⏳",
    }

    contactes  = [a for a in tous if a["statut_contact"] == "mail envoyé" or a["statut_contact"] == "répondu"]
    en_attente = [a for a in tous if a["statut_contact"] == "non contacté"]

    msg = f"🎓 <b>Alumni Hetic ({len(tous)} total)</b>\n\n"

    if contactes:
        msg += f"<b>📧 Contactés ({len(contactes)}) :</b>\n"
        for a in contactes[:10]:
            ic = icons.get(a["statut_contact"], "📧")
            date = (a["date_contact"] or "")[:10]
            msg += f"  {ic} <b>{a['prenom']} {a['nom']}</b> — {a['poste_actuel'] or ''} @ {a['entreprise']}\n"
            if date:
                msg += f"      Contacté le {date}\n"

    if en_attente:
        msg += f"\n<b>⏳ En attente de contact ({len(en_attente)}) :</b>\n"
        for a in en_attente[:5]:
            msg += f"  • {a['prenom']} {a['nom']} — {a['entreprise']}\n"

    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_relances(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Affiche les candidatures à relancer + bouton pour relancer maintenant."""
    if not _check(update): return
    mem = Memory()
    a_relancer = mem.get_candidatures_a_relancer()

    if not a_relancer:
        await update.message.reply_text("✅ Aucune relance en attente.")
        return

    await update.message.reply_text(
        f"🔄 <b>{len(a_relancer)} candidature(s) à relancer :</b>",
        parse_mode="HTML"
    )
    for c in a_relancer[:8]:
        texte = (
            f"🔄 <b>{c.get('titre', '?')}</b> — {c.get('entreprise', '?')}\n"
            f"📧 {c.get('email_dest', '?')}\n"
            f"Relances envoyées : {c.get('nb_relances', 0)}/2"
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("📤 Relancer maintenant", callback_data=f"relance_{c['id']}"),
            InlineKeyboardButton("❌ Ignorer",             callback_data=f"skip_relance_{c['id']}"),
        ]])
        await update.message.reply_text(texte, parse_mode="HTML", reply_markup=kb)


async def cmd_entretiens(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Affiche les offres en statut entretien."""
    if not _check(update): return
    mem = Memory()
    with mem._connect() as conn:
        entretiens = conn.execute("""
            SELECT o.titre, o.entreprise, o.notes, o.url,
                   c.date_candidature, c.email_dest
            FROM offres o
            LEFT JOIN candidatures c ON c.offre_id = o.id
            WHERE o.statut = 'entretien'
            ORDER BY c.date_candidature DESC
        """).fetchall()

    if not entretiens:
        await update.message.reply_text("Aucun entretien pour l'instant. Ça va venir 💪")
        return

    msg = f"🎉 <b>{len(entretiens)} entretien(s) !</b>\n\n"
    for e in entretiens:
        msg += (
            f"🏢 <b>{e['entreprise']}</b> — {e['titre']}\n"
            f"📝 {e['notes'] or 'Pas de notes'}\n"
            f"🔗 <a href=\"{e['url']}\">Voir l'offre</a>\n\n"
        )
    await update.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Affiche toutes les commandes disponibles."""
    if not _check(update): return
    msg = (
        "🤖 <b>Commandes disponibles :</b>\n\n"
        "📋 <b>Recherche</b>\n"
        "/offres — Top 10 offres intéressantes\n"
        "/stats — Statistiques globales\n"
        "/cycle — Lancer un cycle maintenant\n\n"
        "📤 <b>Candidatures</b>\n"
        "/candidatures — Toutes tes candidatures\n"
        "/relances — Candidatures à relancer\n"
        "/entretiens — Entretiens obtenus 🎉\n\n"
        "🎓 <b>Alumni</b>\n"
        "/alumni — Alumni Hetic contactés\n\n"
        "⚙️ <b>Autre</b>\n"
        "/reset — Réinitialiser la conversation\n"
        "/help — Cette aide\n\n"
        "💬 Tu peux aussi m'écrire librement !"
    )
    await update.message.reply_text(msg, parse_mode="HTML")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check(update): return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    reply = demander_claude(update.message.text)
    await update.message.reply_text(reply, parse_mode="HTML")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check(update): return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    image_bytes = bytes(await file.download_as_bytearray())
    caption = update.message.caption or "Analyse cette image. Si c'est une offre, dis-moi si ça matche mon profil."
    reply = demander_claude_vision(caption, image_bytes, "image/jpeg")
    await update.message.reply_text(reply, parse_mode="HTML")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check(update): return
    doc = update.message.document
    mime = doc.mime_type or ""
    caption = update.message.caption or ""
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    file = await context.bot.get_file(doc.file_id)
    file_bytes = bytes(await file.download_as_bytearray())

    if mime == "application/pdf" or doc.file_name.endswith(".pdf"):
        try:
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            texte = "\n".join(p.extract_text() or "" for p in reader.pages)[:4000]
            if not texte.strip():
                await update.message.reply_text("⚠️ Impossible d'extraire le texte de ce PDF.")
                return
            instruction = caption or "Analyse ce document. CV → conseils. Offre → est-ce que ça matche ?"
            reply = demander_claude(f"{instruction}\n\n--- PDF ---\n{texte}")
        except Exception as e:
            reply = f"❌ Erreur PDF : {e}"
    elif mime.startswith("image/"):
        reply = demander_claude_vision(caption or "Analyse cette image.", file_bytes, mime)
    else:
        reply = f"⚠️ Format non supporté ({mime})."

    await update.message.reply_text(reply, parse_mode="HTML")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    mem = Memory()

    if data.startswith("ok_"):
        mem.update_offre_statut(int(data[3:]), "intéressant", "Confirmé par Ali")
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("✅ Marqué prioritaire. Je rédige l'email ?")

    elif data.startswith("no_"):
        mem.update_offre_statut(int(data[3:]), "ignoré")
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("⏭️ Ignoré.")

    elif data.startswith("mail_"):
        offre_id = int(data[5:])
        with mem._connect() as conn:
            o = conn.execute("SELECT * FROM offres WHERE id = ?", (offre_id,)).fetchone()
        if o:
            await context.bot.send_chat_action(chat_id=query.message.chat_id, action="typing")
            prompt = (
                f"Rédige un email de candidature pour :\n"
                f"Poste : {o['titre']}\nEntreprise : {o['entreprise']}\n"
                f"Description : {o['description'][:500] if o['description'] else 'N/A'}\n"
                f"Style : pro mais accessible, 150-200 mots, met en avant mes 3 expériences data et Hetic.\n"
                f"Termine par une ligne séparée : OBJET: [sujet de l'email]"
            )
            brouillon = demander_claude(prompt)
            # Extraire l'objet si présent
            objet = f"Candidature alternance – {o['titre']} – Ali Benaqa"
            if "OBJET:" in brouillon:
                lignes = brouillon.split("\n")
                for l in lignes:
                    if l.startswith("OBJET:"):
                        objet = l.replace("OBJET:", "").strip()
                brouillon = "\n".join(l for l in lignes if not l.startswith("OBJET:")).strip()

            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("📤 Envoyer maintenant", callback_data=f"send_{offre_id}|{objet[:60]}"),
                InlineKeyboardButton("❌ Annuler", callback_data="cancel"),
            ]])
            # Stocke le brouillon temporairement en mémoire
            mem.remember(f"brouillon_{offre_id}", brouillon)
            await query.message.reply_text(
                f"📧 <b>Brouillon :</b>\n\n{brouillon}\n\n<b>Objet :</b> {objet}",
                parse_mode="HTML", reply_markup=kb
            )

    elif data.startswith("send_"):
        parts = data[5:].split("|", 1)
        offre_id = int(parts[0])
        objet = parts[1] if len(parts) > 1 else "Candidature alternance"
        brouillon = mem.recall(f"brouillon_{offre_id}") or ""
        if brouillon:
            ok = envoyer_email(
                destinataire=GMAIL_ADDRESS,  # Envoi à soi-même pour test, à changer avec l'email du recruteur
                sujet=objet,
                corps=brouillon,
                offre_id=offre_id,
            )
            if ok:
                mem.add_candidature({
                    "offre_id": offre_id,
                    "canal": "email",
                    "email_dest": GMAIL_ADDRESS,
                    "objet_email": objet,
                    "corps_email": brouillon,
                })
                await query.edit_message_reply_markup(reply_markup=None)
                await query.message.reply_text("✅ Email envoyé et candidature enregistrée !")
            else:
                await query.message.reply_text("❌ Erreur lors de l'envoi. Vérifie les logs Railway.")
        else:
            await query.message.reply_text("⚠️ Brouillon introuvable, refais /offres.")

    elif data == "cancel":
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("❌ Annulé.")

    elif data.startswith("linkedin_comment_ok:"):
        cle = data[len("linkedin_comment_ok:"):]
        pending = get_commentaires_pending().get(cle)
        if not pending:
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("⚠️ Commentaire expiré ou déjà traité.")
        else:
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("⏳ Publication du commentaire en cours...")

            def _poster():
                from playwright.sync_api import sync_playwright
                from linkedin_agent import _launch_browser, _login, _commentaires_pending as _cp
                import asyncio as _aio
                with sync_playwright() as p:
                    browser, ctx = _launch_browser(p)
                    page = ctx.new_page()
                    ok = False
                    if _login(page):
                        # poster_commentaire_approuve est async → on l'exécute dans un loop dédié
                        loop = _aio.new_event_loop()
                        ok = loop.run_until_complete(poster_commentaire_approuve(cle, page))
                        loop.close()
                    browser.close()
                    return ok

            import asyncio
            ok = await asyncio.get_event_loop().run_in_executor(None, _poster)
            await query.message.reply_text("✅ Commentaire posté !" if ok else "❌ Impossible de poster le commentaire.")

    elif data.startswith("linkedin_post_ok:"):
        cle = data[len("linkedin_post_ok:"):]
        from linkedin_agent import get_posts_pending
        texte = get_posts_pending().pop(cle, None)
        if not texte:
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("⚠️ Post expiré ou déjà publié.")
        else:
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("⏳ Publication sur LinkedIn en cours...")

            def _publier():
                from playwright.sync_api import sync_playwright
                from linkedin_agent import _launch_browser, _login
                with sync_playwright() as p:
                    browser, ctx = _launch_browser(p)
                    page = ctx.new_page()
                    ok = _login(page) and publier_post(page, texte)
                    browser.close()
                    return ok

            import asyncio
            ok = await asyncio.get_event_loop().run_in_executor(None, _publier)
            await query.message.reply_text("✅ Post publié sur LinkedIn !" if ok else "❌ Impossible de publier le post.")

    elif data.startswith("linkedin_post_cancel:"):
        cle = data[len("linkedin_post_cancel:"):]
        from linkedin_agent import get_posts_pending
        get_posts_pending().pop(cle, None)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("❌ Post annulé.")

    elif data.startswith("linkedin_comment_skip:"):
        cle = data[len("linkedin_comment_skip:"):]
        get_commentaires_pending().pop(cle, None)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("⏭️ Commentaire ignoré.")

    elif data.startswith("linkedin_msg_ok:"):
        cle = data[len("linkedin_msg_ok:"):]
        pending = get_messages_pending().get(cle)
        if not pending:
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("⚠️ Message expiré.")
        else:
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("⏳ Envoi de la réponse en cours...")

            def _repondre():
                from playwright.sync_api import sync_playwright
                from linkedin_agent import _launch_browser, _login
                with sync_playwright() as p:
                    browser, ctx = _launch_browser(p)
                    page = ctx.new_page()
                    ok = _login(page) and envoyer_reponse_message(cle, page)
                    browser.close()
                    return ok

            import asyncio
            ok = await asyncio.get_event_loop().run_in_executor(None, _repondre)
            await query.message.reply_text("✅ Réponse envoyée !" if ok else "❌ Erreur envoi réponse.")

    elif data.startswith("linkedin_msg_skip:"):
        cle = data[len("linkedin_msg_skip:"):]
        get_messages_pending().pop(cle, None)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("⏭️ Message ignoré.")

    elif data.startswith("linkedin_dm_ok:"):
        cle = data[len("linkedin_dm_ok:"):]
        pending = get_dms_pending().get(cle)
        if not pending:
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("⚠️ DM expiré.")
        else:
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("⏳ Envoi du DM en cours...")

            def _envoyer_dm():
                from playwright.sync_api import sync_playwright
                from linkedin_agent import _launch_browser, _login
                with sync_playwright() as p:
                    browser, ctx = _launch_browser(p)
                    page = ctx.new_page()
                    ok = _login(page) and envoyer_dm_approuve(cle, page)
                    browser.close()
                    return ok

            import asyncio
            ok = await asyncio.get_event_loop().run_in_executor(None, _envoyer_dm)
            await query.message.reply_text("✅ DM envoyé !" if ok else "❌ Erreur envoi DM.")

    elif data.startswith("linkedin_dm_skip:"):
        cle = data[len("linkedin_dm_skip:"):]
        get_dms_pending().pop(cle, None)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("⏭️ DM ignoré.")

    elif data.startswith("relance_"):
        from reponses import envoyer_relances_auto
        cand_id = int(data[8:])
        with mem._connect() as conn:
            cand = conn.execute("SELECT * FROM candidatures WHERE id = ?", (cand_id,)).fetchone()
            if cand:
                offre = conn.execute("SELECT * FROM offres WHERE id = ?", (cand["offre_id"],)).fetchone()
        if cand and offre:
            from emailer import envoyer_email
            from reponses import _generer_email_relance
            email_data = _generer_email_relance(dict(offre), dict(cand))
            ok = envoyer_email(dict(cand)["email_dest"], email_data["objet"], email_data["corps"])
            if ok:
                with mem._connect() as conn:
                    conn.execute("""
                        UPDATE candidatures SET nb_relances = nb_relances + 1,
                        date_relance = datetime('now', '+7 days'), statut = 'relance'
                        WHERE id = ?
                    """, (cand_id,))
                await query.edit_message_reply_markup(reply_markup=None)
                await query.message.reply_text(f"✅ Relance envoyée à {dict(cand)['email_dest']}")
            else:
                await query.message.reply_text("❌ Erreur envoi relance.")

    elif data.startswith("skip_relance_"):
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("⏭️ Relance ignorée.")


# ────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────

def main():
    # Restaure les données depuis Turso dès le démarrage (avant le dashboard)
    try:
        init_turso()
        restaurer_tout_depuis_turso()
        log.info("✅ Données Turso restaurées dans SQLite local")
    except Exception as e:
        log.warning(f"⚠️  Restauration Turso au démarrage : {e}")

    # Lance le dashboard web
    start_dashboard()
    log.info(f"🌐 Dashboard lancé sur le port {os.environ.get('PORT', 8080)}")

    # Charge l'historique persistant
    conversation_history.extend(Memory().load_history())

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start",        cmd_start))
    app.add_handler(CommandHandler("offres",       cmd_offres))
    app.add_handler(CommandHandler("stats",        cmd_stats))
    app.add_handler(CommandHandler("cycle",        cmd_cycle))
    app.add_handler(CommandHandler("reset",        cmd_reset))
    app.add_handler(CommandHandler("candidatures", cmd_candidatures))
    app.add_handler(CommandHandler("alumni",       cmd_alumni))
    app.add_handler(CommandHandler("relances",     cmd_relances))
    app.add_handler(CommandHandler("entretiens",   cmd_entretiens))
    app.add_handler(CommandHandler("help",           cmd_help))
    app.add_handler(CommandHandler("status",         cmd_status))
    app.add_handler(CommandHandler("linkedin_post",    cmd_linkedin_post))
    app.add_handler(CommandHandler("linkedin_session", cmd_linkedin_session))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Cycle automatique toutes les 12h
    app.job_queue.run_repeating(
        job_cycle,
        interval=INTERVALLE_HEURES * 3600,
        first=3600,  # premier cycle 1h après démarrage
    )

    # Résumé quotidien à 20h
    app.job_queue.run_daily(
        job_resume_quotidien,
        time=datetime.strptime("20:00", "%H:%M").time(),
    )

    # Bilan hebdomadaire chaque lundi à 09h
    app.job_queue.run_daily(
        job_stats_hebdo,
        time=datetime.strptime("09:00", "%H:%M").time(),
        days=(0,),  # 0 = lundi
    )

    # ── Sessions LinkedIn autonomes ──────────────────────────────
    # Lundi : 3 sessions entre 6h et 17h (06h, 10h, 14h + jitter)
    from datetime import timezone as _tz
    import random as _rnd

    for heure_base in ["06:00", "10:00", "14:00"]:
        t = datetime.strptime(heure_base, "%H:%M").replace(tzinfo=_tz.utc).time()
        app.job_queue.run_daily(
            job_linkedin_session,
            time=t,
            days=(0,),  # lundi
            name=f"linkedin_lundi_{heure_base}",
        )

    # Mardi–Vendredi : 2 sessions entre 9h et 17h (09h30 et 14h30)
    for heure_base in ["09:30", "14:30"]:
        t = datetime.strptime(heure_base, "%H:%M").replace(tzinfo=_tz.utc).time()
        app.job_queue.run_daily(
            job_linkedin_session,
            time=t,
            days=(1, 2, 3, 4),  # mar-ven
            name=f"linkedin_semaine_{heure_base}",
        )

    # Gestion des erreurs (conflit Railway au redéploiement)
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        if isinstance(context.error, Conflict):
            log.warning("⚠️  Conflit Telegram (redéploiement en cours) — l'ancienne instance s'arrête, patience...")
        elif isinstance(context.error, NetworkError):
            log.warning(f"⚠️  Erreur réseau Telegram (transitoire) : {context.error}")
        else:
            log.error(f"Erreur bot : {context.error}", exc_info=context.error)

    app.add_error_handler(error_handler)

    log.info(f"🤖 Bot démarré — cycle auto toutes les {INTERVALLE_HEURES}h")
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


if __name__ == "__main__":
    main()
