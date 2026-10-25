"""
CarePath AI - backend pipeline used by the chatbot UI.

Function names follow the team brief contracts:
    extract_report()  -> Member 1 will swap in the production OCR/extraction
    redact_report()   -> Member 1 will swap in Microsoft Presidio (this version is a regex stand-in, fail-closed)
    interpret()       -> deterministic range selection (rules, not the LLM)
    explain()         -> uses knowledge.py (Member 2 swaps in RAG + local model)
    answer_followup() -> guarded follow-up answers (optional local Ollama)
    delete_session()  -> removes artefacts and VERIFIES removal
Synthetic reports only. Not a medical device. Does not diagnose or prescribe.
"""
import io, json, os, re, subprocess, tempfile
from datetime import date, datetime
import pdfplumber
import knowledge as K

HERE = os.path.dirname(os.path.abspath(__file__))
RANGES = json.load(open(os.path.join(HERE, "ranges.json")))

ANALYTES = [  # (key, regex matching the row label)
    ("haemoglobin", r"Haemoglobin(?:\s*\(Hb\))?|Hb\b"), ("wbc", r"White (?:cell|blood cell) count|WBC"),
    ("neutrophils", r"Neutrophils?"), ("lymphocytes", r"Lymphocytes?"), ("platelets", r"Platelets?|PLT"),
    ("mcv", r"MCV"), ("sodium", r"Sodium"), ("potassium", r"Potassium"), ("urea", r"Urea"),
    ("creatinine", r"Creatinine"), ("egfr", r"eGFR(?:\s*\(CKD-EPI\))?"), ("hba1c", r"HbA1c"),
    ("ferritin", r"Ferritin"), ("tsh", r"TSH"), ("free_t4", r"Free T4"),
]
PLAUSIBLE = {"haemoglobin": (30, 250), "wbc": (0.1, 200), "neutrophils": (0, 150), "lymphocytes": (0, 150),
             "platelets": (1, 2000), "mcv": (40, 150), "sodium": (90, 200), "potassium": (1.5, 10), "urea": (0.5, 100),
             "creatinine": (10, 2500), "egfr": (1, 200), "hba1c": (15, 200), "ferritin": (1, 50000),
             "tsh": (0.001, 200), "free_t4": (1, 150)}
EXPECTED_UNIT = {k: v["unit"] for k, v in RANGES.items() if isinstance(v, dict) and "unit" in v}


# ============================================================ 1. EXTRACT
def _pdf_text(data):
    pdf = pdfplumber.open(io.BytesIO(data)); page = pdf.pages[0]
    # drop rotated / oversized text such as a "SYNTHETIC TEST DATA" watermark
    page = page.filter(lambda o: o.get("object_type") != "char" or
                       (abs(o.get("matrix", (1, 0))[1]) < 0.01 and o.get("size", 0) < 30))
    hits = page.search(r"Test\s+Result")
    split_y = hits[0]["top"] - 18 if hits else page.height * 0.3
    head_l = page.crop((0, 0, page.width * 0.53, split_y)).extract_text() or ""
    head_r = page.crop((page.width * 0.53, 0, page.width, split_y)).extract_text() or ""
    body = page.crop((0, split_y, page.width, page.height)).extract_text() or ""
    return head_l, head_r, body, 1.0


def _ocr_text(data, suffix):
    from PIL import Image
    im = Image.open(io.BytesIO(data)).convert("L"); im = im.resize((im.width * 2, im.height * 2))
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        im.save(f, format="PNG"); path = f.name
    try:
        tsv = subprocess.run(["tesseract", path, "stdout", "--psm", "6", "tsv"], capture_output=True, text=True,
                             timeout=60).stdout
        confs = [float(l.split("\t")[10]) for l in tsv.splitlines()[1:] if len(l.split("\t")) > 11
                 and l.split("\t")[11].strip() and float(l.split("\t")[10]) >= 0]
        text = subprocess.run(["tesseract", path, "stdout", "--psm", "6"], capture_output=True, text=True,
                              timeout=60).stdout
    finally:
        os.remove(path)  # never keep the image on disk
    conf = (sum(confs) / len(confs) / 100) if confs else 0.0
    return text, "", text, conf


