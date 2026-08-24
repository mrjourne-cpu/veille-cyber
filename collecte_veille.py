#!/usr/bin/env python3
"""
Collecte quotidienne — Main Courante Cyber
Récupère les publications récentes des sources officielles à flux
(CERT-FR, ANSSI, CERT-EU, Fuites Infos) et les dépose dans latest.json
à la racine du dépôt, plus une copie datée dans archive/.

Conçu pour tourner dans GitHub Actions (accès réseau complet), pas dans
un environnement Claude (réseau restreint à une liste blanche).

Aucune dépendance exotique : requests + feedparser (fallback HTML si le
flux RSS ne répond pas). Tout est défensif — une source qui échoue ne
fait pas planter les autres ; l'échec est simplement consigné dans le
JSON de sortie sous "erreurs".
"""

import json
import re
import sys
from datetime import datetime, timedelta, timezone

import requests

try:
    import feedparser
except ImportError:
    feedparser = None

TIMEOUT = 20
HEADERS = {"User-Agent": "veille-cyber-bot/1.0 (+contact: usage interne)"}
FENETRE_JOURS = 3  # marge de sécurité au-delà des 48h ciblées par la main courante

now = datetime.now(timezone.utc)
seuil = (now - timedelta(days=FENETRE_JOURS)).replace(hour=0, minute=0, second=0, microsecond=0)


def log(msg):
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}", file=sys.stderr)


def get(url, **kw):
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, **kw)
    r.raise_for_status()
    return r


def parse_feed_entries(feed_urls, limiter=None):
    """Essaie une liste de flux RSS candidats, renvoie (entries, url_utilisee)."""
    if feedparser is None:
        return [], None
    for url in feed_urls:
        try:
            resp = get(url)
            parsed = feedparser.parse(resp.content)
            if parsed.bozo and not parsed.entries:
                continue
            if not parsed.entries:
                continue
            entries = []
            for e in parsed.entries:
                date_struct = e.get("published_parsed") or e.get("updated_parsed")
                date_iso = None
                if date_struct:
                    date_iso = datetime(*date_struct[:6], tzinfo=timezone.utc).isoformat()
                entries.append({
                    "titre": e.get("title", "").strip(),
                    "url": e.get("link", "").strip(),
                    "date": date_iso,
                    "resume": re.sub("<[^<]+?>", "", e.get("summary", "")).strip()[:500],
                })
            return entries, url
        except Exception as exc:
            log(f"flux échoué {url}: {exc}")
            continue
    return [], None


def filtrer_recent(entries):
    out = []
    for e in entries:
        if e["date"] is None:
            out.append(e)  # on garde si la date n'a pas pu être extraite, à trier manuellement
            continue
        try:
            d = datetime.fromisoformat(e["date"])
        except Exception:
            out.append(e)
            continue
        if d >= seuil:
            out.append(e)
    return out


def scrape_listing_fallback(url, link_pattern, base=""):
    """Repli générique : récupère une page de listing HTML et en extrait les liens
    correspondant à link_pattern (regex avec un groupe = référence)."""
    try:
        resp = get(url)
    except Exception as exc:
        log(f"listing échoué {url}: {exc}")
        return []
    html = resp.text
    refs = set(re.findall(link_pattern, html))
    entries = []
    for ref in refs:
        entries.append({
            "titre": ref,
            "url": f"{base}{ref}/" if base else ref,
            "date": None,
            "resume": "",
        })
    return entries


resultat = {
    "genere_le": now.isoformat(),
    "fenetre_jours": FENETRE_JOURS,
    "sources": {},
    "erreurs": [],
}


# --- CERT-FR : avis ---------------------------------------------------------
log("CERT-FR avis")
entries, used = parse_feed_entries([
    "https://www.cert.ssi.gouv.fr/avis/feed",
    "https://www.cert.ssi.gouv.fr/avis/feed/",
    "https://www.cert.ssi.gouv.fr/feed/",
])
if not entries:
    entries = scrape_listing_fallback(
        "https://www.cert.ssi.gouv.fr/avis/",
        r"/avis/(CERTFR-\d{4}-AVI-\d+)",
        base="https://www.cert.ssi.gouv.fr/avis/",
    )
    used = "listing HTML (repli, flux RSS indisponible)"
resultat["sources"]["cert_fr_avis"] = {"flux_utilise": used, "entrees": filtrer_recent(entries)}
if not entries:
    resultat["erreurs"].append("cert_fr_avis: aucune entrée récupérée (flux et listing en échec)")

