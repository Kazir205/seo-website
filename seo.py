"""
Content Performance Scorer
Scores a draft or a live web page for SEO, readability, engagement (viral potential),
conversion (promotional strength), social sharing and brand compliance, and shows
what to improve. Optional: trains a predictive model on your own performance data.

Start with:  streamlit run content_scorer.py
"""

import io
import re
from collections import Counter
from html import escape
from urllib.parse import urljoin, urlparse

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st
from bs4 import BeautifulSoup

st.set_page_config(page_title="Content Performance Scorer", page_icon="🚀", layout="wide")


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
    pattern = r"(?<!\w)" + re.escape(phrase.lower()) + r"(?!\w)"
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


def rank_corr(a, b):
    return float(pd.Series(list(a)).rank().corr(pd.Series(list(b)).rank()))


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
                og_desc=clean(teaser), og_image=bool(has_image), teaser=clean(teaser))


@st.cache_data(show_spinner=False, ttl=3600)
def fetch_url(url):
    headers = dict()
    headers["User-Agent"] = "Mozilla/5.0 (compatible; ContentScorer/1.0)"
    r = requests.get(url, headers=headers, timeout=25)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    def meta(key):
        tag = (soup.find("meta", attrs=dict(name=key))
               or soup.find("meta", attrs=dict(property=key)))
        return clean(tag.get("content")) if tag else ""

    title = clean(soup.title.get_text(" ")) if soup.title else ""
    h1s = [clean(h.get_text(" ")) for h in soup.find_all("h1")]
    desc, og_title = meta("description"), meta("og:title")
    og_desc, og_image = meta("og:description"), meta("og:image")

    for tag in soup(["script", "style", "noscript", "template", "svg",
                     "nav", "header", "footer", "aside"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup

    blocks = [clean(t.get_text(" ")) for t in main.find_all(["p", "li", "blockquote"])]
    body = "\n\n".join(b for b in blocks if len(b) > 1)
    if len(words_of(body)) < 50:
        body = "\n\n".join(clean(x) for x in main.get_text("\n").split("\n") if clean(x))

    host = urlparse(r.url).netloc.lower()
    internal = external = 0
    cta_texts = []
    for a in main.find_all(["a", "button"]):
        label = clean(a.get_text(" "))
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
                headings=[clean(h.get_text(" ")) for h in main.find_all(["h2", "h3"])],
                body=body, slug=urlparse(r.url).path, links_int=internal, links_ext=external,
                images=len(imgs), images_no_alt=sum(1 for i in imgs if not clean(i.get("alt"))),
                list_items=len(main.find_all("li")), cta_texts=list(dict.fromkeys(cta_texts))[:10],
                og_title=og_title, og_desc=og_desc, og_image=bool(og_image),
                teaser=og_desc or desc)


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
        ("Curiosity / question", 1.0 if h.strip().endswith("?") or count_in(hl, CURIOSITY) else 0.0, 10),
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
    box = ("<div style='font-family:Arial,sans-serif;max-width:620px;padding:12px;"
           "border:1px solid #ddd;border-radius:8px'>"
           "<div style='color:#202124;font-size:13px'>" + escape(url) + "</div>"
           "<div style='color:#1a0dab;font-size:19px;margin:3px 0'>" + escape(t) + "</div>"
           "<div style='color:#4d5156;font-size:14px'>" + escape(d) + "</div></div>")
    st.markdown(box, unsafe_allow_html=True)


# ============================================================
# Sidebar
# ============================================================
st.sidebar.title("🚀 Content Scorer")
mode = st.sidebar.radio("Input", ["Draft text", "Live URL"], horizontal=True)
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

# ============================================================
# Content input
# ============================================================
st.title("🚀 Content Performance Scorer")
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
    content = parse_draft(headline, seo_title, meta, body_md, slug, cta, teaser, has_image, site_host)
else:
    url = st.text_input("Page URL",
                        "https://www.chg-meridian.com/global-en/services/sustainable-leasing/")
    if st.button("🔍 Fetch & score", type="primary"):
        try:
            with st.spinner("Loading page …"):
                st.session_state["url_content"] = fetch_url(url.strip())
        except Exception as e:
            st.error("Could not load the page: " + str(e))
    content = st.session_state.get("url_content")

result = analyze(content, keyword, secondary, goal_key, channel, rules, required) if content else None
model_info = st.session_state.get("model")

tabs = st.tabs(["🎯 Score", "🛠 What to improve", "📋 All checks", "✍️ Text analysis",
                "🆎 Headline tester", "🤖 Predictive model"])

# ------------------------------------------------------------
# Tab 1: Score
# ------------------------------------------------------------
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
            fig = px.line_polar(cats, r="Score", theta="Category", line_close=True, range_r=[0, 100])
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
        preview_url = content["url"] or (("https://" + site_host if site_host else "") + content["slug"])
        serp_preview(content["title"], preview_url, content["meta"])

# ------------------------------------------------------------
# Tab 2: What to improve
# ------------------------------------------------------------
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
                prio = "🔴 High" if r["Gain"] >= 3 else "🟠 Medium" if r["Gain"] >= 1.5 else "🟢 Low"
                now = (" *Now: " + r["Detail"] + "*") if r["Detail"] else ""
                st.markdown("- **" + prio + " · " + r["Category"] + " – " + r["Check"]
                            + "** (+" + format(r["Gain"], ".1f") + " pts): " + r["Tip"] + now)

        sugg = result["highlights"]["suggestions"]
        if sugg:
            st.subheader("Keyword ideas from your text")
            st.write(", ".join(t + " (" + str(n) + "×)" for t, n in sugg))

# ------------------------------------------------------------
# Tab 3: All checks
# ------------------------------------------------------------
with tabs[2]:
    if result is None:
        st.info("No content analysed yet.")
    else:
        df = result["checks"].copy()
        df["Percent"] = (df["Score"] / df["Max"] * 100).round(0)
        cat_filter = st.multiselect("Category", sorted(df["Category"].unique()))
        if cat_filter:
            df = df[df["Category"].isin(cat_filter)]
        st.dataframe(df[["Status", "Category", "Check", "Percent", "Score", "Max", "Detail", "Tip"]],
                     hide_index=True, height=560,
                     column_config=dict(Percent=st.column_config.ProgressColumn(
                         "Score %", min_value=0, max_value=100, format="%d")))

# ------------------------------------------------------------
# Tab 4: Text analysis
# ------------------------------------------------------------
with tabs[3]:
    if result is None:
        st.info("No content analysed yet.")
    else:
        hl = result["highlights"]
        a, b = st.columns(2)
        with a:
            st.subheader("Keyword placement")
            st.caption("Keyword: " + result["stats"]["kw"])
            st.dataframe(pd.DataFrame(hl["placement"], columns=["Place", "Found"]), hide_index=True)
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

# ------------------------------------------------------------
# Tab 5: Headline A/B tester
# ------------------------------------------------------------
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

# ------------------------------------------------------------
# Tab 6: Predictive model
# ------------------------------------------------------------
with tabs[5]:
    st.subheader("Learn from your own performance data")
    st.markdown(
        "Upload past content with a **result metric** (pageviews, clicks, CTR, leads, shares). "
        "The app computes the same 30+ features for each row and trains a **Random Forest** "
        "that learns what works for *your* audience.\n\n"
        "- At least **20 rows** are needed. 100+ give much better results.\n"
        "- Provide **body text**, or a **URL column** (the pages are then fetched automatically).\n"
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
    st.download_button("⬇️ Download template CSV", template.to_csv(index=False).encode("utf-8-sig"),
                       "training_template.csv", "text/csv")

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
                col_title = pick(m1[1], "Title column", ["title", "titel", "headline", "page title"])
                col_body = pick(m1[2], "Body text column", ["body", "text", "content", "inhalt"])
                m2 = st.columns(3)
                col_meta = pick(m2[0], "Meta description column", ["meta", "meta description", "description"])
                col_kw = pick(m2[1], "Keyword column", ["keyword", "focus keyword"])
                col_url = pick(m2[2], "URL column", ["url", "adresse", "address", "page"])
                m3 = st.columns(2)
                fetch_limit = m3[0].number_input("Max. URLs to fetch (rows without body text)",
                                                 0, 500, 100)
                log_target = m3[1].checkbox("Log-transform target (recommended for traffic and clicks)",
                                            value=True)

                if st.button("🤖 Train model", type="primary"):
                    cols_map = dict(title=col_title, body=col_body, meta=col_meta,
                                    keyword=col_kw, url=col_url)
                    progress = st.progress(0.0, text="Starting …")
                    X, y, fetched, skipped = build_training(hist, cols_map, target, goal_key,
                                                            channel, int(fetch_limit), progress)
                    if len(X) < 20:
                        st.error("Only " + str(len(X)) + " usable rows. At least 20 are needed "
                                 "(skipped: " + str(skipped) + ").")
                    else:
                        try:
                            model, metrics, importance, pred = train_model(X, y, log_target)
                            st.session_state["model"] = dict(
                                model=model, features=list(X.columns), log=log_target, X=X, y=y,
                                target=target, metrics=metrics, importance=importance, pred=pred,
                                heuristic=rank_corr(X["score_overall"], y),
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
            st.error("Weak model: add more rows, or the result depends on factors not in the text "
                     "(budget, channel, timing, topic demand).")

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
                       + fmt(p) + "** – better than **" + format(pct, ".0f") + " %** of your past content.")
            st.subheader("Your content vs. your top 25 % content")
            st.dataframe(benchmark(model_info, result["features"]), hide_index=True)
        if st.button("🗑 Reset model"):
            del st.session_state["model"]
            st.rerun()