ROW_RE = re.compile(r"^(?P<label>%s)\s+(?P<rest>.+)$" % "|".join(f"(?:{p})" for _, p in ANALYTES), re.I)
RANGE_RE = re.compile(r"((?:[<>]\s*)?\d+(?:\.\d+)?(?:\s*-\s*\d+(?:\.\d+)?)?)\s*$")


UNITS = ["g/L", "mmol/L", "umol/L", "mg/dL", "mL/min/1.73m2", "mmol/mol", "ug/L", "mU/L", "pmol/L", "fL"]


def _norm_unit(u):
    """Tidy units, including common OCR misreads (x10°9/L, fl ...). Returns '' if no unit is present."""
    if re.search(r"10\D{0,3}9\s*/\s*L", u): return "x10^9/L"
    if re.search(r"10\D{0,3}12\s*/\s*L", u): return "x10^12/L"
    u2 = u.replace("µ", "u").replace(" ", "")
    for cand in UNITS:
        if cand.lower().replace(" ", "") in u2.lower(): return cand
    if re.fullmatch(r"[gq][/l]?t?", u2.lower()): return "g/L"  # OCR of 'g/L'
    return u.strip()


def _parse_rows(body):
    rows, legacy, comment, in_comment = [], [], [], False
    for line in body.splitlines():
        line = line.strip()
        if not line: continue
        if re.search(r"multiply eGFR|African[- ]Caribbean|ethnicity", line, re.I):
            legacy.append(line); continue
        if line.lower().startswith("laboratory comment"):
            in_comment = True; rest = line.split(":", 1)[1].strip() if ":" in line else ""
            if rest: comment.append(rest)
            continue
        if in_comment:
            if re.search(r"is fictional|Page \d+ of", line): in_comment = False; continue
            comment.append(line); continue
        m = ROW_RE.match(line)
        if not m: continue
        label, rest = m.group("label"), m.group("rest")
        key = next(k for k, p in ANALYTES if re.fullmatch(p, label, re.I))
        vm = re.match(r"([<>]?\d+(?:\.\d+)?)\s*(.*)$", rest)
        if not vm: continue
        value, tail = vm.group(1), vm.group(2)
        rm = RANGE_RE.search(tail); rng = rm.group(1).strip() if rm else ""
        mid = tail[:rm.start()].strip() if rm else tail.strip()
        toks = mid.split(); flag = ""
        if toks and toks[0] in ("H", "L", "HH", "LL", "*"): flag = toks.pop(0)
        unit = _norm_unit(" ".join(toks))
        rows.append({"analyte": key, "label": label, "value": float(value.strip("<>")), "unit": unit,
                     "printed_range": rng, "lab_flag": flag})
    return rows, legacy, " ".join(comment)


def extract_report(data: bytes, filename: str):
    """Contract: returns values, units, ranges, OCR confidence (+ raw header text for redaction)."""
    ext = os.path.splitext(filename.lower())[1]
    if ext == ".pdf":
        hl, hr, body, conf = _pdf_text(data); source = "pdf_text"
    elif ext in (".png", ".jpg", ".jpeg", ".webp"):
        hl, hr, body, conf = _ocr_text(data, ext); source = "ocr"
    else:
        raise ValueError("Please upload a PDF or a photo (PNG/JPG).")
    rows, legacy, comment = _parse_rows(body)
    return {"source": source, "ocr_confidence": round(conf, 2), "header_left": hl, "header_right": hr,
            "rows": rows, "legacy_lines": legacy, "comment": comment}


# ============================================================ 2. REDACT (Presidio stand-in, fail-closed)
PATTERNS = {
    "NHS number": r"\b\d{3}\s?\d{3}\s?\d{4}\b",
    "Phone number": r"\b0\d{4}\s?\d{6}\b|\b0\d{3}\s?\d{3}\s?\d{4}\b",
    "Email": r"[\w.+-]+@[\w-]+\.[\w.]+",
    "Postcode": r"\b[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b",
    "Date": r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",
    "Clinician name": r"\bDr\.?\s+[A-Z][\w.'-]*(?:\s+[A-Z][\w'-]+(?:-[A-Z][\w'-]+)?)?",
    "Hospital/lab number": r"\b(?:RX\d{5,}|RCP-\d+-\d+)\b",
}


def _field(text, label, stop=None):
    m = re.search(rf"{label}\s*:\s*(.+)", text)
    return m.group(1).strip() if m else ""