# --- CERT-FR : alertes -------------------------------------------------------
log("CERT-FR alertes")
entries, used = parse_feed_entries([
    "https://www.cert.ssi.gouv.fr/alerte/feed",
    "https://www.cert.ssi.gouv.fr/alerte/feed/",
])
if not entries:
    entries = scrape_listing_fallback(
        "https://www.cert.ssi.gouv.fr/alerte/",
        r"/alerte/(CERTFR-\d{4}-ALE-\d+)",
        base="https://www.cert.ssi.gouv.fr/alerte/",
    )
    used = "listing HTML (repli, flux RSS indisponible)"
resultat["sources"]["cert_fr_alertes"] = {"flux_utilise": used, "entrees": filtrer_recent(entries)}
if not entries:
    resultat["erreurs"].append("cert_fr_alertes: aucune entrée récupérée")

# --- CERT-FR : rapports CTI --------------------------------------------------
log("CERT-FR CTI")
entries, used = parse_feed_entries([
    "https://www.cert.ssi.gouv.fr/cti/feed",
    "https://www.cert.ssi.gouv.fr/cti/feed/",
])
if not entries:
    entries = scrape_listing_fallback(
        "https://www.cert.ssi.gouv.fr/cti/",
        r"/cti/(CERTFR-\d{4}-CTI-\d+)",
        base="https://www.cert.ssi.gouv.fr/cti/",
    )
    used = "listing HTML (repli, flux RSS indisponible)"
resultat["sources"]["cert_fr_cti"] = {"flux_utilise": used, "entrees": filtrer_recent(entries)}
if not entries:
    resultat["erreurs"].append("cert_fr_cti: aucune entrée récupérée")

# --- ANSSI actualités ---------------------------------------------------------
log("ANSSI actualités")
entries, used = parse_feed_entries([
    "https://cyber.gouv.fr/actualites/feed",
    "https://cyber.gouv.fr/actualites.rss",
])
if not entries:
    entries = scrape_listing_fallback(
        "https://cyber.gouv.fr/actualites",
        r'href="(/actualites/[a-z0-9\-]+)"',
        base="https://cyber.gouv.fr",
    )
    used = "listing HTML (repli, flux RSS indisponible)"
resultat["sources"]["anssi_actualites"] = {"flux_utilise": used, "entrees": filtrer_recent(entries)}
if not entries:
    resultat["erreurs"].append("anssi_actualites: aucune entrée récupérée")

# --- CERT-EU -------------------------------------------------------------------
log("CERT-EU")
entries, used = parse_feed_entries([
    "https://cert.europa.eu/publications/security-advisories/rss",
    "https://cert.europa.eu/rss",
])
resultat["sources"]["cert_eu"] = {"flux_utilise": used, "entrees": filtrer_recent(entries)}
if not entries:
    resultat["erreurs"].append("cert_eu: flux non trouvé — vérifier l'URL manuellement, source à faible priorité")

# --- Fuites Infos (registre GitHub, source déjà confirmée accessible) --------
log("Fuites Infos")
try:
    resp = get("https://raw.githubusercontent.com/CedHaurus/fuitesinfos-transparence/main/REGISTRE.md")
    lignes = resp.text.splitlines()
    # Le registre est un changelog Markdown ; on retient les lignes datées des derniers jours.
    date_re = re.compile(r"(20\d{2}-\d{2}-\d{2})")
    recentes = []
    seuil_date = (now - timedelta(days=FENETRE_JOURS)).date()
    for ligne in lignes:
        m = date_re.search(ligne)
        if m:
            try:
                d = datetime.strptime(m.group(1), "%Y-%m-%d").date()
            except ValueError:
                continue
            if d >= seuil_date:
                recentes.append(ligne.strip())
    resultat["sources"]["fuites_infos"] = {
        "flux_utilise": "raw.githubusercontent.com REGISTRE.md",
        "lignes_recentes": recentes[:200],
    }
except Exception as exc:
    log(f"Fuites Infos échoué: {exc}")
    resultat["erreurs"].append(f"fuites_infos: {exc}")
    resultat["sources"]["fuites_infos"] = {"flux_utilise": None, "lignes_recentes": []}


# --- Écriture ------------------------------------------------------------------
with open("latest.json", "w", encoding="utf-8") as f:
    json.dump(resultat, f, ensure_ascii=False, indent=2)
import os
os.makedirs("archive", exist_ok=True)
archive_name = f"archive/{now.strftime('%Y-%m-%d')}.json"
with open(archive_name, "w", encoding="utf-8") as f:
    json.dump(resultat, f, ensure_ascii=False, indent=2)

total_entrees = sum(
    len(v.get("entrees", v.get("lignes_recentes", [])))
    for v in resultat["sources"].values()
)
log(f"Terminé. {total_entrees} entrées collectées au total. {len(resultat['erreurs'])} erreur(s).")
if resultat["erreurs"]:
    for e in resultat["erreurs"]:
        log(f"  - {e}")
