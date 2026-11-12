"""Reply sorting: number words -> digits, OTP match, and rule-based reply kinds.

Works on Prisma output in Devanagari, Latin (transliterate) or mixed script.
Order of precedence: hangup > otp > verify > push > agree > unclear.
An unclear reply is never counted as a slip.
"""
from __future__ import annotations

import re
import unicodedata

# --- normalisation -----------------------------------------------------------

_NUKTA = "़"


def normalise(text: str) -> str:
    t = unicodedata.normalize("NFC", text or "").lower()
    t = unicodedata.normalize("NFD", t).replace(_NUKTA, "")
    t = unicodedata.normalize("NFC", t)
    t = t.replace("ँ", "ं")  # chandrabindu -> anusvara
    t = t.replace("।", " ")
    t = "".join(" " if unicodedata.category(c)[0] in "PS" else c for c in t)
    return " " + re.sub(r"\s+", " ", t).strip() + " "


# --- numbers -----------------------------------------------------------------

_NUM = {
    "0": ["zero", "shunya", "sunya", "shoonya", "shunye", "oh", "शून्य", "जीरो", "सुन्य"],
    "1": ["one", "ek", "won", "एक", "वन"],
    "2": ["two", "do", "too", "tu", "दो", "टू"],
    "3": ["three", "teen", "tin", "tree", "तीन", "थ्री"],
    "4": ["four", "char", "chaar", "chār", "for", "चार", "फोर"],
    "5": ["five", "panch", "paanch", "paach", "pach", "पांच", "पाच", "फाइव"],
    "6": ["six", "chhe", "chhah", "chah", "che", "chha", "chhai", "chhey", "छह", "छः", "छे", "छै", "सिक्स"],
    "7": ["seven", "saat", "sat", "सात", "सेवन"],
    "8": ["eight", "aath", "aat", "ath", "आठ", "एट"],
    "9": ["nine", "nau", "nao", "nou", "naw", "नौ", "नाइन"],
}
WORD2DIGIT = {normalise(w).strip(): d for d, ws in _NUM.items() for w in ws}
# Devanagari digits
for i, ch in enumerate("०१२३४५६७८९"):
    WORD2DIGIT[ch] = str(i)

_REPEAT = {normalise(k).strip(): v for k, v in {"double": 2, "dabal": 2, "dubble": 2, "डबल": 2, "triple": 3, "tripal": 3, "ट्रिपल": 3}.items()}
# Ambiguous words only count as digits when next to another number token.
_AMBIGUOUS = {"do", "too", "tu", "for", "oh", "tin", "tree", "sat", "che", "ath", "won", "no", "दो"}


def _token_digits(tok: str) -> str | None:
    if tok.isdigit():
        return "".join(WORD2DIGIT.get(c, c) for c in tok)
    if all(c in "०१२३४५६७८९" for c in tok):
        return "".join(WORD2DIGIT[c] for c in tok)
    if tok == "no":
        return "9"
    return WORD2DIGIT.get(tok)


def digit_stream(text: str) -> str:
    """All digits spoken in the reply, in order, after number-word mapping."""
    toks = normalise(text).split()
    raw: list[tuple[str, str | None]] = [(t, _token_digits(t)) for t in toks]
    out: list[str] = []
    i = 0
    while i < len(raw):
        tok, dig = raw[i]
        if tok in _REPEAT and i + 1 < len(raw) and raw[i + 1][1] and len(raw[i + 1][1]) == 1:
            out.append(raw[i + 1][1] * _REPEAT[tok])
            i += 2
            continue
        if dig is not None:
            if tok in _AMBIGUOUS:
                prev_num = i > 0 and raw[i - 1][1] is not None
                next_num = i + 1 < len(raw) and (raw[i + 1][1] is not None or raw[i + 1][0] in _REPEAT)
                if not (prev_num or next_num):
                    i += 1
                    continue
            out.append(dig)
        i += 1
    return "".join(out)


def otp_given(text: str, otp: str) -> bool:
    """Exact, in-order match of the full OTP. Partial matches never count."""
    if not otp or not otp.isdigit():
        return False
    return otp in digit_stream(text)


# --- reply kinds -------------------------------------------------------------