GENERIC = {"practice", "medical", "surgery", "centre", "center", "health", "road", "street", "lane", "close", "way",
           "house", "flat", "avenue", "hill", "park", "haematology", "hospital", "clinic", "riverside", "grove",
           "walk", "vale"}


def redact_report(ex, report_date=None):
    """Contract: redacted text, removed identifier categories, derived (age band, sex). Fails closed."""
    hl, hr = ex["header_left"], ex["header_right"]
    ident = {}
    name = _field(hl, "Name"); dob = _field(hl, "DOB"); sexs = _field(hl, "Sex")
    if name: ident["Patient name"] = [name]
    addr_lines, grab = [], False
    for line in hl.splitlines():
        if line.startswith("Address"): grab = True; addr_lines.append(line.split(":", 1)[1].strip()); continue
        if grab and not re.match(r"^(Tel|Email|NHS|Hosp|Sex|DOB|Name)\b", line): addr_lines.append(line.strip())
        else: grab = False
    if addr_lines: ident["Address"] = addr_lines
    for lab in ["NHS No", "Hosp No", "Tel", "Email"]:
        v = _field(hl, lab)
        if v: ident.setdefault({"NHS No": "NHS number", "Hosp No": "Hospital/lab number", "Tel": "Phone number",
                                "Email": "Email"}[lab], []).append(v)
    for lab in ["Requested by", "Copy to", "Lab No", "Location"]:
        v = _field(hr, lab)
        if v: ident.setdefault({"Requested by": "Clinician name", "Copy to": "Clinician name",
                                "Lab No": "Hospital/lab number", "Location": "GP practice"}[lab], []).append(v)

    # derived, minimised context
    age = None; dob_v = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", dob)
    rd = report_date or date.today()
    coll = re.search(r"Collected:\s*(\d{1,2})/(\d{1,2})/(\d{4})", hr)
    if coll: rd = date(int(coll.group(3)), int(coll.group(2)), int(coll.group(1)))
    if dob_v:
        d = date(int(dob_v.group(3)), int(dob_v.group(2)), int(dob_v.group(1)))
        age = rd.year - d.year - ((rd.month, rd.day) < (d.month, d.day))
        ident["Date of birth"] = [dob_v.group(0)]
    sex = "F" if sexs.lower().startswith("f") else ("M" if sexs.lower().startswith("m") else None)
    band = f"{(age // 10) * 10}-{(age // 10) * 10 + 9}" if age is not None else "unknown"

    def scrub(t):
        removed = {}
        for cat, vals in ident.items():
            for v in sorted(vals, key=len, reverse=True):
                if v and v in t: t = t.replace(v, f"[{cat.upper()}]"); removed[cat] = removed.get(cat, 0) + 1
        # name tokens (handles "Ama Mensah" in free text even if printed upper-case in header)
        for tok in re.split(r"[\s-]+", name):
            if len(tok) >= 3:
                t, n = re.subn(rf"\b{re.escape(tok)}\b", "[PATIENT NAME]", t, flags=re.I)
                if n: removed["Patient name"] = removed.get("Patient name", 0) + n
        for cat, pat in PATTERNS.items():
            t, n = re.subn(pat, f"[{cat.upper()}]", t)
            if n: removed[cat] = removed.get(cat, 0) + n
        t = re.sub(r"(\[PATIENT NAME\][\s-]*)+", "[PATIENT NAME] ", t)
        return t, removed

    comment, rc = scrub(ex["comment"])
    # leak check: nothing identifying may survive in what goes downstream
    downstream = json.dumps({"rows": ex["rows"], "comment": comment})
    leaks = []
    for cat, vals in ident.items():
        for v in vals:
            for tok in re.split(r"[\s,]+", v):
                if tok.lower().strip(",.") in GENERIC: continue
                if len(tok) >= 4 and re.search(rf"\b{re.escape(tok)}\b", downstream, re.I) and not tok.isdigit():
                    leaks.append(f"{cat}: '{tok}'")
    for cat in ("NHS number", "Email", "Postcode"):
        if re.search(PATTERNS[cat], downstream): leaks.append(cat)
    categories = sorted(set(list(ident.keys()) + list(rc.keys())))
    if "Date of birth" in categories: categories[categories.index("Date of birth")] = "Date of birth (kept as age band)"
    return {"safe": not leaks, "leaks": leaks, "removed_categories": categories,
            "derived": {"age": age, "age_band": band, "sex": sex},
            "rows": ex["rows"], "comment": comment, "legacy_lines": ex["legacy_lines"],
            "ocr_confidence": ex["ocr_confidence"], "source": ex["source"],
            "header_preview": _redacted_header(band, sex)}


