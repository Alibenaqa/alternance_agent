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
from scorer import scorer_offres_nouvelles
from notifier import notifier_offres, alerter_offres_top
from reponses import run_suivi_candidatures
from emailer import envoyer_email
from candidater import run_candidatures_auto, envoyer_resume_quotidien
from turso_sync import init_turso, restaurer_statuts_depuis_turso, sync_candidatures_vers_turso
from alumni_linkedin import run_alumni_outreach
from memory import Memory

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

INTERVALLE_HEURES = 8

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
Formation : Bachelor Data & IA — Hetic (3e année)
Disponibilité : {r['disponibilite']} | Durée : {r['duree_contrat']}
Postes ciblés : {', '.join(r['poste_cible'])}
Secteurs préférés : {', '.join(r['secteurs_preferes'])}
Localisation : {', '.join(r['localisation'])}
Expériences : Data Analyst (Techwin, BNC Corporation), Stage Mamda Assurance
Stack : Python, SQL, Power BI, ETL, API REST, Machine Learning

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


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check(update): return
    reply = demander_claude("Stats rapides de ma recherche.")
    await update.message.reply_text(reply)


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check(update): return
    conversation_history.clear()
    Memory().clear_history()
    await update.message.reply_text("🔄 Conversation remise à zéro.")


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


# ────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────

def main():
    # Charge l'historique persistant
    conversation_history.extend(Memory().load_history())

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("offres", cmd_offres))
    app.add_handler(CommandHandler("stats",  cmd_stats))
    app.add_handler(CommandHandler("cycle",  cmd_cycle))
    app.add_handler(CommandHandler("reset",  cmd_reset))
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

    log.info(f"🤖 Bot démarré — cycle auto toutes les {INTERVALLE_HEURES}h")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
