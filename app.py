"""
Content & Website Intelligence Suite - v2.0

Modules (switch in the sidebar):
1. Content Scorer  - scores a draft or live page for SEO, readability, engagement,
                     conversion, social sharing and brand compliance (+ predictive model).
2. Form Finder     - finds pages with contact, whitepaper/download, demo, newsletter,
                     event and job forms - on one page or a whole website.
3. Site Crawler    - crawls a website: pages, URLs, structure, sitemap, status codes,
                     links, downloads, technology and SEO issues with a health score.

Start with:  streamlit run seo.py
Install:     pip install streamlit requests beautifulsoup4 pandas numpy plotly scikit-learn
Optional:    pip install lxml
"""

import hashlib
import io
import json
import re
import time
import gzip
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict, deque
from html import escape
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st
from bs4 import BeautifulSoup

try:
    import lxml  # noqa: F401
    PARSER = "lxml"
except ImportError:
    PARSER = "html.parser"

st.set_page_config(page_title="Content & Website Intelligence", page_icon="🚀", layout="wide")


# ============================================================
# Word lists (English + German)
# ============================================================

def wordset(text):
    return set(text.lower().split())


STOP_EN = wordset("the a an and or but of to in on for with at by from is are was were be been "
                  "it this that these those as you your we our they their not can will")
STOP_DE = wordset("der die das und oder aber ein eine einen einem einer zu im in auf für mit bei "
                  "von ist sind war waren wird werden es diese dieser sie ihr wir unser nicht den "
                  "dem des sich auch als kann")
POWER = wordset("new free proven exclusive essential ultimate secret simple easy fast instant "
                "powerful smart effective best top guide complete surprising sustainable future "
                "neu neue neuer kostenlos exklusiv einfach schnell sofort effektiv beste besten "
                "leitfaden ultimativ nachhaltig nachhaltige zukunft erfolgreich clever smarte")
CURIOSITY = wordset("how why what when which who secret mistakes truth reasons ways tips lessons "
                    "wie warum was wann welche wer geheimnis fehler wahrheit gründe wege tipps")
EMO_POS = wordset("success successful growth win best great love happy easy save saving benefit "
                  "secure safe trust proud strong efficient innovative ready "
                  "erfolg erfolgreich wachstum gewinnen großartig einfach sparen vorteil sicher "
                  "vertrauen stolz stark effizient innovativ begeistert")
EMO_NEG = wordset("risk problem fail failure loss lose costly expensive danger threat mistake "
                  "waste worry stress difficult pressure "
                  "risiko scheitern verlust verlieren teuer gefahr bedrohung verschwendung sorge "
                  "schwierig druck")
CTA_VERBS = wordset("contact download register sign subscribe start get try request book buy order "
                    "discover learn read join call apply schedule watch explore "
                    "kontaktieren kontakt herunterladen registrieren anmelden abonnieren starten "
                    "jetzt holen testen anfragen buchen kaufen bestellen entdecken erfahren lesen "
                    "mitmachen anrufen bewerben vereinbaren ansehen")
BENEFIT = wordset("save saves saving reduce reduces lower increase increases improve improves "
                  "boost faster easier flexible flexibility efficient cost costs budget transparent "
                  "transparency secure sustainable predictable "
                  "sparen spart reduzieren senken steigern verbessern schneller einfacher flexibel "
                  "flexibilität effizient kosten budget transparenz sicher nachhaltig planbar "
                  "entlasten entlastung")
URGENCY = wordset("now today limited deadline last soon hurry immediately "
                  "jetzt heute begrenzt frist letzte bald sofort")
PROOF = wordset("customer customers client clients award awarded certified certificate "
                "testimonial rated trusted partner partners leading platinum iso "
                "kunde kunden kundenreferenz auszeichnung ausgezeichnet zertifiziert zertifikat "
                "referenz führend marktführer")
STORY = wordset("example story case journey experience imagine beispiel geschichte erfahrung")
YOU = wordset("you your yours yourself sie ihr ihre ihren ihrem ihnen du dein deine dich dir euch")
FILLER = wordset("very really basically actually just quite literally somehow certainly "
                 "sehr wirklich eigentlich halt eben quasi irgendwie sozusagen durchaus")
SPAM = wordset("guaranteed miracle unbelievable cash winner garantiert wunder unglaublich gratis")

PASSIVE_EN = re.compile(r"\b(?:is|are|was|were|be|been|being)\s+(?:\w+ly\s+)?\w+(?:ed|en)\b", re.I)
PASSIVE_DE = re.compile(r"\b(?:wird|werden|wurde|wurden|worden)\b", re.I)
WORD_RE = re.compile(r"[^\W_]+(?:[-'’][^\W_]+)*")
MD_IMG = re.compile(r"!\[([^\]]*)\]\(([^)]*)\)")
MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
LIST_RE = re.compile(r"^(?:[-*•]|\d+[.)])\s+")


# ============================================================
# Crawler and form settings
# ============================================================

MODULES = ["📝 Content Scorer", "📨 Form Finder", "🕸 Site Crawler"]
DEFAULT_SITE = "https://www.chg-meridian.com/global-en/"
DEFAULT_PAGE = "https://www.chg-meridian.com/global-en/services/sustainable-leasing/"

CRAWL_HEADERS = dict([
    ("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 ContentScorer/2.0"),
    ("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
    ("Accept-Language", "en-US,en;q=0.9,de;q=0.8"),
])

SKIP_EXT = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".zip", ".rar",
            ".mp4", ".mp3", ".avi", ".mov", ".css", ".js", ".json", ".xml", ".doc", ".docx",
            ".xls", ".xlsx", ".ppt", ".pptx", ".woff", ".woff2", ".ttf", ".eot", ".gz")
DOWNLOAD_EXT = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip")
IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")
SITEMAP_LIMIT = 100000

NON_FIELDS = ("hidden", "submit", "button", "image", "reset", "checkbox", "radio")
PRIVACY_HINTS = ("privacy", "datenschutz", "consent", "einwillig", "gdpr", "dsgvo",
                 "data protection")
CAPTCHA_HINTS = ("recaptcha", "hcaptcha", "h-captcha", "cf-turnstile", "friendly-captcha",
                 "frc-captcha", "altcha", "honeypot")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z][A-Za-z]+")

# order matters: the first matching group wins
FORM_TYPES = [
    ("Whitepaper / download", ("whitepaper", "white-paper", "white paper", "ebook", "e-book",
                               "download", "herunterladen", "leitfaden", "studie", "report",
                               "checklist", "checkliste", "brochure", "broschüre", "factsheet",
                               "datasheet", "datenblatt", "guide")),
    ("Demo / consultation", ("demo", "consultation", "beratung", "termin", "appointment", "quote",
                             "angebot", "callback", "rückruf", "rueckruf", "pricing", "trial")),
    ("Newsletter", ("newsletter", "subscribe", "abonnier", "mailing")),
    ("Event / webinar", ("webinar", "event", "veranstaltung", "seminar", "konferenz",
                         "conference", "registration", "registrierung")),
    ("Job application", ("career", "karriere", "bewerbung", "application", "lebenslauf",
                         "resume", "apply")),
    ("Contact", ("contact", "kontakt", "anfrage", "inquiry", "enquiry", "message", "nachricht",
                 "get in touch", "support", "frage", "question")),
]
LEAD_FORM_TYPES = [name for name, _ in FORM_TYPES] + ["Lead / other"]
UTILITY_FORMS = ("Search", "Login / account")
ALL_FORM_TYPES = LEAD_FORM_TYPES + ["Other"] + list(UTILITY_FORMS)

# (name, signatures, injected by JavaScript / iframe)
FORM_PROVIDERS = [
    ("HubSpot", ("hbspt.forms.create", "hs-form-frame", "share.hsforms.com", "hs-form"), True),
    ("Pardot / Account Engagement", ("go.pardot.com/l/", "pi.pardot.com/l/", "pardot-form"), True),
    ("Salesforce Web-to-Lead", ("webto.salesforce.com", "servlet.webtolead"), False),
    ("Marketo", ("mktoform", "forms2.min.js"), True),
    ("Eloqua", ("elqform", "eloqua.com/e/f"), True),
    ("Typeform", ("typeform.com/to/", "data-tf-widget", "embed.typeform.com"), True),
    ("Google Forms", ("docs.google.com/forms", "forms.gle/"), True),
    ("Microsoft Forms", ("forms.office.com", "forms.microsoft.com"), True),
    ("Jotform", ("jotform.com", "jotfor.ms"), True),
    ("Formstack", ("formstack.com/forms",), True),
    ("Cognito Forms", ("cognitoforms.com",), True),
    ("Zoho Forms", ("forms.zohopublic", "zohoforms"), True),
    ("Mailchimp", ("list-manage.com/subscribe", "mc-embedded-subscribe"), True),
    ("CleverReach", ("cleverreach.com/f/", "cr_form"), True),
    ("Brevo / Sendinblue", ("sibforms.com", "sib-form"), True),
    ("Calendly (booking)", ("calendly.com/",), True),
    ("Contact Form 7", ("wpcf7",), False),
    ("Gravity Forms", ("gform_wrapper", "gform_fields"), False),
    ("WPForms", ("wpforms",), False),
    ("Elementor Forms", ("elementor-form",), False),
    ("Ninja Forms", ("ninja-forms", "nf-form"), False),
]

TECH = [
    ("WordPress", ("wp-content", "wp-includes")),
    ("Drupal", ("drupal-settings-json", "/sites/default/files")),
    ("TYPO3", ("typo3",)),
    ("Sitecore", ("sitecore", "/-/media/")),
    ("Adobe Experience Manager", ("/etc.clientlibs", "/content/dam/")),
    ("Shopify", ("cdn.shopify.com",)),
    ("Wix", ("wixstatic.com",)),
    ("Squarespace", ("squarespace",)),
    ("Webflow", ("webflow",)),
    ("HubSpot CMS", ("hs-sites", "hubspotusercontent")),
    ("Google Tag Manager", ("googletagmanager.com/gtm.js", "googletagmanager.com/ns.html")),
    ("Google Analytics", ("googletagmanager.com/gtag/js", "google-analytics.com")),
    ("Matomo", ("matomo",)),
    ("Hotjar", ("hotjar",)),
    ("HubSpot tracking", ("js.hs-scripts.com", "js.hs-analytics.net")),
    ("LinkedIn Insight Tag", ("snap.licdn.com",)),
    ("Meta Pixel", ("connect.facebook.net",)),
    ("Cookiebot", ("cookiebot",)),
    ("OneTrust", ("onetrust", "cookielaw.org")),
    ("Usercentrics", ("usercentrics",)),
    ("Google reCAPTCHA", ("recaptcha",)),
]

PAGE_TYPES = [
    ("Legal", ("imprint", "impressum", "privacy", "datenschutz", "legal", "terms", "agb",
               "cookie", "disclaimer")),
    ("Contact", ("contact", "kontakt")),
    ("Career", ("career", "karriere", "jobs", "/job")),
    ("Events / webinars", ("event", "webinar", "veranstaltung")),
    ("Downloads / whitepaper", ("download", "whitepaper", "ebook", "e-book", "resources",
                                "ressourcen", "mediathek")),
    ("News / press", ("news", "press", "presse", "newsroom")),
    ("Blog / insights", ("blog", "insight", "magazin", "magazine", "article", "artikel", "stories")),
    ("Products / services", ("product", "produkt", "service", "leistung", "solution",
                             "loesung", "lösung")),
    ("About", ("about", "ueber-uns", "über-uns", "unternehmen", "company", "team", "who-we-are")),
]

SEVERITY = dict([("🔴 Error", 10), ("🟠 Warning", 5), ("🔵 Notice", 2)])

FORM_COLS = ["Page", "Type", "Provider", "Fields", "Required", "Email_field", "Consent",
             "Spam_protection", "Method", "Action", "Button", "Heading", "Field_names",
             "Signature", "JS_embed"]


# ============================================================
# Content goals and channels
# ============================================================

GOALS = dict(
    Blog_article=dict(label="Blog / SEO article", words=(800, 2500),
                      weights=dict(SEO=0.35, Readability=0.20, Engagement=0.20,
                                   Conversion=0.15, Social=0.10)),
    Landing_page=dict(label="Landing / product page", words=(300, 1200),
                      weights=dict(SEO=0.25, Readability=0.15, Engagement=0.15,
                                   Conversion=0.35, Social=0.10)),
    Social_campaign=dict(label="Social campaign post", words=(30, 300),
                         weights=dict(SEO=0.05, Readability=0.20, Engagement=0.35,
                                      Conversion=0.20, Social=0.20)),
    Newsletter=dict(label="Newsletter / email", words=(150, 600),
                    weights=dict(SEO=0.05, Readability=0.25, Engagement=0.30,
                                 Conversion=0.35, Social=0.05)),
    Press_release=dict(label="Press release / news", words=(300, 900),
                       weights=dict(SEO=0.30, Readability=0.20, Engagement=0.20,
                                    Conversion=0.10, Social=0.20)),
)

CHANNELS = dict(
    LinkedIn=dict(chars=(150, 700), tags=(1, 5)),
    X_Twitter=dict(chars=(70, 280), tags=(0, 2)),
    Facebook=dict(chars=(40, 300), tags=(0, 3)),
    Instagram=dict(chars=(100, 500), tags=(3, 15)),
    Website_only=dict(chars=(70, 200), tags=(0, 0)),
)