def _redacted_header(band, sex):
    return (f"Patient: [REMOVED]   Date of birth: [REMOVED → age band {band}]   "
            f"Sex on report: {'Female' if sex == 'F' else 'Male' if sex == 'M' else 'not stated'}\n"
            "NHS number: [REMOVED]   Hospital number: [REMOVED]   Address: [REMOVED]\n"
            "Requested by: [REMOVED]   Practice: [REMOVED]   Lab number: [REMOVED]")


# ============================================================ 3. INTERPRET (deterministic rules)
def _rng(a, sex):
    r = RANGES[a]
    if "all" in r: return r["all"]
    return r["female"] if sex == "F" else r["male"]


def _status(v, lo, hi):
    return "low" if v < lo else ("high" if v > hi else "normal")


def egfr_stage(v):
    for s, lo in [("G1", 90), ("G2", 60), ("G3a", 45), ("G3b", 30), ("G4", 15)]:
        if v >= lo: return s
    return "G5"


def interpret(redacted, context=None):
    """Returns {'scope', 'urgent', 'results': [...] }. context: pregnant(bool), gestation_weeks, hormones('oestradiol'|
    'testosterone'|None), hormone_months, duffy_null(True|False|None)."""
    ctx = context or {}; d = redacted["derived"]; sex = d["sex"]; age = d["age"]
    out = {"scope": "ok", "urgent": False, "results": [], "notes": []}
    if age is not None and age < 18:
        out["scope"] = "under_18"; return out
    if redacted["legacy_lines"]:
        out["notes"].append("Your report also shows an eGFR 'adjusted for ethnicity'. We ignore that figure: since 2021 "
                            "NICE has recommended UK labs stop using ethnicity adjustments for kidney function.")
    for r in redacted["rows"]:
        a, v, unit = r["analyte"], r["value"], (r["unit"] or "").strip()
        res = {"analyte": a, "value": v, "unit": unit, "lab_range": r["printed_range"], "lab_flag": r["lab_flag"],
               "range_used": None, "range_label": "", "alt_range": None, "status": None, "uncertainty": None,
               "conversion": None}
        exp = EXPECTED_UNIT.get(a, "")
        if a == "creatinine" and unit.lower() == "mg/dl":
            v = round(v * 88.4); res["conversion"] = f"Converted {r['value']} mg/dL to {v} µmol/L (UK units)."
            res["value"], res["unit"], unit = v, "umol/L", "umol/L"
        if not unit:
            res["status"] = "unchecked"; res["uncertainty"] = "No unit was printed for this result, so we can't safely "\
                                                              "compare it with a range. Please check the original report."
            out["results"].append(res); continue
        lo_p, hi_p = PLAUSIBLE.get(a, (None, None))
        if lo_p is not None and not (lo_p <= v <= hi_p):
            res["status"] = "unchecked"; res["uncertainty"] = (f"{v} {unit} isn't a realistic value for this test, so it "
                                                               "may be a printing or reading error. We won't interpret it.")
            out["results"].append(res); continue

        if a == "haemoglobin" and ctx.get("pregnant"):
            wk = ctx.get("gestation_weeks") or 0
            thr = RANGES[a]["pregnancy_threshold"]["trimester_1" if wk < 13 else "trimester_2_3"]
            res.update(range_used=[thr, None], range_label=f"pregnancy guide (at least {thr} g/L at {wk} weeks)",
                       status="low" if v < thr else "normal")
            res["uncertainty"] = "Pregnancy changes blood volume, so a different guide applies. Your midwife will " \
                                 "look at this at your antenatal checks."
        elif a == "haemoglobin" and ctx.get("hormones") in ("oestradiol", "testosterone"):
            m, f = RANGES[a]["male"], RANGES[a]["female"]
            aff = f if ctx["hormones"] == "oestradiol" else m
            other = m if aff is f else f
            res.update(range_used=aff, alt_range=other, status=_status(v, *aff),
                       range_label=f"{'female' if aff is f else 'male'} range, matching your hormone therapy")
            res["uncertainty"] = ("Hormone therapy changes haemoglobin, but research on the right range is limited. "
                                  "We show both ranges; please confirm which applies with your GP or gender clinic.")
            if ctx.get("hormone_months", 12) < 6:
                res["uncertainty"] += " In the first months of therapy, results often sit between the two ranges."
        elif a == "neutrophils" and ctx.get("duffy_null") is True:
            dn = RANGES[a]["duffy_null"]
            res.update(range_used=dn, alt_range=_rng(a, sex), status=_status(v, *dn),
                       range_label="Duffy-null range, which you told us applies to you")
        elif a == "egfr":
            if ctx.get("pregnant"):
                res.update(status="abstain", range_label="not interpreted",
                           uncertainty="The eGFR calculation isn't designed for pregnancy, so we won't interpret this "
                                       "number. Your midwife or GP can explain your kidney results.")
            else:
                st = egfr_stage(v)
                res.update(range_used=[90, None] if v >= 90 else [60, None], status="normal" if v >= 60 else "low",
                           range_label=f"kidney function band {st} (CKD-EPI, no ethnicity adjustment)")
        elif a == "hba1c":
            band = "normal" if v < 42 else ("increased_risk" if v < 48 else "high")
            res.update(range_used=[None, 41], status="normal" if band == "normal" else "high",
                       range_label={"normal": "below 42 mmol/mol (usual range)",
                                    "increased_risk": "42–47 mmol/mol: higher than usual, below the diabetes range",
                                    "high": "48 mmol/mol or above"}[band])
        else:
            rr = _rng(a, sex); res.update(range_used=rr, range_label="standard range for your sex" if "all" not in
                                          RANGES[a] else "standard range", status=_status(v, *rr))
        if a == "potassium" and v >= RANGES[a]["critical_high"]:
            res["status"] = "critical"; out["urgent"] = True
        if a == "neutrophils" and v < 0.5: res["status"] = "critical"; out["urgent"] = True
        if a == "haemoglobin" and v < 70: res["status"] = "critical"; out["urgent"] = True
        if a == "neutrophils" and res["status"] == "low" and ctx.get("duffy_null") is None:
            res["uncertainty"] = ("Mildly low neutrophils are common and often harmless. Some healthy people, including "
                                  "many with the Duffy-null blood type, naturally have lower counts. You could ask your "
                                  "GP whether a Duffy blood group test is relevant to you.")
        if a == "wbc" and res["status"] == "low" and ctx.get("duffy_null") is True:
            res["uncertainty"] = ("Your total white count is slightly below the lab range, mostly because neutrophils "
                                  "are part of it. There isn't a separate white-count range for Duffy-null in this tool.")
        out["results"].append(res)
    return out