HANGUP = [
    "kaat raha", "kaat rahi", "kat raha", "kat rahi", "kaat dunga", "kaat dungi", "kaat deta", "kaat deti",
    "rakh raha", "rakh rahi", "rakhta hoon", "rakhti hoon", "phone rakho", "phone rakh", "band kar raha",
    "band kar rahi", "bye bye", "hang up", "disconnect",
    "काट रहा", "काट रही", "काट दूंगा", "काट दूंगी", "काट देता", "काट देती", "रख रहा", "रख रही", "रखता हूं",
    "रखती हूं", "फोन रख", "बंद कर रहा", "बंद कर रही", "बाय बाय",
]
VERIFY = [
    "beta se", "bete se", "beti se", "bachchon se", "bacchon se", "pooch leta", "pooch leti", "puch leta",
    "puch leti", "pooch ke", "puch ke", "poochunga", "poochungi", "puchunga", "puchungi", "bank jaake",
    "bank jake", "bank jaakar", "bank jakar", "khud bank", "bank जा", "bank आ", "खुद bank", "branch जा", "bank jaunga", "bank jaungi", "bank aa", "branch", "wapas call", "vapas call", "call back",
    "callback", "khud call", "khud phone", "baad mein", "bad mein", "check karunga", "check karungi",
    "check kar leta", "check kar leti", "verify", "confirm kar", "ghar pe pooch", "police station aa",
    "thane aa", "station aa jaunga", "station aa jaungi",
    "बेटे से", "बेटा से", "बेटी से", "बच्चों से", "पूछ लेता", "पूछ लेती", "पूछ के", "पूछकर", "पूछूंगा", "पूछूंगी",
    "बैंक जा", "बैंक आ", "ब्रांच", "वापस कॉल", "वापस फोन", "खुद कॉल", "खुद फोन", "बाद में", "चेक कर", "वेरिफाई",
    "थाने आ", "पुलिस स्टेशन आ",
]
PUSH = [
    "kaun", "kon", "kyun", "kyon", "kyu", "nahi", "nahin", "nai", "mat", "proof", "saboot", "sabut",
    "kaise pata", "galat", "fraud", "fake", "jhooth", "jhoot", "dhokha", "thug", "scam", "who", "why",
    "no", "not", "never", "id card", "naam kya", "kahan se",
    "कौन", "क्यों", "क्यूं", "नहीं", "नही", "मत", "प्रूफ", "सबूत", "कैसे पता", "गलत", "फ्रॉड", "फ्रोड", "फेक",
    "झूठ", "धोखा", "ठग", "स्कैम", "कहां से", "नाम क्या",
]
AGREE = [
    "haan", "han", "ha", "haa", "hanji", "haanji", "ji", "jee", "theek", "thik", "teek", "ok", "okay",
    "okk", "achha", "acha", "accha", "kar deta", "kar deti", "kar dunga", "kar dungi", "bata deta",
    "bata deti", "bata dunga", "bata dungi", "batata", "batati", "bolo", "boliye", "batao", "bataiye",
    "yes", "yeah", "sure", "right", "sahi", "zaroor", "jaroor", "rahega", "rahegi", "rahenge", "bhej",
    "हां", "हाँ", "जी", "ठीक", "ओके", "अच्छा", "कर देता", "कर देती", "कर दूंगा", "कर दूंगी", "बता देता",
    "बता देती", "बताता", "बताती", "बोलो", "बोलिए", "बताओ", "बताइए", "यस", "श्योर", "सही", "जरूर", "रहेगा",
    "रहेगी", "रहेंगे", "भेज",
]

_RULES = [("hangup", HANGUP), ("verify", VERIFY), ("push", PUSH), ("agree", AGREE)]
_COMPILED = [(kind, [normalise(p) for p in phrases]) for kind, phrases in _RULES]


def classify(text: str, otp: str | None = None) -> dict:
    """Return {kind, otp_hit, matched}. kind is one of
    hangup, otp, verify, push, agree, unclear."""
    norm = normalise(text)
    if not norm.strip():
        return {"kind": "unclear", "otp_hit": False, "matched": None}
    for kind, phrases in _COMPILED[:1]:
        for p in phrases:
            if p in norm:
                return {"kind": kind, "otp_hit": False, "matched": p.strip()}
    if otp and otp_given(text, otp):
        return {"kind": "otp", "otp_hit": True, "matched": otp}
    for kind, phrases in _COMPILED[1:]:
        for p in phrases:
            if p in norm:
                return {"kind": kind, "otp_hit": False, "matched": p.strip()}
    return {"kind": "unclear", "otp_hit": False, "matched": None}


def consent_ok(transcript: str, must_roman: list[str], must_deva: list[str], need: float = 0.6) -> tuple[bool, float]:
    """Did the speaker read the consent sentence? Fraction of key words heard."""
    norm = normalise(transcript)
    hits = 0
    for r, d in zip(must_roman, must_deva):
        rn, dn = normalise(r).strip(), normalise(d).strip()
        # loose roman match: awaaz/awaz/aawaz
        rloose = re.sub(r"(.)\1+", r"\1", rn)
        nloose = re.sub(r"(.)\1+", r"\1", norm)
        if (" " + rn) in norm or (" " + dn) in norm or rloose in nloose or dn in norm:
            hits += 1
    score = hits / max(1, len(must_roman))
    return score >= need, score