DEMO = dict(
    headline="5 Ways Sustainable IT Leasing Cuts Costs and CO₂ Emissions",
    meta=("Discover how sustainable IT leasing helps you lower costs, reduce CO₂ emissions "
          "and keep devices up to date. Practical tips for IT and finance teams."),
    slug="/global-en/insights/blog/sustainable-it-leasing/",
    keyword="sustainable IT leasing",
    cta="Request a free consultation",
    teaser=("5 ways sustainable IT leasing cuts costs and CO₂ – from flexible budgets to "
            "carbonZER0 offsetting. Which one fits your IT strategy? #SustainableIT #GreenIT"),
    body="""Rising IT costs and ambitious climate targets put pressure on IT and finance teams. Do you want modern devices without tying up capital – and with a smaller carbon footprint? Sustainable IT leasing makes this possible.

## 1. Pay for use instead of ownership
With sustainable IT leasing, you pay a predictable monthly rate. Your budget stays flexible, and you can upgrade devices when your needs change.

## 2. Offset CO₂ emissions
Every device causes emissions during production, transport and use. With [re.cover](/global-en/services/sustainable-leasing/), these emissions are calculated and offset through certified climate projects.

## 3. Extend the device lifecycle
- Certified data erasure for every returned device
- Refurbishment and remarketing instead of scrapping
- Transparent reporting on reused devices

## 4. Save time in procurement
One partner handles sourcing, rollout and returns. Your IT team saves time and can focus on strategic projects.

## 5. Proof for your ESG report
You receive clear figures for your sustainability reporting. A customer told us: "We now see the CO₂ footprint of our entire IT fleet at a glance."

Ready to make your IT more sustainable? Request a free consultation today.""",
)


# ============================================================
# Text helpers
# ============================================================

def clean(s):
    return " ".join(str(s or "").split())


def text_of(tag):
    return clean(tag.get_text(" ")) if tag else ""


def words_of(text):
    return WORD_RE.findall(text or "")


def first_word(text):
    w = words_of(str(text).lower())
    return w[0] if w else ""


def sentences_of(text):
    parts = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    return [p.strip() for p in parts if len(words_of(p)) >= 3]


def syllables(word):
    return max(1, len(re.findall(r"[aeiouyäöü]+", word.lower())))


def detect_lang(words):
    low = [w.lower() for w in words]
    return "de" if sum(w in STOP_DE for w in low) > sum(w in STOP_EN for w in low) else "en"


def count_in(words_lower, vocab):
    return sum(1 for w in words_lower if w in vocab)


def phrase_count(text, phrase):
    if not phrase or not text:
        return 0
    # negative lookbehind (?<!\w), written in parts so copy & paste cannot break it
    before = "(?" + "<" + r"!\w)"
    pattern = before + re.escape(phrase.lower()) + r"(?!\w)"
    return len(re.findall(pattern, str(text).lower()))


def kw_presence(text, kw):
    """1.0 = exact phrase found, up to 0.6 = some keyword words found."""
    if not kw or not text:
        return 0.0
    if phrase_count(text, kw):
        return 1.0
    parts = [p for p in kw.split() if len(p) > 2]
    if not parts:
        return 0.0
    low = str(text).lower()
    return 0.6 * sum(p in low for p in parts) / len(parts)


def band(v, lo, hi, min_v, max_v):
    """1.0 inside [lo, hi], falling linearly to 0 at min_v / max_v."""
    if lo <= v <= hi:
        return 1.0
    if v < lo:
        return max(0.0, (v - min_v) / (lo - min_v)) if lo > min_v else 0.0
    return max(0.0, (max_v - v) / (max_v - hi)) if max_v > hi else 0.0


def top_terms(words, k=10):
    low = [w.lower() for w in words]
    stop = STOP_EN | STOP_DE
    uni = Counter(w for w in low if len(w) > 3 and w not in stop and not w.isdigit())
    bi = Counter(a + " " + b for a, b in zip(low, low[1:])
                 if a not in stop and b not in stop and len(a) > 2 and len(b) > 2)
    combined = [(t, n) for t, n in bi.most_common(k) if n >= 2] + uni.most_common(k)
    return combined[:k]


def fmt(x):
    x = float(x)
    return format(x, ",.0f") if abs(x) >= 100 else format(x, ",.1f")


def num(x):
    return format(int(x), ",")


def rank_corr(a, b):
    return float(pd.Series(list(a)).rank().corr(pd.Series(list(b)).rank()))


# ============================================================
# URL helpers
# ============================================================

def host_key(netloc):
    h = netloc.lower().split(":")[0]
    return h[4:] if h.startswith("www.") else h