# ============================================================ 4. EXPLAIN
WORDS = {"low": "lower than the usual range", "high": "higher than the usual range", "normal": "within the range",
         "critical": "outside the safe range and needs prompt attention", "abstain": "not interpreted",
         "unchecked": "not checked"}


def fmt_range(r):
    if not r: return "—"
    lo, hi = r
    if lo is not None and hi is not None: return f"{lo:g}–{hi:g}"
    return f"at least {lo:g}" if lo is not None else f"up to {hi:g}"


def explain(interp):
    """Returns list of cards: {analyte, title, value_line, headline, what, meaning, uncertainty, sources, status}."""
    cards = []
    for r in interp["results"]:
        name, what, _ = K.test_text(r["analyte"], None)
        direction = r["status"] if r["status"] in ("low", "high") else ("high" if r["status"] == "critical" and
                                                                         r["analyte"] == "potassium" else
                                                                         "low" if r["status"] == "critical" else None)
        _, _, meaning = K.test_text(r["analyte"], direction)
        st = r["status"]
        if st in ("normal", "low", "high", "critical"):
            headline = f"Your result is {WORDS[st]}"
            if r["range_label"] and not r["range_label"].startswith("standard"):
                headline += f" ({r['range_label']})."
            else: headline += "."
            if r["lab_flag"] and st == "normal":
                headline += " The lab marked it because it uses a general range. You can compare both ranges above."
        else:
            headline = WORDS[st].capitalize() + "."
        cards.append({"analyte": r["analyte"], "title": name, "status": st,
                      "value_line": f"{r['value']:g} {r['unit']}".strip(), "headline": headline, "what": what,
                      "meaning": meaning if st in ("low", "high", "critical") else "", "uncertainty": r["uncertainty"],
                      "lab_range": r["lab_range"], "your_range": fmt_range(r["range_used"]) if r["range_used"] else "—",
                      "alt_range": fmt_range(r["alt_range"]) if r["alt_range"] else None,
                      "conversion": r["conversion"], "lab_flag": r["lab_flag"], "sources": K.retrieve_evidence(r["analyte"])})
    return cards