def normalize(url, keep_query=False):
    p = urlparse(url)
    query = ""
    if keep_query and p.query:
        q = [(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith("utm_")]
        query = urlencode(q)
    return urlunparse((p.scheme.lower(), p.netloc.lower(), p.path or "/", "", query, ""))


def same_url(a, b):
    pa, pb = urlparse(a), urlparse(b)
    return (host_key(pa.netloc) == host_key(pb.netloc)
            and pa.path.rstrip("/") == pb.path.rstrip("/") and pa.query == pb.query)


def is_page_url(url):
    p = urlparse(url)
    return p.scheme in ("http", "https") and not p.path.lower().endswith(SKIP_EXT)


def page_type_of(path, is_home):
    if is_home:
        return "Home"
    p = path.lower()
    for name, terms in PAGE_TYPES:
        if any(t in p for t in terms):
            return name
    return "Other"


# ============================================================
# Form detection
# ============================================================

def guess_form_type(blob):
    for name, terms in FORM_TYPES:
        if any(t in blob for t in terms):
            return name
    return ""


def classify_form(form, fields, button, heading, action, labels):
    types = [(f.get("type") or "text").lower() for f in fields]
    names = [(f.get("name") or "").lower() for f in fields]
    parts = []
    for f in fields:
        parts += [f.get("name") or "", f.get("id") or "", f.get("placeholder") or "",
                  f.get("aria-label") or ""]
    cls = form.get("class") or []
    parts += [" ".join(cls) if isinstance(cls, list) else str(cls), form.get("id") or "",
              form.get("name") or "", action, button, heading, labels]
    blob = " ".join(parts).lower()
    has_textarea = any(f.name == "textarea" for f in fields)

    if "password" in types:
        return "Login / account"
    if ("search" in types or (form.get("role") or "") == "search"
            or (len(fields) <= 2 and not has_textarea
                and (any(n in ("q", "s", "query", "search", "suche") for n in names)
                     or "search" in blob or "suche" in blob))):
        return "Search"
    kind = guess_form_type(blob)
    if kind == "Newsletter" and (has_textarea or len(fields) > 4):
        kind = "Contact" if has_textarea else "Lead / other"
    if kind:
        return kind
    if has_textarea:
        return "Contact"
    if "email" in types or any("mail" in n for n in names):
        return "Lead / other"
    return "Other"


def extract_forms(soup, page_url, html_low="", page_hint=""):
    found, providers_seen = [], set()
    for form in soup.find_all("form"):
        fields = [f for f in form.find_all(["input", "textarea", "select"])
                  if not (f.name == "input" and (f.get("type") or "text").lower() in NON_FIELDS)]
        if not fields:
            continue
        btn = (form.find(["button", "input"], attrs=dict(type=re.compile("submit", re.I)))
               or form.find("button"))
        if btn is None:
            button = ""
        elif btn.name == "button":
            button = text_of(btn)
        else:
            button = clean(btn.get("value"))
        heading = text_of(form.find_previous(["h1", "h2", "h3", "h4"]))[:100]
        action = urljoin(page_url, form.get("action") or "")
        labels = " ".join(text_of(lab) for lab in form.find_all("label"))
        form_html = str(form).lower()
        form_text = text_of(form).lower()
        kind = classify_form(form, fields, button, heading, action, labels)

        provider = "HTML form"
        for pname, sigs, _ in FORM_PROVIDERS:
            if any(s in form_html for s in sigs):
                provider = pname
                providers_seen.add(pname)
                break

        field_names = ", ".join(dict.fromkeys(
            clean(f.get("name") or f.get("id") or f.get("placeholder") or f.get("type") or f.name)
            for f in fields))[:150]
        sig = hashlib.md5((kind + "|" + field_names + "|" + urlparse(action).path)
                          .encode("utf-8")).hexdigest()[:10]
        found.append(dict(
            Page=page_url, Type=kind, Provider=provider, Fields=len(fields),
            Required=sum(1 for f in fields if f.has_attr("required")
                         or f.get("aria-required") == "true"),
            Email_field=any((f.get("type") or "").lower() == "email"
                            or "mail" in (f.get("name") or "").lower() for f in fields),
            Consent=any(h in form_text or h in form_html for h in PRIVACY_HINTS),
            Spam_protection=any(h in form_html for h in CAPTCHA_HINTS),
            Method=(form.get("method") or "get").upper(), Action=action, Button=button[:60],
            Heading=heading, Field_names=field_names, Signature=sig, JS_embed=False))

    # forms injected by JavaScript or iframe
    if html_low:
        for pname, sigs, embedded in FORM_PROVIDERS:
            if embedded and pname not in providers_seen and any(s in html_low for s in sigs):
                kind = ("Demo / consultation" if pname.startswith("Calendly")
                        else guess_form_type(page_hint) or "Lead / other")
                found.append(dict(
                    Page=page_url, Type=kind, Provider=pname, Fields=0, Required=0,
                    Email_field=False, Consent=False, Spam_protection=False, Method="",
                    Action="", Button="", Heading="", Field_names="(loaded by JavaScript)",
                    Signature=hashlib.md5((pname + "|" + page_url).encode("utf-8")).hexdigest()[:10],
                    JS_embed=True))
    return found


# ============================================================
# Content input: draft (Markdown) or live URL
# ============================================================

def parse_draft(headline, seo_title, meta, body_md, slug, cta, teaser, has_image, site_host):
    h1s = [clean(headline)] if clean(headline) else []
    headings, lines, list_items = [], [], 0
    images = MD_IMG.findall(body_md or "")
    text = MD_IMG.sub("", body_md or "")
    for raw_line in text.splitlines():
        s = raw_line.strip()
        m = re.match(r"^(#+)\s*(.+)$", s)
        if m:
            (h1s if len(m.group(1)) == 1 else headings).append(clean(m.group(2)))
            continue
        if LIST_RE.match(s):
            list_items += 1
            s = LIST_RE.sub("", s)
        lines.append(s)
    body = "\n".join(lines)
    links = MD_LINK.findall(body)
    internal = sum(1 for _, u in links if u.startswith("/") or (site_host and site_host in u))
    cta_texts = [clean(x) for x in (cta or "").splitlines() if clean(x)]
    cta_texts += [t for t, _ in links if first_word(t) in CTA_VERBS]
    body = MD_LINK.sub(r"\1", body)
    title = clean(seo_title) or (h1s[0] if h1s else "")
    return dict(source="Draft", url="", title=title, meta=clean(meta),
                h1=h1s[0] if h1s else "", h1_count=len(h1s), headings=headings, body=body,
                slug=clean(slug), links_int=internal, links_ext=len(links) - internal,
                images=len(images), images_no_alt=sum(1 for alt, _ in images if not alt.strip()),
                list_items=list_items, cta_texts=cta_texts, og_title=title,
                og_desc=clean(teaser), og_image=bool(has_image), teaser=clean(teaser), forms=[])


@st.cache_data(show_spinner=False, ttl=3600)
def fetch_url(url):
    r = requests.get(url, headers=CRAWL_HEADERS, timeout=25)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, PARSER)

    def meta(key):
        tag = (soup.find("meta", attrs=dict(name=key))
               or soup.find("meta", attrs=dict(property=key)))
        return clean(tag.get("content")) if tag else ""

    title = text_of(soup.title)
    h1s = [text_of(h) for h in soup.find_all("h1")]
    desc, og_title = meta("description"), meta("og:title")
    og_desc, og_image = meta("og:description"), meta("og:image")
    forms = extract_forms(soup, r.url, r.text.lower(),
                          (r.url + " " + title + " " + (h1s[0] if h1s else "")).lower())

    for tag in soup(["script", "style", "noscript", "template", "svg",
                     "nav", "header", "footer", "aside"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup

    blocks = [text_of(t) for t in main.find_all(["p", "li", "blockquote"])]
    body = "\n\n".join(b for b in blocks if len(b) > 1)
    if len(words_of(body)) < 50:
        body = "\n\n".join(clean(x) for x in main.get_text("\n").split("\n") if clean(x))

    host = urlparse(r.url).netloc.lower()
    internal = external = 0
    cta_texts = []
    for a in main.find_all(["a", "button"]):
        label = text_of(a)
        if label and first_word(label) in CTA_VERBS and len(words_of(label)) <= 8:
            cta_texts.append(label)
        href = (a.get("href") or "").strip() if a.name == "a" else ""
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        if urlparse(urljoin(r.url, href)).netloc.lower() == host:
            internal += 1
        else:
            external += 1

    imgs = main.find_all("img")
    return dict(source="URL", url=r.url, title=title, meta=desc,
                h1=h1s[0] if h1s else "", h1_count=len(h1s),
                headings=[text_of(h) for h in main.find_all(["h2", "h3"])],
                body=body, slug=urlparse(r.url).path, links_int=internal, links_ext=external,
                images=len(imgs), images_no_alt=sum(1 for i in imgs if not clean(i.get("alt"))),
                list_items=len(main.find_all("li")), cta_texts=list(dict.fromkeys(cta_texts))[:10],
                og_title=og_title, og_desc=og_desc, og_image=bool(og_image),
                teaser=og_desc or desc, forms=forms)


# ============================================================
# Scoring engine
# ============================================================

def verdict_text(score, brand_issue):
    if score >= 80:
        v = "🟢 Ready to publish – strong campaign"
    elif score >= 65:
        v = "🟡 Good – a few improvements will boost performance"
    elif score >= 50:
        v = "🟠 Needs work before publishing"
    else:
        v = "🔴 Not ready – major gaps"
    return v + (" · 🚫 fix brand terms first" if brand_issue else "")


def analyze(c, keyword, secondary, goal_key, channel, rules, required):
    goal = GOALS[goal_key]
    web = goal_key not in ("Social_campaign", "Newsletter")
    body = c["body"]
    words = words_of(body)
    low = [w.lower() for w in words]
    n = max(len(words), 1)
    sents = sentences_of(body)
    lens = [len(words_of(s)) for s in sents] or [0]
    lang = detect_lang(words)
    headline = c["h1"] or c["title"]
    hl_low = [w.lower() for w in words_of(headline)]
    suggestions = top_terms(words)
    first100 = " ".join(words[:100])

    kw = clean(keyword).lower()
    kw_auto = False
    if not kw and suggestions:
        kw, kw_auto = suggestions[0][0], True
    kw_label = ("'" + kw + "'" + (" (auto-detected)" if kw_auto else "")) if kw else "a focus keyword"

    checks = []

    def add(cat, name, ratio, pts, tip, detail=""):
        ratio = float(min(max(ratio, 0.0), 1.0))
        checks.append(dict(Category=cat, Check=name, Score=round(ratio * pts, 1), Max=pts,
                           Status="✅" if ratio >= 0.8 else "⚠️" if ratio >= 0.4 else "❌",
                           Detail=str(detail), Tip=tip if ratio < 0.999 else ""))

    # ---------- statistics ----------
    asl = float(np.mean(lens))
    asw = sum(syllables(w) for w in words) / n
    ease = 180 - asl - 58.5 * asw if lang == "de" else 206.835 - 1.015 * asl - 84.6 * asw
    ease = float(min(max(ease, 0), 100))
    long_sents = [s for s in sents if len(words_of(s)) > 25]
    long_share = len(long_sents) / max(len(sents), 1)
    passive = [s for s in sents if (PASSIVE_DE if lang == "de" else PASSIVE_EN).search(s)]
    passive_share = len(passive) / max(len(sents), 1)
    paragraphs = [p for p in re.split(r"\n\s*\n", body) if words_of(p)]
    if len(paragraphs) <= 1:
        paragraphs = [p for p in body.split("\n") if words_of(p)]
    par_avg = n / max(len(paragraphs), 1)
    fillers = count_in(low, FILLER)
    kw_count = phrase_count(body, kw)
    kw_len = max(len(kw.split()), 1)
    density = kw_count * kw_len / n * 100
    pos, neg = count_in(low, EMO_POS), count_in(low, EMO_NEG)
    emo_share = (pos + neg) / n * 100
    positivity = pos / (pos + neg) if pos + neg else 0.5
    you100 = count_in(low, YOU) / n * 100
    questions = body.count("?")
    benefit100 = count_in(low, BENEFIT) / n * 100
    urgency = count_in(low, URGENCY)
    urgency100 = urgency / n * 100
    numbers = len(re.findall(r"\d+(?:[.,]\d+)*", body))
    percents = len(re.findall(r"\d+(?:[.,]\d+)?\s*%", body))
    quotes = len(re.findall(r"[„“\"”«»]", body)) // 2
    proof = count_in(low, PROOF) + percents + quotes
    story = count_in(low, STORY) + quotes
    excl = body.count("!") + headline.count("!")
    caps = sum(1 for w in words if len(w) > 4 and w.isupper() and "-" not in w
               and not any(ch.isdigit() for ch in w))
    spam = count_in(low, SPAM)
    curious = headline.strip().endswith("?") or count_in(hl_low, CURIOSITY) > 0
    hw = len(hl_low)

    # ---------- SEO ----------
    S = "SEO"
    tl = len(c["title"])
    add(S, "Title length", band(tl, 30, 60, 5, 90), 10,
        "Write a title of 30–60 characters so Google doesn't cut it off.", str(tl) + " characters")
    add(S, "Keyword in title", kw_presence(c["title"], kw), 10,
        "Put " + kw_label + " into the title.")
    pos_title = c["title"].lower().find(kw) if kw else -1
    add(S, "Keyword near start of title", 1.0 if 0 <= pos_title <= tl / 2 else 0.0, 4,
        "Move the keyword into the first half of the title.")
    add(S, "Exactly one H1", 1.0 if c["h1_count"] == 1 else 0.4 if c["h1_count"] > 1 else 0.0, 6,
        "Use exactly one main headline (H1).", str(c["h1_count"]) + " H1")
    add(S, "Keyword in H1", kw_presence(c["h1"], kw), 6, "Use " + kw_label + " in the H1.")
    add(S, "Keyword in first 100 words", kw_presence(first100, kw), 8,
        "Mention " + kw_label + " in the first paragraph.")
    target_count = max(1, int(round(0.015 * n / kw_len)))
    add(S, "Keyword density", band(density, 0.5, 2.5, 0, 5), 8,
        "Use the keyword naturally about " + str(target_count) + " times (0.5–2.5 %).",
        format(density, ".1f") + " % (" + str(kw_count) + "×)")
    lo, hi = goal["words"]
    add(S, "Content length", band(n, lo, hi, lo * 0.3, hi * 2.5), 10,
        "Aim for " + str(lo) + "–" + str(hi) + " words for a " + goal["label"] + ".",
        str(len(words)) + " words")
    if web:
        ml = len(c["meta"])
        add(S, "Meta description length", band(ml, 120, 160, 40, 220) if ml else 0.0, 8,
            "Write a meta description of 120–160 characters with a clear benefit.",
            str(ml) + " characters")
        add(S, "Keyword in meta description", kw_presence(c["meta"], kw), 5,
            "Mention " + kw_label + " in the meta description.")
        slug = c["slug"]
        slug_ok = 0.0
        if slug:
            kw_words = kw.split()
            slug_ok = (0.4 * (len(slug) <= 75)
                       + 0.3 * (slug == slug.lower() and " " not in slug and "_" not in slug)
                       + 0.3 * (sum(w in slug.lower() for w in kw_words) / len(kw_words)
                                if kw_words else 0))
        add(S, "URL slug", slug_ok, 5,
            "Use a short, lowercase URL with hyphens that contains the keyword.", slug or "no URL")
        hc = len(c["headings"])
        need = max(1.0, n / 300)
        add(S, "Subheadings (H2/H3)", band(hc / need, 0.8, 4, 0, 8), 6,
            "Add a subheading about every 300 words (" + str(int(round(need))) + " recommended).",
            str(hc) + " subheadings")
        add(S, "Keyword in a subheading",
            1.0 if kw and any(kw in h.lower() for h in c["headings"]) else 0.0, 4,
            "Use the keyword or a close variant in at least one subheading.")
        add(S, "Internal links", band(c["links_int"], 2, 60, 0, 200), 5,
            "Link to at least 2 related pages on your own site.", str(c["links_int"]) + " internal")
        add(S, "External links", 1.0 if c["links_ext"] >= 1 else 0.3, 2,
            "Cite at least one trustworthy external source.", str(c["links_ext"]) + " external")
    if c["images"]:
        add(S, "Image alt texts", (c["images"] - c["images_no_alt"]) / c["images"], 4,
            "Add descriptive alt text to every image.",
            str(c["images_no_alt"]) + " of " + str(c["images"]) + " without alt")
    elif goal_key != "Newsletter":
        add(S, "Images in content", 0.0, 4, "Add at least one relevant image with alt text.", "none")
    if secondary:
        all_txt = " ".join([c["title"], c["meta"], " ".join(c["headings"]), body])
        found = [s for s in secondary if phrase_count(all_txt, s)]
        add(S, "Secondary keywords", len(found) / len(secondary), 5,
            "Also cover: " + ", ".join(s for s in secondary if s not in found) + ".",
            str(len(found)) + " of " + str(len(secondary)))

    # ---------- Readability ----------
    R = "Readability"
    ease_name = "Amstad (German Flesch)" if lang == "de" else "Flesch Reading Ease"
    add(R, "Reading ease", band(ease, 50, 100, 10, 101), 14,
        "Use shorter words and sentences.", ease_name + ": " + format(ease, ".0f"))
    add(R, "Average sentence length", band(asl, 8, 20, 3, 35), 10,
        "Keep sentences at 8–20 words on average.", format(asl, ".1f") + " words")
    add(R, "Long sentences (> 25 words)", band(long_share, 0, 0.15, 0, 0.5), 8,
        "Split long sentences – see the Text analysis tab.",
        str(len(long_sents)) + " of " + str(len(sents)))
    add(R, "Paragraph length", band(par_avg, 10, 80, 0, 220), 6,
        "Break the text into paragraphs of max. 3–4 sentences.",
        format(par_avg, ".0f") + " words per paragraph")
    add(R, "Passive voice", band(passive_share, 0, 0.15, 0, 0.5), 5,
        "Prefer active voice: 'We reduce costs' instead of 'Costs are reduced'.",
        format(passive_share * 100, ".0f") + " % of sentences")
    add(R, "Filler words", band(fillers / n * 100, 0, 1, 0, 4), 4,
        "Remove filler words such as 'very', 'really', 'eigentlich'.", str(fillers) + " found")
    if goal_key != "Social_campaign":
        add(R, "Scannable lists", min(c["list_items"] / 3, 1), 5,
            "Add a bullet list for key points or benefits.", str(c["list_items"]) + " list items")

    # ---------- Engagement (viral potential) ----------
    E = "Engagement"
    add(E, "Headline length (words)", band(hw, 6, 13, 2, 22), 8,
        "Headlines with 6–13 words get the most clicks.", str(hw) + " words")
    add(E, "Headline length (characters)", band(len(headline), 30, 70, 10, 120), 4,
        "Keep the headline under 70 characters so it fits social previews.",
        str(len(headline)) + " characters")
    add(E, "Number in headline", 1.0 if re.search(r"\d", headline) else 0.0, 6,
        "Use a number, e.g. '5 ways …' or '30 % less …'.")
    add(E, "Power word in headline", min(count_in(hl_low, POWER), 1), 7,
        "Add a strong word such as 'proven', 'simple', 'new' or 'sustainable'.")
    add(E, "Curiosity trigger", 1.0 if curious else 0.0, 5,
        "Spark curiosity with 'How', 'Why' or a question.")
    add(E, "Emotional words", band(emo_share, 1, 5, 0, 10), 7,
        "Add words that show impact (success, risk, save, trust).",
        format(emo_share, ".1f") + " % of words")
    add(E, "Positive tone", band(positivity, 0.55, 1, 0.2, 1.01), 4,
        "Balance problems with positive outcomes.", format(positivity * 100, ".0f") + " % positive")
    add(E, "Reader focus ('you')", band(you100, 1, 6, 0, 12), 6,
        "Address the reader directly ('you', 'Sie', 'Ihr').",
        format(you100, ".1f") + " per 100 words")
    add(E, "Question to the reader", min(questions, 1), 3,
        "Ask the reader at least one question.", str(questions) + " questions")
    add(E, "Stories, examples or quotes", min(story / 2, 1), 5,
        "Add an example, customer story or quote.", str(story) + " found")

    # ---------- Conversion (promotional strength) ----------
    C = "Conversion"
    tail_cta = count_in(low[int(len(low) * 0.7):], CTA_VERBS)
    cta_ratio = 1.0 if c["cta_texts"] else 0.6 if tail_cta else 0.0
    add(C, "Call to action", cta_ratio, 12,
        "Add a clear call to action (button or link) at the end.",
        ", ".join(c["cta_texts"][:3]) or ("CTA wording in text" if tail_cta else "none"))
    best = 0.0
    for t in c["cta_texts"]:
        best = max(best, 0.6 * (first_word(t) in CTA_VERBS)
                   + 0.4 * band(len(words_of(t)), 2, 6, 0, 12))
    add(C, "CTA wording", best, 5, "Start the CTA with an action verb and keep it to 2–6 words.")
    add(C, "Benefits", band(benefit100, 1, 6, 0, 12), 8,
        "Spell out concrete benefits (save, reduce, faster, flexible).",
        format(benefit100, ".1f") + " per 100 words")
    add(C, "Urgency", 0.4 if urgency == 0 else band(urgency100, 0.1, 2.5, 0, 6), 4,
        "Give a reason to act now (deadline, 'today') – without overdoing it.",
        str(urgency) + " found")
    add(C, "Social proof", min(proof / 3, 1), 8,
        "Add proof: customer names, quotes, awards, certificates or results in %.",
        str(proof) + " signals")
    add(C, "Concrete numbers", band(numbers, 3, 60, 0, 150), 5,
        "Back up claims with figures (%, €, time saved).", str(numbers) + " numbers")
    value_early = any(w in BENEFIT for w in low[:50]) or (kw and kw in " ".join(low[:50]))
    add(C, "Value proposition early", 1.0 if value_early else 0.0, 5,
        "State the main benefit in the first 2–3 sentences.")
    hype = (max(0, excl / max(len(sents), 1) - 0.1) * 3
            + max(0, caps / n - 0.02) * 20 + spam * 0.25)
    add(C, "No hype or spam signals", 1 - min(hype, 1), 5,
        "Reduce exclamation marks, ALL CAPS and hype words.",
        str(excl) + " '!' · " + str(caps) + " CAPS · " + str(spam) + " hype words")
    if c["source"] == "URL" and goal_key in ("Landing_page", "Blog_article"):
        lead = [f for f in c.get("forms", []) if f["Type"] not in UTILITY_FORMS]
        add(C, "Lead form on page", 1.0 if lead else 0.0, 6,
            "Add a contact, demo or download form so visitors can convert on the page.",
            ", ".join(sorted(set(f["Type"] for f in lead))) or "none")

    # ---------- Social ----------
    So = "Social"
    ch = CHANNELS[channel]
    teaser = c["teaser"]
    add(So, "Share image (og:image)", 1.0 if c["og_image"] else 0.0, 8,
        "Add a share image (1200 × 627 px). Posts with images get more engagement.")
    add(So, "Share title", 1.0 if c["og_title"] else 0.0, 4, "Set an Open Graph title for sharing.")
    lo2, hi2 = ch["chars"]
    add(So, "Teaser / share text length", band(len(teaser), lo2, hi2, 0, hi2 * 2) if teaser else 0.0,
        6, "Write a " + channel.replace("_", " ") + " teaser of " + str(lo2) + "–" + str(hi2)
        + " characters.", str(len(teaser)) + " characters")
    if c["source"] == "Draft":
        tags = len(re.findall(r"#\w+", teaser))
        tlo, thi = ch["tags"]
        add(So, "Hashtags", band(tags, tlo, thi, 0 if tlo == 0 else -1, thi + 5), 3,
            "Use " + str(tlo) + "–" + str(thi) + " relevant hashtags.", str(tags) + " hashtags")

    # ---------- Brand compliance ----------
    fields = dict(Title=c["title"], Meta=c["meta"], H1=c["h1"],
                  Subheadings=" ".join(c["headings"]), Body=body, Teaser=teaser, URL=c["slug"])
    all_text = " ".join(fields.values())
    brand_hits = []
    for old, new in rules:
        count = phrase_count(all_text, old)
        if count:
            where = ", ".join(name for name, txt in fields.items() if phrase_count(txt, old))
            brand_hits.append(dict(Term=old, Replace_with=new, Count=count, Found_in=where))
    missing_req = [t for t in required if not phrase_count(all_text, t)]
    penalty = min(25, 8 * len(brand_hits) + 4 * len(missing_req))

    # ---------- Aggregation ----------
    df = pd.DataFrame(checks)
    agg = df.groupby("Category")[["Score", "Max"]].sum()
    cat_scores = (agg["Score"] / agg["Max"] * 100).round(0)
    weights = pd.Series(goal["weights"])
    weights = weights[weights.index.isin(cat_scores.index)]
    weights = weights / weights.sum()
    raw_overall = float((cat_scores[weights.index] * weights).sum())
    overall = max(0.0, min(100.0, raw_overall - penalty))
    df["Gain"] = df.apply(lambda r: (r["Max"] - r["Score"]) / agg.loc[r["Category"], "Max"]
                          * 100 * weights.get(r["Category"], 0), axis=1).round(1)

    places = [("Title", c["title"]), ("Meta description", c["meta"]), ("H1", c["h1"]),
              ("First 100 words", first100), ("Subheadings", " ".join(c["headings"])),
              ("URL slug", c["slug"].replace("-", " ").replace("/", " "))]
    placement = [(name, "✅" if kw_presence(t, kw) >= 1 else "⚠️ partly"
                  if kw_presence(t, kw) > 0 else "❌") for name, t in places]

    features = dict(word_count=len(words), title_length=tl, meta_length=len(c["meta"]),
                    headline_words=hw, headline_has_number=int(bool(re.search(r"\d", headline))),
                    headline_power_words=count_in(hl_low, POWER), headline_curiosity=int(curious),
                    reading_ease=ease, avg_sentence_length=asl, long_sentence_share=long_share,
                    passive_share=passive_share, subheadings=len(c["headings"]),
                    list_items=c["list_items"], internal_links=c["links_int"],
                    external_links=c["links_ext"], images=c["images"], keyword_density=density,
                    emotion_share=emo_share, positivity=positivity, you_per_100=you100,
                    questions=questions, benefit_per_100=benefit100, urgency_per_100=urgency100,
                    proof_signals=proof, numbers=numbers, cta_present=cta_ratio)
    for cat, val in cat_scores.items():
        features["score_" + cat.lower()] = float(val)
    features["score_overall"] = raw_overall

    stats = dict(lang=lang, words=len(words), sentences=len(sents), avg_sentence=asl,
                 reading_ease=ease, ease_name=ease_name, kw=kw, kw_auto=kw_auto,
                 kw_count=kw_count, density=density, reading_time=len(words) / 220)
    highlights = dict(long=sorted(long_sents, key=lambda s: -len(words_of(s)))[:8],
                      passive=passive[:8], fillers=sorted(set(w for w in low if w in FILLER)),
                      suggestions=suggestions, placement=placement)

    return dict(checks=df, cats=cat_scores, weights=weights, overall=overall, penalty=penalty,
                brand_hits=brand_hits, missing_req=missing_req, stats=stats, features=features,
                highlights=highlights, headline=headline,
                verdict=verdict_text(overall, bool(brand_hits)))


def score_headline(h, kw):
    hl = [w.lower() for w in words_of(h)]
    parts = [
        ("6–13 words", band(len(hl), 6, 13, 2, 22), 20),
        ("Under 70 characters", band(len(h), 30, 70, 10, 120), 10),
        ("Number", 1.0 if re.search(r"\d", h) else 0.0, 15),
        ("Power word", min(count_in(hl, POWER), 1), 15),
        ("Curiosity / question",
         1.0 if h.strip().endswith("?") or count_in(hl, CURIOSITY) else 0.0, 10),
        ("Emotional word", min(count_in(hl, EMO_POS | EMO_NEG), 1), 10),
        ("Keyword", kw_presence(h, kw) if kw else 0.5, 15),
        ("Reader focus", min(count_in(hl, YOU), 1), 5),
    ]
    total = sum(r * w for _, r, w in parts)
    return round(total), ", ".join(name for name, r, _ in parts if r < 0.8) or "–"


# ============================================================
# Predictive model (learns from your own data)
# ============================================================

def read_any_csv(raw):
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return pd.read_csv(io.BytesIO(raw), sep=None, engine="python", encoding=enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("Unknown file encoding")


def build_training(hist, cols, target, goal_key, channel, fetch_limit, progress):
    feats, ys, fetched, skipped = [], [], 0, 0
    total = len(hist)
    for i, (_, row) in enumerate(hist.iterrows()):
        progress.progress((i + 1) / total, text="Analysing row " + str(i + 1) + " of " + str(total))

        def val(name):
            col = cols.get(name)
            if not col or pd.isna(row[col]):
                return ""
            return str(row[col])

        y = pd.to_numeric(row[target], errors="coerce")
        if pd.isna(y):
            skipped += 1
            continue
        if val("body"):
            content = parse_draft(val("title"), "", val("meta"), val("body"),
                                  urlparse(val("url")).path, "", "", False, "")
        elif val("url") and fetched < fetch_limit:
            try:
                content = fetch_url(val("url"))
                fetched += 1
            except Exception:
                skipped += 1
                continue
        else:
            skipped += 1
            continue
        res = analyze(content, val("keyword"), [], goal_key, channel, [], [])
        feats.append(res["features"])
        ys.append(float(y))
    return pd.DataFrame(feats).fillna(0), pd.Series(ys, name=target), fetched, skipped


def train_model(X, y, log_target):
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.metrics import mean_absolute_error, r2_score
    from sklearn.model_selection import KFold, cross_val_predict

    yt = np.log1p(y.clip(lower=0)) if log_target else y
    model = RandomForestRegressor(n_estimators=300, min_samples_leaf=2, random_state=42, n_jobs=-1)
    folds = KFold(n_splits=max(2, min(5, len(X) // 4)), shuffle=True, random_state=42)
    pred = cross_val_predict(model, X, yt, cv=folds)
    pred_real = np.expm1(pred) if log_target else pred
    metrics = dict(r2=float(r2_score(yt, pred)), mae=float(mean_absolute_error(y, pred_real)),
                   spearman=rank_corr(pred_real, y))
    model.fit(X, yt)
    importance = pd.Series(model.feature_importances_, index=X.columns).sort_values(ascending=False)
    return model, metrics, importance, pred_real


def predict_current(m, features):
    X = pd.DataFrame([features]).reindex(columns=m["features"], fill_value=0)
    p = float(m["model"].predict(X)[0])
    if m["log"]:
        p = float(np.expm1(p))
    return p, float((m["y"] < p).mean() * 100)


def benchmark(m, features, top_n=10):
    X, y = m["X"], m["y"]
    top = X[y.values >= y.quantile(0.75)]
    rows = []
    for f in m["importance"].index[:top_n]:
        cur = float(features.get(f, 0))
        med_all, med_top = float(X[f].median()), float(top[f].median())
        if med_top > med_all * 1.05 + 1e-9 and cur < med_top:
            hint = "⬆️ Increase"
        elif med_top < med_all * 0.95 - 1e-9 and cur > med_top:
            hint = "⬇️ Decrease"
        else:
            hint = "✅ On track"
        rows.append(dict(Feature=f, Your_content=round(cur, 2), Median_all=round(med_all, 2),
                         Median_top_25pct=round(med_top, 2), Hint=hint))
    return pd.DataFrame(rows)


# ============================================================
# Website crawler
# ============================================================

def report(progress, value, text):
    if progress:
        progress(value, text)


def load_robots(base):
    rp = RobotFileParser()
    info = dict(url=base + "/robots.txt", found=False, sitemaps=[], disallow=0)
    try:
        r = requests.get(info["url"], headers=CRAWL_HEADERS, timeout=10)
        if r.ok and "html" not in r.headers.get("Content-Type", "").lower():
            lines = r.text.splitlines()
            rp.parse(lines)
            info["found"] = True
            info["sitemaps"] = [line.split(":", 1)[1].strip() for line in lines
                                if line.lower().startswith("sitemap:")]
            info["disallow"] = sum(1 for line in lines if line.lower().startswith("disallow:")
                                   and line.split(":", 1)[1].strip())
        else:
            rp.parse([])
    except Exception:
        rp.parse([])
    return rp, info


def read_sitemap(url, limit=SITEMAP_LIMIT, depth=0):
    """Page URLs from a sitemap (follows sitemap indexes, supports .gz)."""
    out = []
    if limit <= 0:
        return out
    try:
        r = requests.get(url, headers=CRAWL_HEADERS, timeout=20)
        r.raise_for_status()
        content = r.content
        if content[:2] == b"\x1f\x8b":
            content = gzip.decompress(content)
        root = ET.fromstring(content)
    except Exception:
        return out
    locs = [e.text.strip() for e in root.iter() if e.tag.endswith("loc") and e.text]
    if root.tag.endswith("sitemapindex") and depth < 2:
        for sm in locs:
            out += read_sitemap(sm, limit - len(out), depth + 1)
            if len(out) >= limit:
                break
    else:
        out = locs
    return out[:limit]


def new_row(url, depth, via):
    return dict(URL=url, Final_URL=url, Status=0, Status_group="", Redirect="", Depth=depth,
                Found_via=via, Section="", L1="", L2="", Page_type="", Title="", Title_len=0,
                Meta_description="", Meta_len=0, H1_count=0, H1="", H2_count=0, Words=0,
                Internal_links=0, External_links=0, Inbound_links=0, Images=0, Images_no_alt=0,
                Forms=0, Form_types="", Indexable=False, Noindex=False, Canonical="",
                Canonical_other=False, Lang="", Hreflang=0, Schema="", OG_image=False,
                In_sitemap=False, Response_ms=0, Size_KB=0.0, Parsed=False, Hash="", Note="")


def parse_page(soup, html, url, host, keep_query):
    low_html = html.lower()

    def meta(key):
        tag = (soup.find("meta", attrs=dict(name=key))
               or soup.find("meta", attrs=dict(property=key)))
        return clean(tag.get("content")) if tag else ""

    title = text_of(soup.title)
    desc = meta("description")
    robots_meta = meta("robots").lower()
    h1s = [text_of(h) for h in soup.find_all("h1")]
    h2_count = len(soup.find_all("h2"))
    canon = ""
    ctag = soup.find("link", rel="canonical")
    if ctag and ctag.get("href"):
        canon = normalize(urljoin(url, ctag["href"].strip()), keep_query)
    html_tag = soup.find("html")
    lang = clean(html_tag.get("lang")) if html_tag else ""
    hreflang = len(soup.find_all("link", hreflang=True))
    generator = meta("generator")
    og_image = bool(meta("og:image"))

    schema = []
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or s.get_text() or "")
        except Exception:
            continue
        stack = [data]
        while stack and len(schema) < 50:
            d = stack.pop()
            if isinstance(d, list):
                stack += d
            elif isinstance(d, dict):
                t = d.get("@type")
                if isinstance(t, list):
                    schema += [str(x) for x in t]
                elif t:
                    schema.append(str(t))
                if "@graph" in d:
                    stack.append(d["@graph"])

    page_hint = (url + " " + title + " " + (h1s[0] if h1s else "")).lower()
    forms = extract_forms(soup, url, low_html, page_hint)
    imgs = soup.find_all("img")
    no_alt = sum(1 for i in imgs if not clean(i.get("alt")))

    internal, external = set(), set()
    downloads, leads, emails, phones = [], [], set(), set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        low_href = href.lower()
        label = text_of(a)[:80]
        if low_href.startswith("mailto:"):
            addr = unquote(href[7:].split("?")[0]).strip().lower()
            if "@" in addr:
                emails.add(addr)
            continue
        if low_href.startswith("tel:"):
            number = clean(unquote(href[4:]))
            if number:
                phones.add(number)
            continue
        if not href or low_href.startswith(("#", "javascript:", "sms:", "data:")):
            continue
        target = normalize(urljoin(url, href), keep_query)
        pu = urlparse(target)
        if pu.scheme not in ("http", "https"):
            continue
        if pu.path.lower().endswith(DOWNLOAD_EXT):
            downloads.append(dict(Page=url, File=target, Link_text=label,
                                  Type=pu.path.rsplit(".", 1)[-1].upper()))
        if host_key(pu.netloc) == host:
            internal.add(target)
            kind = guess_form_type((pu.path + " " + label).lower())
            if kind and is_page_url(target):
                leads.append(dict(Source=url, URL=target, Link_text=label, Likely_type=kind))
        else:
            external.add(target)

    tech = set(name for name, sigs in TECH if any(s in low_html for s in sigs))
    if generator:
        tech.add("Generator: " + generator[:40])

    for tag in soup(["script", "style", "noscript", "template", "svg", "iframe"]):
        tag.decompose()
    full_text = soup.get_text(" ")
    for e in EMAIL_RE.findall(full_text):
        e = e.lower().strip(".")
        if not e.endswith(IMG_EXT) and "example" not in e:
            emails.add(e)
    for tag in soup(["nav", "header", "footer", "aside"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = clean(main.get_text(" "))
    words = len(words_of(text))

    row = dict(Title=title, Title_len=len(title), Meta_description=desc, Meta_len=len(desc),
               H1_count=len(h1s), H1=h1s[0][:120] if h1s else "", H2_count=h2_count, Words=words,
               Internal_links=len(internal), External_links=len(external), Images=len(imgs),
               Images_no_alt=no_alt, Forms=len(forms),
               Form_types=", ".join(sorted(set(f["Type"] for f in forms))),
               Noindex="noindex" in robots_meta, Canonical=canon,
               Canonical_other=bool(canon) and not same_url(canon, url), Lang=lang,
               Hreflang=hreflang, Schema=", ".join(sorted(set(schema))), OG_image=og_image,
               Hash=hashlib.md5(text.lower().encode("utf-8")).hexdigest() if words >= 50 else "")
    return dict(row=row, forms=forms, internal=internal, external=external, downloads=downloads,
                leads=leads, emails=emails, phones=phones, tech=tech, schema=set(schema))


def status_group(row):
    s = row["Status"]
    if s == 0:
        return "Unreachable"
    if s >= 500:
        return "5xx server error"
    if s >= 400:
        return "4xx not found / blocked"
    if row["Redirect"]:
        return "3xx redirected"
    if not row["Parsed"]:
        return "2xx not HTML / skipped"
    return "2xx OK"


def crawl_site(start_url, max_pages=100, max_depth=3, delay=0.2, respect_robots=True,
               stay_in_path=True, keep_query=False, use_sitemap=True, progress=None):
    t_start = time.time()
    start_url = clean(start_url)
    if not start_url.startswith(("http://", "https://")):
        start_url = "https://" + start_url
    p0 = urlparse(start_url)
    if not p0.netloc:
        raise ValueError("Please enter a valid URL, e.g. https://www.example.com/")
    base = p0.scheme + "://" + p0.netloc
    host = host_key(p0.netloc)
    scope = p0.path.rstrip("/") if stay_in_path else ""
    start = normalize(start_url, keep_query)
    page_limit = max_pages if max_pages and max_pages > 0 else None
    depth_limit = max_depth if max_depth and max_depth > 0 else None

    report(progress, 0.0, "Reading robots.txt …")
    rp, robots = load_robots(base)
    if not respect_robots:
        rp = None

    sitemap_all = []
    if use_sitemap:
        report(progress, 0.0, "Reading XML sitemap … (large sitemaps can take a few seconds)")
        for sm in robots["sitemaps"] or [base + "/sitemap.xml"]:
            sitemap_all += read_sitemap(sm, SITEMAP_LIMIT - len(sitemap_all))
            if len(sitemap_all) >= SITEMAP_LIMIT:
                break
        sitemap_all = list(dict.fromkeys(
            normalize(u, keep_query) for u in sitemap_all
            if host_key(urlparse(u).netloc) == host and is_page_url(u)))

    def in_scope(u):
        pu = urlparse(u)
        if host_key(pu.netloc) != host:
            return False
        return not scope or pu.path.rstrip("/") == scope or pu.path.startswith(scope + "/")

    queue = deque([(start, 0, "Start")])
    queued, done = set([start]), set()
    pages, forms, downloads, leads, blocked = [], [], [], [], []
    inbound, ext_domains = Counter(), Counter()
    emails, phones, tech, schema = Counter(), Counter(), Counter(), Counter()
    sources = defaultdict(list)
    internal_pages, external_all = set(), set()
    seeded = False

    session = requests.Session()
    session.headers.update(CRAWL_HEADERS)

    while page_limit is None or len(pages) < page_limit:
        if not queue:
            # links are exhausted: add sitemap pages that no link pointed to
            if use_sitemap and not seeded and pages:
                seeded = True
                for u in sitemap_all:
                    if u not in queued and in_scope(u):
                        queued.add(u)
                        queue.append((u, -1, "Sitemap"))
            if not queue:
                break
        url, depth, via = queue.popleft()
        if rp is not None and not rp.can_fetch("*", url):
            blocked.append(url)
            continue

        report(progress, len(pages) / max_pages,
               "Crawling " + str(len(pages) + 1) + " / " + str(max_pages) + " · " + url[:90])

        row = new_row(url, depth, via)
        soup, html = None, ""
        try:
            r = session.get(url, timeout=20)
            row["Status"] = r.status_code
            row["Response_ms"] = int(r.elapsed.total_seconds() * 1000)
            row["Size_KB"] = round(len(r.content) / 1024, 1)
            final = normalize(r.url, keep_query)
            row["Final_URL"] = final
            if final != url:
                row["Redirect"] = (str(r.history[0].status_code) if r.history else "3xx") + " → " + final
            ctype = r.headers.get("Content-Type", "").lower()
            if r.status_code >= 400:
                row["Note"] = "HTTP error " + str(r.status_code)
            elif "html" not in ctype:
                row["Note"] = "Not HTML (" + (ctype.split(";")[0] or "unknown") + ")"
            elif host_key(urlparse(final).netloc) != host:
                row["Note"] = "Redirects to another host"
            elif final != url and final in done:
                row["Note"] = "Redirects to a page that was already crawled"
            else:
                html = r.text
                soup = BeautifulSoup(html, PARSER)
        except Exception as e:
            row["Note"] = "Unreachable: " + str(e)[:100]

        if soup is None:
            pages.append(row)
            time.sleep(delay)
            continue

        final = row["Final_URL"]
        if depth == 0 and scope:  # start page redirected (e.g. /global-en/ -> /en/)
            fpath = urlparse(final).path.rstrip("/")
            if not (fpath == scope or fpath.startswith(scope + "/")):
                scope = fpath
        done.add(url)
        done.add(final)
        queued.add(final)

        info = parse_page(soup, html, final, host, keep_query)
        row.update(info["row"])
        row["Parsed"] = True
        pages.append(row)
        forms += info["forms"]
        downloads += info["downloads"]
        leads += info["leads"]
        emails.update(info["emails"])
        phones.update(info["phones"])
        tech.update(info["tech"])
        schema.update(info["schema"])
        external_all |= info["external"]
        ext_domains.update(set(host_key(urlparse(e).netloc) for e in info["external"]))

        for t in info["internal"]:
            inbound[t] += 1
            if len(sources[t]) < 5:
                sources[t].append(final)
            if is_page_url(t):
                internal_pages.add(t)
                if (t not in queued and in_scope(t) and depth >= 0
                        and (depth_limit is None or depth < depth_limit)
                        and (keep_query or not urlparse(t).query)):

                    queued.add(t)
                    queue.append((t, depth + 1, "Link"))
        time.sleep(delay)

    sitemap_scope = [u for u in sitemap_all if in_scope(u)]
    sm_set = set(sitemap_scope)
    for row in pages:
        path = urlparse(row["Final_URL"]).path
        rel = path[len(scope):] if scope and path.startswith(scope) else path
        segs = [s for s in rel.split("/") if s]
        row["Section"] = row["L1"] = segs[0] if segs else "(home)"
        row["L2"] = segs[1] if len(segs) > 1 else "(index)"
        row["Page_type"] = page_type_of(rel, not segs)
        row["Inbound_links"] = inbound.get(row["URL"], 0) + (
            inbound.get(row["Final_URL"], 0) if row["Final_URL"] != row["URL"] else 0)
        row["In_sitemap"] = row["URL"] in sm_set or row["Final_URL"] in sm_set
        row["Indexable"] = bool(row["Parsed"] and 200 <= row["Status"] < 300 and not row["Noindex"]
                                and not row["Canonical_other"] and not row["Redirect"])
        row["Status_group"] = status_group(row)

    crawled = set(r["URL"] for r in pages) | set(r["Final_URL"] for r in pages)
    return dict(
        start=start, host=host, scope=scope, elapsed=time.time() - t_start,
        pages=pd.DataFrame(pages, columns=list(new_row("", 0, "").keys())),
        forms=pd.DataFrame(forms, columns=FORM_COLS),
        downloads=pd.DataFrame(downloads, columns=["Page", "File", "Link_text", "Type"]),
        lead_links=pd.DataFrame(leads, columns=["Source", "URL", "Link_text", "Likely_type"]),
        emails=emails, phones=phones, tech=tech, schema=schema, ext_domains=ext_domains,
        robots=robots, sitemap_total=len(sitemap_all), sitemap_urls=sitemap_scope,
        internal_discovered=len(set(u for u in internal_pages if in_scope(u)) | crawled),
        external_unique=len(external_all), queue_left=len(queue), blocked=blocked,
        sources=dict(sources))


def site_issues(pages):
    ok = pages[pages["Parsed"]]
    n_all, n_ok = len(pages), len(ok)
    rows, examples = [], dict()
    E, W, N = list(SEVERITY)
    path = ok["Final_URL"].map(lambda u: urlparse(u).path)

    def add(sev, name, sub, base, tip, show=None):
        rows.append(dict(Severity=sev, Issue=name, Pages=len(sub),
                         Share=round(len(sub) / max(base, 1) * 100, 1), Tip=tip))
        if len(sub):
            examples[name] = sub[show or ["URL", "Title"]].head(300)

    bad = pages[(pages["Status"] >= 400) | (pages["Status"] == 0)]
    add(E, "Broken or unreachable pages", bad, n_all,
        "Fix or remove links to these pages, or redirect them.", ["URL", "Status", "Note"])
    add(E, "Not on HTTPS", ok[ok["Final_URL"].str.startswith("http://")], n_ok,
        "Serve every page over HTTPS.")
    add(E, "Missing title", ok[ok["Title"] == ""], n_ok, "Give every page a unique title tag.")
    has_title = ok[ok["Title"] != ""]
    add(W, "Duplicate titles", has_title[has_title.duplicated("Title", keep=False)]
        .sort_values("Title"), n_ok, "Write a unique title for every page.")
    add(N, "Title too long (> 60 characters)", ok[ok["Title_len"] > 60], n_ok,
        "Shorten titles so Google does not cut them off.", ["URL", "Title", "Title_len"])
    add(N, "Title too short (< 30 characters)", ok[(ok["Title_len"] > 0) & (ok["Title_len"] < 30)],
        n_ok, "Use more descriptive titles with the main keyword.", ["URL", "Title", "Title_len"])
    add(W, "Missing meta description", ok[ok["Meta_len"] == 0], n_ok,
        "Write a meta description of 120–160 characters.")
    has_meta = ok[ok["Meta_len"] > 0]
    add(W, "Duplicate meta descriptions",
        has_meta[has_meta.duplicated("Meta_description", keep=False)]
        .sort_values("Meta_description"), n_ok, "Write a unique description for every page.",
        ["URL", "Meta_description"])
    add(N, "Meta description too long (> 160)", ok[ok["Meta_len"] > 160], n_ok,
        "Shorten the description to 120–160 characters.", ["URL", "Meta_len"])
    add(W, "Missing H1", ok[ok["H1_count"] == 0], n_ok, "Add one main headline (H1).")
    add(N, "Multiple H1", ok[ok["H1_count"] > 1], n_ok, "Use exactly one H1 per page.",
        ["URL", "H1_count"])
    add(W, "Thin content (< 200 words)", ok[ok["Words"] < 200], n_ok,
        "Expand the content or merge thin pages.", ["URL", "Title", "Words"])
    has_hash = ok[ok["Hash"] != ""]
    add(W, "Duplicate content", has_hash[has_hash.duplicated("Hash", keep=False)]
        .sort_values("Hash"), n_ok, "Merge duplicate pages or set a canonical URL.")
    add(N, "Noindex pages", ok[ok["Noindex"]], n_ok,
        "Check that these pages should really be hidden from Google.")
    add(N, "Canonical points to another URL", ok[ok["Canonical_other"]], n_ok,
        "Check that the canonical URL is correct.", ["URL", "Canonical"])
    add(N, "Internal redirects", pages[pages["Redirect"] != ""], n_all,
        "Link directly to the final URL.", ["URL", "Redirect"])
    add(W, "Slow response (> 1.5 s)", ok[ok["Response_ms"] > 1500], n_ok,
        "Improve server speed, caching or page weight.", ["URL", "Response_ms"])
    add(N, "Large HTML (> 500 KB)", ok[ok["Size_KB"] > 500], n_ok,
        "Reduce inline code and page weight.", ["URL", "Size_KB"])
    add(N, "Deep pages (click depth > 3)", ok[ok["Depth"] > 3], n_ok,
        "Link important pages closer to the home page.", ["URL", "Depth"])
    add(N, "Weak internal linking (≤ 1 inbound link)",
        ok[(ok["Inbound_links"] <= 1) & (ok["Depth"] != 0)], n_ok,
        "Add internal links from related pages.", ["URL", "Inbound_links", "Depth"])
    add(N, "Images without alt text", ok[ok["Images_no_alt"] > 0], n_ok,
        "Add alt text to meaningful images.", ["URL", "Images", "Images_no_alt"])
    add(N, "Missing share image (og:image)", ok[~ok["OG_image"].astype(bool)], n_ok,
        "Add an Open Graph image for social sharing.")
    add(N, "Missing lang attribute", ok[ok["Lang"] == ""], n_ok,
        "Set the language, e.g. .")
    add(N, "No structured data", ok[ok["Schema"] == ""], n_ok,
        "Add schema.org markup (Organization, Article, BreadcrumbList …).")
    add(N, "Long URL (> 115 characters)", ok[ok["Final_URL"].str.len() > 115], n_ok,
        "Use shorter, readable URLs.", ["URL"])
    add(N, "URL with uppercase or underscore",
        ok[path.map(lambda p: p != p.lower() or "_" in p)], n_ok,
        "Use lowercase URLs with hyphens.", ["URL"])

    df = pd.DataFrame(rows)
    order = dict(zip(SEVERITY, range(len(SEVERITY))))
    df = df.assign(_o=df["Severity"].map(order)).sort_values(["_o", "Pages"], ascending=[True, False])
    df = df.drop(columns="_o")
    lost = sum(SEVERITY[r["Severity"]] * min(1.0, r["Share"] / 100) for _, r in df.iterrows())
    health = max(0.0, 100.0 - lost) if n_ok else 0.0
    return df, examples, health


# ============================================================
# Charts and previews
# ============================================================

def gauge(value, title):
    color = ("#2e7d32" if value >= 80 else "#f9a825" if value >= 65
             else "#ef6c00" if value >= 50 else "#c62828")
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=round(value), title=dict(text=title),
        gauge=dict(axis=dict(range=[0, 100]), bar=dict(color=color),
                   steps=[dict(range=[0, 50], color="#fdecea"),
                          dict(range=[50, 65], color="#fff4e5"),
                          dict(range=[65, 80], color="#fffbe6"),
                          dict(range=[80, 100], color="#edf7ed")])))
    fig.update_layout(height=280, margin=dict(l=20, r=20, t=60, b=10))
    return fig


def serp_preview(title, url, desc):
    t = title if len(title) <= 60 else title[:57] + "…"
    d = desc if len(desc) <= 160 else desc[:157] + "…"
    d = d or "(no meta description – Google will pick text from the page)"
    box = ("<div>"
           "<div>" + escape(url) + "</div>"
           "<div>" + escape(t) + "</div>"
           "<div>" + escape(d) + "</div></div>")
    st.markdown(box, unsafe_allow_html=True)


def counter_df(counter, label, value="Pages"):
    return pd.DataFrame(counter.most_common(), columns=[label, value])


# ============================================================
# Shared UI helpers
# ============================================================

def send_to_scorer(url):
    try:
        st.session_state["url_content"] = fetch_url(url)
    except Exception as e:
        st.session_state["send_error"] = "Could not load " + url + ": " + str(e)
        return
    st.session_state["live_url"] = url
    st.session_state["input_mode"] = "Live URL"
    st.session_state["app_mode"] = MODULES[0]


def send_box(urls, prefix):
    choices = list(dict.fromkeys(urls))
    if not choices:
        return
    st.markdown("**📝 Analyse a page in the Content Scorer**")
    a, b = st.columns([4, 1])
    sel = a.selectbox("Page", choices, key=prefix + "_send_sel", label_visibility="collapsed")
    b.button("Send to Content Scorer", key=prefix + "_send", on_click=send_to_scorer, args=(sel,))


def crawl_settings(prefix, default_pages):
    sb = st.sidebar
    url = sb.text_input("Website URL", DEFAULT_SITE, key=prefix + "_url")
    unlimited = sb.checkbox("♾️ No page limit (crawl the whole site)", False,
                            key=prefix + "_unlimited")
    max_pages = sb.number_input("Max. pages", min_value=1, value=default_pages, step=50,
                                key=prefix + "_max", disabled=unlimited,
                                help="No upper limit. Tick 'No page limit' to crawl every page.")
    all_depths = sb.checkbox("♾️ No click-depth limit", False, key=prefix + "_alldepth")
    max_depth = sb.slider("Max. click depth", 1, 10, 4, key=prefix + "_depth",
                          disabled=all_depths)
    with sb.expander("⚙️ Crawl options"):
        delay = st.slider("Delay between requests (s)", 0.0, 3.0, 0.2, 0.1, key=prefix + "_delay")
        stay = st.checkbox("Stay inside the start path", True, key=prefix + "_stay",
                           help="E.g. only /global-en/ and not the other language versions.")
        robots = st.checkbox("Respect robots.txt", True, key=prefix + "_robots")
        sitemap = st.checkbox("Read XML sitemap", True, key=prefix + "_sitemap")
        query = st.checkbox("Include URLs with ?parameters", False, key=prefix + "_query")
    if unlimited:
        sb.warning("Large sites can take hours. Do not click anything in the app while "
                   "the crawl runs – Streamlit would restart it.")
    return dict(url=url, max_pages=0 if unlimited else int(max_pages),
                max_depth=0 if all_depths else max_depth, delay=delay,
                stay=stay, robots=robots, sitemap=sitemap, query=query)


def run_crawl(cfg):
    bar = st.progress(0.0, text="Starting …")
    try:
        res = crawl_site(cfg["url"], cfg["max_pages"], cfg["max_depth"], cfg["delay"],
                         cfg["robots"], cfg["stay"], cfg["query"], cfg["sitemap"],
                         progress=lambda v, t: bar.progress(min(max(v, 0.0), 1.0), text=t))
    except Exception as e:
        bar.empty()
        st.error("Crawl failed: " + str(e))
        return None
    bar.empty()
    return res


def crawl_warnings(res):
    pages = res["pages"]
    st.caption("Crawl of **" + res["start"] + "** · " + str(len(pages)) + " pages in "
               + format(res["elapsed"], ".0f") + " s"
               + (" · scope: " + res["scope"] if res["scope"] else ""))
    if pages.empty:
        st.error("No page could be crawled. The start URL may be blocked by robots.txt ("
                 + str(len(res["blocked"])) + " URLs blocked). Untick 'Respect robots.txt' "
                 "only if you are allowed to crawl this site.")
        return
    first = pages.iloc[0]
    if not first["Parsed"]:
        st.error("The start page could not be analysed – status " + str(first["Status"]) + ". "
                 + str(first["Note"]) + ". The site may block automated requests.")
    if res["queue_left"]:
        st.warning("Page limit reached – " + num(res["queue_left"]) + " more URLs are waiting. "
                   "Increase 'Max. pages' to crawl more.")
    if res["blocked"]:
        st.info(num(len(res["blocked"])) + " URLs were skipped because robots.txt disallows them.")


# ============================================================
# Module 1: Content Scorer
# ============================================================

def render_content_scorer():
    st.sidebar.title("📝 Content Scorer")
    mode = st.sidebar.radio("Input", ["Draft text", "Live URL"], horizontal=True, key="input_mode")
    goal_key = st.sidebar.selectbox("Content type / goal", list(GOALS),
                                    format_func=lambda g: GOALS[g]["label"])
    channel = st.sidebar.selectbox("Main promotion channel", list(CHANNELS),
                                   format_func=lambda x: x.replace("_", " "))
    keyword = st.sidebar.text_input("Focus keyword", DEMO["keyword"])
    secondary_text = st.sidebar.text_input("Secondary keywords (comma-separated)", "CO₂, lifecycle")
    with st.sidebar.expander("🏷 Brand rules", expanded=True):
        rules_text = st.text_area("Outdated term -> replacement (one per line)",
                                  "carbonZER0 -> re.cover\ncarbonZERO -> re.cover")
        required_text = st.text_input("Required terms (comma-separated)", "")

    secondary = [s.strip().lower() for s in secondary_text.split(",") if s.strip()]
    required = [s.strip() for s in required_text.split(",") if s.strip()]
    rules = []
    for line in rules_text.splitlines():
        parts = re.split(r"\s*(?:->|→|=>)\s*", line.strip(), maxsplit=1)
        if parts and parts[0]:
            rules.append((parts[0], parts[1] if len(parts) > 1 else ""))

    st.title("📝 Content Performance Scorer")
    st.caption("Scores content for SEO, readability, engagement (viral potential), conversion "
               "(promotional strength) and social sharing – and tells you what to improve.")

    site_host = ""
    if mode == "Draft text":
        with st.form("draft"):
            a, b = st.columns([3, 2])
            headline = a.text_input("Headline (H1)", DEMO["headline"])
            seo_title = b.text_input("SEO title (optional – defaults to the headline)", "")
            meta = st.text_area("Meta description", DEMO["meta"], height=70)
            body_md = st.text_area("Body text – Markdown supported: ## subheading, - bullet, "
                                   "[link](url), ![alt](image)", DEMO["body"], height=320)
            c1, c2, c3 = st.columns(3)
            slug = c1.text_input("URL slug", DEMO["slug"])
            cta = c2.text_input("Call to action (button text)", DEMO["cta"])
            site_host = c3.text_input("Your domain (for internal links)", "chg-meridian.com")
            a, b = st.columns([3, 1])
            teaser = a.text_area("Social teaser / share text", DEMO["teaser"], height=90)
            has_image = b.checkbox("Share image available", value=True)
            st.form_submit_button("🔍 Score content", type="primary")
        content = parse_draft(headline, seo_title, meta, body_md, slug, cta, teaser,
                              has_image, site_host)
    else:
        st.session_state.setdefault("live_url", DEFAULT_PAGE)
        url = st.text_input("Page URL", key="live_url")
        if st.button("🔍 Fetch & score", type="primary"):
            try:
                with st.spinner("Loading page …"):
                    st.session_state["url_content"] = fetch_url(url.strip())
            except Exception as e:
                st.error("Could not load the page: " + str(e))
        content = st.session_state.get("url_content")

    result = (analyze(content, keyword, secondary, goal_key, channel, rules, required)
              if content else None)
    model_info = st.session_state.get("model")

    tabs = st.tabs(["🎯 Score", "🛠 What to improve", "📋 All checks", "✍️ Text analysis",
                    "🆎 Headline tester", "🤖 Predictive model"])

    # ---------- Tab 1: Score ----------
    with tabs[0]:
        if result is None:
            st.info("Enter content or fetch a URL to see the scores.")
        else:
            left, right = st.columns([2, 3])
            with left:
                st.plotly_chart(gauge(result["overall"], "Overall score"))
                st.markdown("### " + result["verdict"])
                if result["penalty"]:
                    st.error("Brand compliance: −" + str(result["penalty"]) + " points "
                             "(see 'What to improve').")
            with right:
                cats = result["cats"].reset_index()
                cats.columns = ["Category", "Score"]
                fig = px.line_polar(cats, r="Score", theta="Category", line_close=True,
                                    range_r=[0, 100])
                fig.update_traces(fill="toself")
                fig.update_layout(height=340, margin=dict(l=40, r=40, t=30, b=30))
                st.plotly_chart(fig)

            labels = dict(SEO="SEO", Readability="Readability", Engagement="Engagement (viral)",
                          Conversion="Conversion (promo)", Social="Social sharing")
            cols = st.columns(len(result["cats"]))
            for col, (cat, val) in zip(cols, result["cats"].items()):
                weight = result["weights"].get(cat, 0) * 100
                col.metric(labels.get(cat, cat), str(int(val)) + " / 100",
                           help="Weight for this content type: " + format(weight, ".0f") + " %")

            s = result["stats"]
            k = st.columns(5)
            k[0].metric("Words", fmt(s["words"]))
            k[1].metric("Reading time", format(s["reading_time"], ".1f") + " min")
            k[2].metric(s["ease_name"], format(s["reading_ease"], ".0f"))
            k[3].metric("Keyword density", format(s["density"], ".1f") + " %",
                        help="Keyword: " + s["kw"] + (" (auto-detected)" if s["kw_auto"] else ""))
            k[4].metric("Language detected", s["lang"].upper())

            if model_info:
                p, pct = predict_current(model_info, result["features"])
                st.success("🤖 Predicted **" + model_info["target"] + "**: **" + fmt(p)
                           + "** – better than **" + format(pct, ".0f")
                           + " %** of your past content.")
            else:
                st.caption("💡 Train the model in the 🤖 tab to predict real results "
                           "(e.g. pageviews or leads) based on your own data.")

            st.subheader("Google search preview")
            preview_url = content["url"] or (("https://" + site_host if site_host else "")
                                             + content["slug"])
            serp_preview(content["title"], preview_url, content["meta"])

            if content["source"] == "URL":
                st.subheader("📨 Forms on this page")
                fdf = with_hints(pd.DataFrame(content.get("forms", []), columns=FORM_COLS))
                if fdf.empty:
                    st.caption("No forms found. Forms loaded by JavaScript may not be visible.")
                else:
                    st.dataframe(fdf[["Type", "Provider", "Fields", "Email_field", "Consent",
                                      "Spam_protection", "Button", "Hints"]], hide_index=True)

    # ---------- Tab 2: What to improve ----------
    with tabs[1]:
        if result is None:
            st.info("No content analysed yet.")
        else:
            if result["brand_hits"]:
                st.error("🚫 Outdated brand terms found – replace them before publishing:")
                st.dataframe(pd.DataFrame(result["brand_hits"]), hide_index=True)
            if result["missing_req"]:
                st.warning("Required terms missing: " + ", ".join(result["missing_req"]))

            recs = result["checks"]
            recs = recs[recs["Gain"] > 0].sort_values("Gain", ascending=False).copy()
            if recs.empty:
                st.success("Nothing left to improve. ✅")
            else:
                top5 = float(recs.head(5)["Gain"].sum())
                a, b = st.columns(2)
                a.metric("Current score", fmt(result["overall"]))
                b.metric("Estimated score after the top 5 fixes",
                         fmt(min(100, result["overall"] + top5)), "+" + format(top5, ".1f"))
                st.subheader("Prioritised to-do list")
                for _, r in recs.head(12).iterrows():
                    prio = ("🔴 High" if r["Gain"] >= 3 else "🟠 Medium" if r["Gain"] >= 1.5
                            else "🟢 Low")
                    now = (" *Now: " + r["Detail"] + "*") if r["Detail"] else ""
                    st.markdown("- **" + prio + " · " + r["Category"] + " – " + r["Check"]
                                + "** (+" + format(r["Gain"], ".1f") + " pts): " + r["Tip"] + now)

            sugg = result["highlights"]["suggestions"]
            if sugg:
                st.subheader("Keyword ideas from your text")
                st.write(", ".join(t + " (" + str(n) + "×)" for t, n in sugg))

    # ---------- Tab 3: All checks ----------
    with tabs[2]:
        if result is None:
            st.info("No content analysed yet.")
        else:
            df = result["checks"].copy()
            df["Percent"] = (df["Score"] / df["Max"] * 100).round(0)
            cat_filter = st.multiselect("Category", sorted(df["Category"].unique()))
            if cat_filter:
                df = df[df["Category"].isin(cat_filter)]
            st.dataframe(df[["Status", "Category", "Check", "Percent", "Score", "Max", "Detail",
                             "Tip"]], hide_index=True, height=560,
                         column_config=dict(Percent=st.column_config.ProgressColumn(
                             "Score %", min_value=0, max_value=100, format="%d")))

    # ---------- Tab 4: Text analysis ----------
    with tabs[3]:
        if result is None:
            st.info("No content analysed yet.")
        else:
            hl = result["highlights"]
            a, b = st.columns(2)
            with a:
                st.subheader("Keyword placement")
                st.caption("Keyword: " + result["stats"]["kw"])
                st.dataframe(pd.DataFrame(hl["placement"], columns=["Place", "Found"]),
                             hide_index=True)
                st.subheader("Filler words found")
                st.write(", ".join(hl["fillers"]) if hl["fillers"] else "None ✅")
            with b:
                st.subheader("Most frequent terms")
                if hl["suggestions"]:
                    terms = pd.DataFrame(hl["suggestions"], columns=["Term", "Count"])
                    fig = px.bar(terms, x="Count", y="Term", orientation="h", text_auto=True)
                    fig.update_layout(yaxis=dict(autorange="reversed"), height=330,
                                      margin=dict(l=10, r=10, t=10, b=10))
                    st.plotly_chart(fig)
            st.subheader("Long sentences to split (> 25 words)")
            if hl["long"]:
                for s in hl["long"]:
                    st.markdown("- " + s + " *(" + str(len(words_of(s))) + " words)*")
            else:
                st.write("None ✅")
            st.subheader("Possible passive sentences")
            if hl["passive"]:
                for s in hl["passive"]:
                    st.markdown("- " + s)
            else:
                st.write("None ✅")

    # ---------- Tab 5: Headline A/B tester ----------
    with tabs[4]:
        st.subheader("Compare headline variants")
        base = result["headline"] if result else DEMO["headline"]
        variants_text = st.text_area("One headline per line", "\n".join([
            base,
            "How sustainable IT leasing saves money",
            "Sustainable IT leasing: 5 proven ways to cut costs and CO₂",
            "Why is your IT fleet costing you more than you think?",
        ]), height=150)
        variants = [v.strip() for v in variants_text.splitlines() if v.strip()]
        if variants:
            kw_ab = clean(keyword).lower()
            rows = []
            for v in variants:
                score, missing = score_headline(v, kw_ab)
                rows.append(dict(Headline=v, Score=score, Characters=len(v), Missing=missing))
            ab = pd.DataFrame(rows).sort_values("Score", ascending=False)
            st.success("🏆 Best variant: **" + ab.iloc[0]["Headline"] + "** ("
                       + str(ab.iloc[0]["Score"]) + " / 100)")
            st.dataframe(ab, hide_index=True,
                         column_config=dict(Score=st.column_config.ProgressColumn(
                             "Score", min_value=0, max_value=100, format="%d")))
            st.caption("For real A/B results, test the top 2 variants as LinkedIn posts or email "
                       "subject lines, then add the results to your training data.")

    # ---------- Tab 6: Predictive model ----------
    with tabs[5]:
        st.subheader("Learn from your own performance data")
        st.markdown(
            "Upload past content with a **result metric** (pageviews, clicks, CTR, leads, shares). "
            "The app computes the same 30+ features for each row and trains a **Random Forest** "
            "that learns what works for *your* audience.\n\n"
            "- At least **20 rows** are needed. 100+ give much better results.\n"
            "- Provide **body text**, or a **URL column** (the pages are then fetched "
            "automatically).\n"
            "- Sources: GA4 page report, Search Console, LinkedIn analytics, newsletter tool."
        )
        template = pd.DataFrame(dict(
            Title=["5 Ways Sustainable IT Leasing Cuts Costs", "Our new office in Romania"],
            Meta=["Discover how sustainable IT leasing …", "We are growing in Southeast Europe …"],
            Body=["Full article text …", "Full article text …"],
            Keyword=["sustainable IT leasing", "Romania"],
            URL=["https://www.example.com/blog/a/", "https://www.example.com/news/b/"],
            Pageviews=[1840, 320],
        ))
        st.download_button("⬇️ Download template CSV",
                           template.to_csv(index=False).encode("utf-8-sig"),
                           "training_template.csv", "text/csv", key="dl_template")

        up = st.file_uploader("Historical content with results (CSV)", type=["csv"], key="hist")
        if up is not None:
            try:
                hist = read_any_csv(up.getvalue())
            except Exception as e:
                hist = None
                st.error("The file could not be read: " + str(e))
            if hist is not None:
                st.dataframe(hist.head(), hide_index=True)
                options = ["(none)"] + list(hist.columns)
                numeric = [col for col in hist.columns
                           if pd.to_numeric(hist[col], errors="coerce").notna().mean() > 0.8]

                def guess(names):
                    for i, o in enumerate(options):
                        if str(o).strip().lower() in names:
                            return i
                    return 0

                def pick(container, label, names):
                    choice = container.selectbox(label, options, index=guess(names))
                    return None if choice == "(none)" else choice

                if not numeric:
                    st.error("No numeric column found for the target metric.")
                else:
                    m1 = st.columns(3)
                    target = m1[0].selectbox("Target metric (what to predict)", numeric,
                                             index=len(numeric) - 1)
                    col_title = pick(m1[1], "Title column",
                                     ["title", "titel", "headline", "page title"])
                    col_body = pick(m1[2], "Body text column", ["body", "text", "content", "inhalt"])
                    m2 = st.columns(3)
                    col_meta = pick(m2[0], "Meta description column",
                                    ["meta", "meta description", "description"])
                    col_kw = pick(m2[1], "Keyword column", ["keyword", "focus keyword"])
                    col_url = pick(m2[2], "URL column", ["url", "adresse", "address", "page"])
                    m3 = st.columns(2)
                    fetch_limit = m3[0].number_input("Max. URLs to fetch (rows without body text)",
                                                     0, 500, 100)
                    log_target = m3[1].checkbox("Log-transform target (recommended for traffic "
                                                "and clicks)", value=True)

                    if st.button("🤖 Train model", type="primary"):
                        cols_map = dict(title=col_title, body=col_body, meta=col_meta,
                                        keyword=col_kw, url=col_url)
                        progress = st.progress(0.0, text="Starting …")
                        X, y, fetched, skipped = build_training(hist, cols_map, target, goal_key,
                                                                channel, int(fetch_limit), progress)
                        if len(X) < 20:
                            st.error("Only " + str(len(X)) + " usable rows. At least 20 are "
                                     "needed (skipped: " + str(skipped) + ").")
                        else:
                            try:
                                model, metrics, importance, pred = train_model(X, y, log_target)
                                st.session_state["model"] = dict(
                                    model=model, features=list(X.columns), log=log_target, X=X,
                                    y=y, target=target, metrics=metrics, importance=importance,
                                    pred=pred, heuristic=rank_corr(X["score_overall"], y),
                                    fetched=fetched, skipped=skipped)
                                st.rerun()
                            except ImportError:
                                st.error("scikit-learn is missing. Install it with: "
                                         "pip install scikit-learn")

        if model_info:
            st.divider()
            st.subheader("Model results – target: " + model_info["target"])
            mt = model_info["metrics"]
            k = st.columns(4)
            k[0].metric("Rows used", str(len(model_info["y"])))
            k[1].metric("R² (cross-validated)", format(mt["r2"], ".2f"))
            k[2].metric("Rank correlation – model", format(mt["spearman"], ".2f"))
            k[3].metric("Rank correlation – rule score", format(model_info["heuristic"], ".2f"),
                        help="How well the rule-based overall score alone ranks your past content")
            rho = mt["spearman"]
            if rho >= 0.5:
                st.success("Good model: it ranks your content reliably.")
            elif rho >= 0.3:
                st.warning("Moderate model: useful for comparing drafts, not for exact numbers.")
            else:
                st.error("Weak model: add more rows, or the result depends on factors not in the "
                         "text (budget, channel, timing, topic demand).")

            a, b = st.columns(2)
            imp = model_info["importance"].head(15).reset_index()
            imp.columns = ["Feature", "Importance"]
            fig = px.bar(imp, x="Importance", y="Feature", orientation="h",
                         title="What drives " + model_info["target"])
            fig.update_layout(yaxis=dict(autorange="reversed"), height=460)
            a.plotly_chart(fig)
            comp = pd.DataFrame(dict(Actual=model_info["y"].values, Predicted=model_info["pred"]))
            fig = px.scatter(comp, x="Actual", y="Predicted", opacity=0.6,
                             title="Predicted vs. actual (cross-validated)")
            b.plotly_chart(fig)

            if result:
                p, pct = predict_current(model_info, result["features"])
                st.success("🤖 Predicted " + model_info["target"] + " for the current content: **"
                           + fmt(p) + "** – better than **" + format(pct, ".0f")
                           + " %** of your past content.")
                st.subheader("Your content vs. your top 25 % content")
                st.dataframe(benchmark(model_info, result["features"]), hide_index=True)
            if st.button("🗑 Reset model"):
                del st.session_state["model"]
                st.rerun()


# ============================================================
# Module 2: Form Finder
# ============================================================

def form_hints(r):
    if r["JS_embed"]:
        return "Loaded by JavaScript – check the fields in a browser"
    if r["Type"] in UTILITY_FORMS:
        return ""
    tips = []
    if not r["Email_field"]:
        tips.append("no email field")
    if not r["Consent"]:
        tips.append("no privacy / consent text")
    if not r["Spam_protection"]:
        tips.append("no spam protection found")
    if r["Fields"] > 7:
        tips.append(str(r["Fields"]) + " fields – fewer fields convert better")
    if not r["Button"] or first_word(r["Button"]) in ("submit", "send", "senden", "absenden", "ok"):
        tips.append("generic button text")
    if r["Method"] == "GET":
        tips.append("uses GET instead of POST")
    return "; ".join(tips) or "✅ looks good"


def with_hints(forms):
    if forms.empty:
        return forms.assign(Hints=pd.Series(dtype=str))
    return forms.assign(Hints=forms.apply(form_hints, axis=1))


def form_summary(forms):
    """Merge forms that repeat on many pages (same signature)."""
    if forms.empty:
        return forms
    out = forms.groupby("Signature").agg(
        Type=("Type", "first"), Provider=("Provider", "first"), Fields=("Fields", "first"),
        Button=("Button", "first"), Field_names=("Field_names", "first"),
        Consent=("Consent", "max"), Spam_protection=("Spam_protection", "max"),
        Hints=("Hints", "first"), Pages=("Page", "nunique"), Example_page=("Page", "first"),
    ).reset_index()
    return out.sort_values("Pages", ascending=False)


def render_form_finder():
    st.sidebar.title("📨 Form Finder")
    where = st.sidebar.radio("Search in", ["Single page", "Whole website"], key="ff_scope")
    st.title("📨 Form Finder")
    st.caption("Finds contact, whitepaper / download, demo, newsletter, event and job forms – "
               "on one page or on a whole website.")

    # ---------- single page ----------
    if where == "Single page":
        url = st.text_input("Page URL", DEFAULT_PAGE, key="ff_page_url")
        if st.button("🔍 Find forms", type="primary", key="ff_page_go"):
            try:
                with st.spinner("Loading page …"):
                    st.session_state["ff_page"] = fetch_url(url.strip())
            except Exception as e:
                st.error("Could not load the page: " + str(e))
        c = st.session_state.get("ff_page")
        if not c:
            st.info("Enter a page URL and click 'Find forms'.")
            return
        forms = with_hints(pd.DataFrame(c["forms"], columns=FORM_COLS))
        st.markdown("**" + c["title"] + "** · " + c["url"])
        if forms.empty:
            st.warning("No forms found on this page. Forms loaded by JavaScript may not be "
                       "visible to this tool.")
            return
        k = st.columns(3)
        k[0].metric("Forms found", len(forms))
        k[1].metric("Lead forms", int(forms["Type"].isin(LEAD_FORM_TYPES).sum()))
        k[2].metric("Loaded by JavaScript", int(forms["JS_embed"].sum()))
        st.dataframe(forms.drop(columns=["Signature"]), hide_index=True)
        st.download_button("⬇️ Download forms CSV", forms.to_csv(index=False).encode("utf-8-sig"),
                           "forms_page.csv", "text/csv", key="ff_page_dl")
        return

    # ---------- whole website ----------
    cfg = crawl_settings("ff", 100)
    types_wanted = st.sidebar.multiselect("Form types to show", ALL_FORM_TYPES,
                                          default=LEAD_FORM_TYPES, key="ff_types")
    if st.sidebar.button("🕸 Search website", type="primary", key="ff_go"):
        res = run_crawl(cfg)
        if res:
            st.session_state["site_crawl"] = res

    res = st.session_state.get("site_crawl")
    if not res:
        st.info("Enter a website URL in the sidebar and click 'Search website'. "
                "Results are shared with the Site Crawler module.")
        return
    crawl_warnings(res)
    pages, forms = res["pages"], with_hints(res["forms"])
    if pages.empty:
        return

    lead = forms[forms["Type"].isin(LEAD_FORM_TYPES)]
    k = st.columns(6)
    k[0].metric("Pages crawled", num(len(pages)))
    k[1].metric("Pages with lead forms", num(lead["Page"].nunique()))
    k[2].metric("Lead forms found", num(len(lead)))
    k[3].metric("Unique forms", num(forms["Signature"].nunique()))
    k[4].metric("JavaScript forms", num(int(forms["JS_embed"].sum())))
    k[5].metric("Emails found", num(len(res["emails"])))

    view = forms[forms["Type"].isin(types_wanted)]
    text = st.text_input("Search in URL, heading, fields or button", key="ff_search")
    if text and not view.empty:
        mask = view.astype(str).apply(
            lambda col: col.str.contains(text, case=False, regex=False)).any(axis=1)
        view = view[mask]

    t1, t2, t3, t4 = st.tabs(["📄 Pages with forms", "🧩 Unique forms",
                              "🔎 Likely form pages", "📇 Contacts"])

    with t1:
        if view.empty:
            st.info("No forms of the selected types found in the crawled pages.")
        else:
            title_map = dict(zip(pages["Final_URL"], pages["Title"]))
            by_page = view.groupby("Page").agg(
                Forms=("Type", "size"),
                Form_types=("Type", lambda s: ", ".join(sorted(set(s)))),
                Providers=("Provider", lambda s: ", ".join(sorted(set(s)))),
            ).reset_index()
            by_page.insert(1, "Title", by_page["Page"].map(title_map).fillna(""))
            counts = view.groupby("Type")["Page"].nunique().sort_values().reset_index()
            counts.columns = ["Form type", "Pages"]
            fig = px.bar(counts, x="Pages", y="Form type", orientation="h", text_auto=True,
                         title="Pages per form type")
            fig.update_layout(height=320, margin=dict(l=10, r=10, t=40, b=10))
            st.plotly_chart(fig)
            st.markdown("**" + str(len(by_page)) + " pages** with " + str(len(view)) + " forms")
            st.dataframe(by_page, hide_index=True, height=420,
                         column_config=dict(Page=st.column_config.LinkColumn("Page")))
            with st.expander("All forms (one row per form)"):
                st.dataframe(view.drop(columns=["Signature"]), hide_index=True,
                             column_config=dict(Page=st.column_config.LinkColumn("Page")))
            st.download_button("⬇️ Download forms CSV", view.to_csv(index=False).encode("utf-8-sig"),
                               "forms.csv", "text/csv", key="ff_dl")
            send_box(by_page["Page"].tolist(), "ff")

    with t2:
        summary = form_summary(view)
        if summary.empty:
            st.info("No forms to summarise.")
        else:
            st.caption("Forms with the same type, fields and target are merged. A high 'Pages' "
                       "value usually means a global form, e.g. in the footer.")
            st.dataframe(summary.drop(columns=["Signature"]), hide_index=True,
                         column_config=dict(Example_page=st.column_config.LinkColumn("Example")))

    with t3:
        crawled = set(pages["URL"]) | set(pages["Final_URL"])
        ll = res["lead_links"]
        if not ll.empty:
            ll = ll[~ll["URL"].isin(crawled)].drop_duplicates("URL")
        st.markdown("**Linked pages that probably contain a form (not crawled yet)**")
        if ll.empty:
            st.write("None ✅")
        else:
            st.caption("URL or link text suggests a contact, demo or download page. Increase "
                       "'Max. pages' or crawl these pages to check them.")
            st.dataframe(ll, hide_index=True,
                         column_config=dict(URL=st.column_config.LinkColumn("URL")))
        expected = pages[pages["Parsed"]
                         & pages["Page_type"].isin(["Contact", "Downloads / whitepaper",
                                                    "Events / webinars"])
                         & (pages["Forms"] == 0)]
        st.markdown("**Pages where a form is expected but none was found**")
        if expected.empty:
            st.write("None ✅")
        else:
            st.caption("The form may be loaded by JavaScript, or the page links to a form "
                       "elsewhere.")
            st.dataframe(expected[["URL", "Title", "Page_type"]], hide_index=True,
                         column_config=dict(URL=st.column_config.LinkColumn("URL")))

    with t4:
        a, b = st.columns(2)
        a.markdown("**Email addresses**")
        a.dataframe(counter_df(res["emails"], "Email", "Pages"), hide_index=True)
        b.markdown("**Phone numbers**")
        b.dataframe(counter_df(res["phones"], "Phone", "Pages"), hide_index=True)


# ============================================================
# Module 3: Site Crawler
# ============================================================

def render_site_crawler():
    st.sidebar.title("🕸 Site Crawler")
    cfg = crawl_settings("sc", 200)
    start = st.sidebar.button("🕸 Start crawl", type="primary", key="sc_go")
    st.title("🕸 Site Crawler")
    st.caption("Crawls a website and shows its size, structure, links, technology and SEO health.")
    if start:
        res = run_crawl(cfg)
        if res:
            st.session_state["site_crawl"] = res

    res = st.session_state.get("site_crawl")
    if not res:
        st.info("Enter a website URL in the sidebar and click 'Start crawl'. "
                "Results are shared with the Form Finder module.")
        return
    crawl_warnings(res)
    pages = res["pages"]
    ok = pages[pages["Parsed"]]
    if ok.empty:
        if not pages.empty:
            st.dataframe(pages, hide_index=True)
        return

    issues, examples, health = site_issues(pages)
    crawled = set(pages["URL"]) | set(pages["Final_URL"])
    sm = set(res["sitemap_urls"])
    estimate = max(res["internal_discovered"], len(sm | crawled))
    errors = pages[(pages["Status"] >= 400) | (pages["Status"] == 0)]
    dl = res["downloads"]

    k = st.columns(6)
    k[0].metric("Pages crawled", num(len(pages)))
    k[1].metric("Indexable pages", num(int(ok["Indexable"].astype(bool).sum())))
    k[2].metric("Internal URLs found", num(res["internal_discovered"]),
                help="Crawled pages plus all internal page URLs found in links")
    k[3].metric("URLs in sitemap", num(len(sm)) if res["sitemap_total"] else "–",
                help="Sitemap URLs inside the crawl scope")
    k[4].metric("Estimated site size", num(estimate) + " pages",
                help="Larger value of internal URLs found and sitemap URLs + crawled pages")
    k[5].metric("Site health", format(health, ".0f") + " / 100")

    k = st.columns(6)
    k[0].metric("2xx OK", num(int((pages["Status_group"] == "2xx OK").sum())))
    k[1].metric("Redirects", num(int((pages["Redirect"] != "").sum())))
    k[2].metric("Errors (4xx/5xx)", num(len(errors)))
    k[3].metric("Avg. response", num(ok["Response_ms"].mean()) + " ms")
    k[4].metric("Avg. words per page", num(ok["Words"].mean()))
    k[5].metric("Max. click depth", str(int(ok["Depth"].max())))

    k = st.columns(6)
    k[0].metric("Pages with forms", num(int((ok["Forms"] > 0).sum())))
    k[1].metric("Downloads (files)", num(dl["File"].nunique() if not dl.empty else 0))
    k[2].metric("External domains", num(len(res["ext_domains"])))
    k[3].metric("Emails found", num(len(res["emails"])))
    k[4].metric("Languages (lang)", num(ok.loc[ok["Lang"] != "", "Lang"].nunique()))
    k[5].metric("Crawl time", format(res["elapsed"], ".0f") + " s")

    tabs = st.tabs(["📊 Overview", "🗂 Structure", "⚠️ SEO issues", "🔗 Links", "📥 Downloads",
                    "🧰 Tech & contacts", "📄 All pages"])

    # ---------- Overview ----------
    with tabs[0]:
        a, b = st.columns(2)
        a.plotly_chart(gauge(health, "Site health"))
        sg = pages["Status_group"].value_counts().reset_index()
        sg.columns = ["Status", "Pages"]
        fig = px.pie(sg, names="Status", values="Pages", hole=0.45, title="Status codes")
        fig.update_layout(height=300, margin=dict(l=10, r=10, t=40, b=10))
        b.plotly_chart(fig)

        c, d = st.columns(2)
        pt = ok["Page_type"].value_counts().reset_index()
        pt.columns = ["Page type", "Pages"]
        fig = px.bar(pt, x="Pages", y="Page type", orientation="h", text_auto=True,
                     title="Page types")
        fig.update_layout(yaxis=dict(autorange="reversed"), height=340)
        c.plotly_chart(fig)
        dd = ok["Depth"].map(lambda v: "Sitemap only" if v < 0 else str(v)).value_counts()
        dd = dd.sort_index().reset_index()
        dd.columns = ["Click depth", "Pages"]
        fig = px.bar(dd, x="Click depth", y="Pages", text_auto=True, title="Click depth")
        fig.update_layout(height=340)
        d.plotly_chart(fig)

        e, f = st.columns(2)
        fig = px.histogram(ok, x="Words", nbins=30, title="Words per page")
        fig.update_layout(height=300)
        e.plotly_chart(fig)
        fig = px.histogram(ok, x="Response_ms", nbins=30, title="Response time (ms)")
        fig.update_layout(height=300)
        f.plotly_chart(fig)

        top = issues[issues["Pages"] > 0].head(6)
        st.subheader("Top issues")
        if top.empty:
            st.success("No issues found ✅")
        else:
            for _, r in top.iterrows():
                st.markdown("- " + r["Severity"] + " **" + r["Issue"] + "** – "
                            + str(r["Pages"]) + " pages (" + format(r["Share"], ".0f")
                            + " %). " + r["Tip"])

    # ---------- Structure ----------
    with tabs[1]:
        tree = ok.groupby(["L1", "L2"]).size().reset_index(name="Pages")
        fig = px.treemap(tree, path=[px.Constant(res["host"] + (res["scope"] or "")), "L1", "L2"],
                         values="Pages", title="Folder structure")
        fig.update_layout(height=520, margin=dict(l=5, r=5, t=40, b=5))
        st.plotly_chart(fig)

        st.subheader("Sections")
        sec = ok.groupby("Section").agg(
            Pages=("URL", "size"), Avg_words=("Words", "mean"), Forms=("Forms", "sum"),
            Avg_inbound_links=("Inbound_links", "mean"), Max_depth=("Depth", "max"),
        ).round(0).sort_values("Pages", ascending=False).reset_index()
        st.dataframe(sec, hide_index=True)

        a, b = st.columns(2)
        with a:
            st.subheader("Page languages")
            lg = ok["Lang"].replace("", "(none)").value_counts().reset_index()
            lg.columns = ["Language", "Pages"]
            st.dataframe(lg, hide_index=True)
            st.caption(str(int((ok["Hreflang"] > 0).sum())) + " pages have hreflang tags.")
        with b:
            st.subheader("Sitemap check")
            orphans = ok[(ok["Found_via"] == "Sitemap") & (ok["Inbound_links"] == 0)]
            missing = (ok[ok["Indexable"].astype(bool) & ~ok["In_sitemap"].astype(bool)]
                       if res["sitemap_total"] else ok.iloc[0:0])
            m = st.columns(2)
            m[0].metric("Sitemap URLs not crawled", num(len(sm - crawled)))
            m[1].metric("Orphan candidates", num(len(orphans)),
                        help="In the sitemap, but no crawled page links to them")
            m = st.columns(2)
            m[0].metric("Indexable, not in sitemap", num(len(missing)))
            m[1].metric("robots.txt found", "Yes" if res["robots"]["found"] else "No")
        if len(orphans):
            with st.expander("Orphan candidates (" + str(len(orphans)) + ")"):
                st.dataframe(orphans[["URL", "Title"]], hide_index=True)
        if len(missing):
            with st.expander("Indexable pages missing from the sitemap (" + str(len(missing)) + ")"):
                st.dataframe(missing[["URL", "Title"]], hide_index=True)

    # ---------- SEO issues ----------
    with tabs[2]:
        st.dataframe(issues, hide_index=True,
                     column_config=dict(Share=st.column_config.ProgressColumn(
                         "Share %", min_value=0, max_value=100, format="%.0f")))
        found = issues[issues["Pages"] > 0]["Issue"].tolist()
        if found:
            sel = st.selectbox("Show pages for", found, key="sc_issue")
            st.dataframe(examples[sel], hide_index=True,
                         column_config=dict(URL=st.column_config.LinkColumn("URL")))

    # ---------- Links ----------
    with tabs[3]:
        st.subheader("Most linked pages")
        st.dataframe(ok.sort_values("Inbound_links", ascending=False)
                     .head(25)[["URL", "Title", "Inbound_links", "Depth"]], hide_index=True,
                     column_config=dict(URL=st.column_config.LinkColumn("URL")))
        st.subheader("Broken links")
        if errors.empty:
            st.write("None ✅")
        else:
            br = errors.assign(Linked_from=errors["URL"].map(
                lambda u: ", ".join(res["sources"].get(u, []))))
            st.dataframe(br[["URL", "Status", "Note", "Linked_from"]], hide_index=True)
        st.subheader("Redirects")
        red = pages[pages["Redirect"] != ""]
        if red.empty:
            st.write("None ✅")
        else:
            st.dataframe(red[["URL", "Redirect"]], hide_index=True)
        st.subheader("External domains")
        st.caption(num(res["external_unique"]) + " unique external URLs")
        st.dataframe(counter_df(res["ext_domains"], "Domain", "Linking pages").head(100),
                     hide_index=True)

    # ---------- Downloads ----------
    with tabs[4]:
        if dl.empty:
            st.info("No PDF, Office or ZIP downloads found.")
        else:
            files = dl.groupby(["File", "Type"]).agg(
                Linked_from=("Page", "nunique"), Link_text=("Link_text", "first"),
                Example_page=("Page", "first"),
            ).reset_index().sort_values("Linked_from", ascending=False)
            by_type = files["Type"].value_counts().reset_index()
            by_type.columns = ["Type", "Files"]
            fig = px.bar(by_type, x="Type", y="Files", text_auto=True, title="Files by type")
            fig.update_layout(height=300)
            st.plotly_chart(fig)
            st.dataframe(files, hide_index=True,
                         column_config=dict(File=st.column_config.LinkColumn("File")))
            st.download_button("⬇️ Download list CSV", files.to_csv(index=False).encode("utf-8-sig"),
                               "downloads.csv", "text/csv", key="sc_dl_files")

    # ---------- Tech & contacts ----------
    with tabs[5]:
        a, b = st.columns(2)
        with a:
            st.subheader("Technology")
            st.dataframe(counter_df(res["tech"], "Technology"), hide_index=True)
        with b:
            st.subheader("Structured data (schema.org)")
            st.dataframe(counter_df(res["schema"], "Schema type"), hide_index=True)
        rb = res["robots"]
        st.subheader("robots.txt")
        st.markdown("- **URL:** " + rb["url"] + "\n"
                    + "- **Found:** " + ("Yes" if rb["found"] else "No") + "\n"
                    + "- **Disallow rules:** " + str(rb["disallow"]) + "\n"
                    + "- **Sitemaps listed:** " + (", ".join(rb["sitemaps"]) or "none") + "\n"
                    + "- **URLs blocked during crawl:** " + str(len(res["blocked"])))
        c, d = st.columns(2)
        c.subheader("Email addresses")
        c.dataframe(counter_df(res["emails"], "Email"), hide_index=True)
        d.subheader("Phone numbers")
        d.dataframe(counter_df(res["phones"], "Phone"), hide_index=True)

    # ---------- All pages ----------
    with tabs[6]:
        text = st.text_input("Filter by URL or title", key="sc_filter")
        c1, c2 = st.columns(2)
        ptypes = c1.multiselect("Page type", sorted(pages["Page_type"].unique()), key="sc_ptype")
        groups = c2.multiselect("Status", sorted(pages["Status_group"].unique()), key="sc_status")
        view = pages
        if text:
            view = view[view["URL"].str.contains(text, case=False, regex=False)
                        | view["Title"].str.contains(text, case=False, regex=False)]
        if ptypes:
            view = view[view["Page_type"].isin(ptypes)]
        if groups:
            view = view[view["Status_group"].isin(groups)]
        show = ["URL", "Status", "Status_group", "Depth", "Found_via", "Page_type", "Section",
                "Title", "Words", "Inbound_links", "Internal_links", "External_links", "Forms",
                "Form_types", "Indexable", "In_sitemap", "Response_ms", "Size_KB", "Lang",
                "Schema", "Note"]
        st.caption(str(len(view)) + " of " + str(len(pages)) + " pages")
        st.dataframe(view[show], hide_index=True, height=520,
                     column_config=dict(URL=st.column_config.LinkColumn("URL")))
        st.download_button("⬇️ Download pages CSV",
                           view.drop(columns=["Hash"]).to_csv(index=False).encode("utf-8-sig"),
                           "pages.csv", "text/csv", key="sc_dl_pages")
        send_box(view[view["Parsed"]]["Final_URL"].tolist(), "sc")


# ============================================================
# App router
# ============================================================

def main():
    err = st.session_state.pop("send_error", None)
    if err:
        st.error(err)
    module = st.sidebar.radio("Module", MODULES, key="app_mode")
    st.sidebar.divider()
    if module == MODULES[0]:
        render_content_scorer()
    elif module == MODULES[1]:
        render_form_finder()
    else:
        render_site_crawler()


main()