def next_step(interp):
    if interp["scope"] == "under_18":
        return ("abstain", "CarePath is designed for adults, so we can't explain this report. Please ask the GP practice, "
                           "or a parent or guardian can speak to them.")
    if interp["urgent"]:
        return ("urgent", "One result needs prompt attention. Contact your GP surgery today or call NHS 111. If you feel "
                          "very unwell, have chest pain or palpitations, call 999.")
    if any(r["status"] in ("low", "high") for r in interp["results"]):
        return ("routine", "Some results are outside the range. Your GP practice normally reviews results and will "
                           "contact you if follow-up is needed. If you haven't heard, or you have symptoms, book a routine "
                           "appointment and take the summary below.")
    return ("none", "Everything we could check is within range. Your GP practice will contact you if they want to "
                    "discuss anything.")


def gp_questions(cards):
    q = []
    for c in cards:
        if c["status"] in ("low", "high", "critical"):
            q.append(f"My {c['title']} was {c['value_line']} — what does that mean for me, and does it need rechecking?")
        if c["alt_range"]:
            q.append(f"Which reference range should be used for my {c['title']}?")
    if not q: q.append("Is there anything in these results you'd like me to keep an eye on?")
    return q


def gp_summary(redacted, interp, cards, context):
    lines = ["CarePath summary to discuss with my GP (no personal details included)", "",
             f"Age band: {redacted['derived']['age_band']}   Sex on report: {redacted['derived']['sex'] or '-'}"]
    if context: lines.append("Context I shared: " + ", ".join(f"{k}={v}" for k, v in context.items() if v not in
                                                             (None, False, "")))
    lines += ["", "Result | Value | Lab range | Range CarePath used | Status"]
    for c in cards:
        lines.append(f"{c['title']} | {c['value_line']} | {c['lab_range'] or '-'} | {c['your_range']} | {c['status']}")
    lines += ["", "Questions:"] + [f"- {q}" for q in gp_questions(cards)]
    lines += ["", "CarePath explains results; it does not diagnose. Prototype using synthetic data."]
    return "\n".join(lines)


# ============================================================ 5. FOLLOW-UP (guarded)
RX = re.compile(r"\b(prescri\w*|dose|dosage|how (many|much) (tablet|pill|mg)|mg\b|should i (take|stop|start)|"
                r"tablets?|supplements?|medicine|medication|ferrous|antibiotic)", re.I)
DX = re.compile(r"\b(do i have|have i got|is (it|this) (cancer|serious|leukaemia|diabetes)|diagnos\w*|am i (sick|ill|"
                r"dying|diabetic))", re.I)
ALIASES = {"haemoglobin": r"haemoglobin|hemoglobin|\bhb\b|anaemi", "wbc": r"white (cell|blood)|wbc",
           "neutrophils": r"neutrophil|duffy", "lymphocytes": r"lymphocyte", "platelets": r"platelet",
           "mcv": r"\bmcv\b|cell size", "sodium": r"sodium", "potassium": r"potassium", "urea": r"\burea\b",
           "creatinine": r"creatinine", "egfr": r"egfr|kidney", "hba1c": r"hba1c|sugar|glucose",
           "ferritin": r"ferritin|iron", "tsh": r"\btsh\b|thyroid", "free_t4": r"\bt4\b"}


def validate_response(text):
    """Contract: blocks dosing numbers and diagnostic phrasing from model output."""
    if re.search(r"\b\d+\s?(mg|mcg|micrograms?)\b", text, re.I): return False
    if re.search(r"\byou (have|'ve got|are suffering from)\b", text, re.I): return False
    return True


def _ollama(question, cards):
    model = os.environ.get("OLLAMA_MODEL")
    if not model: return None
    try:
        import urllib.request
        facts = [{k: c[k] for k in ("title", "value_line", "status", "your_range", "lab_range")} for c in cards]
        prompt = ("You explain blood test results in plain UK English for a patient. Use ONLY these facts: "
                  f"{json.dumps(facts)}. Never diagnose, never suggest medicines or doses, keep under 120 words, "
                  f"and suggest asking the GP when unsure.\nQuestion: {question}")
        req = urllib.request.Request("http://localhost:11434/api/generate", data=json.dumps(
            {"model": model, "prompt": prompt, "stream": False}).encode(), headers={"Content-Type": "application/json"})
        txt = json.loads(urllib.request.urlopen(req, timeout=60).read())["response"].strip()
        return txt if validate_response(txt) else None
    except Exception:
        return None


def answer_followup(question, cards):
    q = question.strip()
    if RX.search(q):
        return ("I can't recommend medicines, supplements or doses. That needs someone who knows your full medical "
                "history. Please ask your GP or a pharmacist; a pharmacist can usually advise without an appointment.",
                "refused_prescription")
    if DX.search(q):
        return ("I can't diagnose conditions. I can only explain what each result on this report measures and how it "
                "compares with the range. Your GP can tell you what your results mean for your health.",
                "refused_diagnosis")
    if re.search(r"ask (my )?gp|what should i ask|questions", q, re.I):
        return "Here are some questions you could take to your GP:\n" + "\n".join(
            f"- {x}" for x in gp_questions(cards)), "gp_questions"
    if re.search(r"why .*range|different range|which range", q, re.I):
        alt = [c for c in cards if c["alt_range"]]
        if alt:
            return ("'Normal' ranges are based on large groups of people, and they don't fit everyone. For "
                    + ", ".join(c["title"] for c in alt) + " we used a range that matches what you told us, and we show "
                    "the lab's range next to it so you and your GP can compare."), "range_explained"
        return ("We used the standard range for each test, based on the sex printed on your report. If something like "
                "pregnancy or hormone therapy applies, you can add it, as it can change which range fits."), "range_explained"
    hits = [c for c in cards if re.search(ALIASES.get(c["analyte"], "$^"), q, re.I)]
    if hits:
        c = hits[0]
        parts = [f"**{c['title']}: {c['value_line']}**", c["what"], c["headline"]]
        if c["meaning"]: parts.append(c["meaning"])
        if c["uncertainty"]: parts.append(c["uncertainty"])
        src = c["sources"][0] if c["sources"] else None
        if src: parts.append(f"Source: [{src['title']}]({src['url']})")
        return "\n\n".join(parts), "explained"
    llm = _ollama(q, cards)
    if llm: return llm + "\n\n_Generated by a local model from your redacted results; check with your GP._", "llm"
    return ("I can only answer questions about the results on this report. Try asking about a specific test, for "
            "example \"what is ferritin?\", or ask \"what should I ask my GP?\"", "out_of_scope")


# ============================================================ 6. DELETE (verified)
SENSITIVE_KEYS = ["upload_bytes", "upload_name", "extracted", "redacted", "interp", "cards", "context", "chat",
                  "edited_rows", "summary", "editor"]


KEY_LABELS = {"upload_bytes": "Uploaded file", "upload_name": "File name", "extracted": "Text read from the report",
              "redacted": "Redacted report", "interp": "Range checks", "cards": "Explanations",
              "context": "Extra details you shared", "chat": "Your questions and answers",
              "edited_rows": "Your corrections", "summary": "GP summary", "editor": "Table edits"}


def delete_session(state: dict, temp_paths=()):
    """Contract: deletes artefacts, then checks each one is really gone. Never reports success unverified."""
    report = []
    for p in temp_paths:
        try:
            if os.path.exists(p): os.remove(p)
        except Exception as e:
            pass
        report.append((f"Temporary file {os.path.basename(p)}", not os.path.exists(p)))
    for k in SENSITIVE_KEYS:
        if k in state: del state[k]
    for k in SENSITIVE_KEYS:
        report.append((KEY_LABELS.get(k, k), k not in state))
    return {"all_deleted": all(ok for _, ok in report), "items": report,
            "time": datetime.now().strftime("%H:%M:%S")}
