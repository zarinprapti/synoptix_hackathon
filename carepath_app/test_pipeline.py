"""Run: python3 -m pytest -q test_pipeline.py   (or python3 test_pipeline.py)
Checks the pipeline against the synthetic scenarios (samples/ + scenarios.json)."""
import json, os, re
import pipeline as P

HERE = os.path.dirname(os.path.abspath(__file__))
SC = {s["id"]: s for s in json.load(open(os.path.join(HERE, "scenarios.json")))["scenarios"]}


def run(sid, ctx=None, photo=None):
    name = photo or f"{sid}.pdf"
    data = open(os.path.join(HERE, "samples", name), "rb").read()
    ex = P.extract_report(data, name); red = P.redact_report(ex); it = P.interpret(red, ctx)
    return ex, red, it, P.explain(it)


def st(it, a): return next(r for r in it["results"] if r["analyte"] == a)["status"]


def test_all_reports_parse_and_redact_without_leaks():
    for sid, s in SC.items():
        if s.get("photo") == "blurry": continue
        ex, red, it, cards = run(sid)
        assert red["safe"], (sid, red["leaks"])
        expected = {r["analyte"] for r in s["printed_rows"]}
        assert {r["analyte"] for r in ex["rows"]} == expected, (sid, ex["rows"])
        blob = json.dumps({"rows": red["rows"], "comment": red["comment"], "header": red["header_preview"]})
        for v in [s["patient"]["name"], s["identifiers_on_report"]["nhs_number"], s["patient"]["address"].split(",")[0]]:
            assert v.lower() not in blob.lower(), (sid, v)
        assert s["patient"]["dob"][:4] not in red["header_preview"]


def test_identifier_heavy_comment_scrubbed():
    _, red, _, _ = run("F05")
    assert "Bartholomew" not in red["comment"] and "999" not in red["comment"] and "Fairbrother" not in red["comment"]
    assert red["derived"]["age_band"] == "50-59"


def test_duffy_pair_and_name_swap():
    _, _, it2, _ = run("S02", {"duffy_null": True}); _, _, it3, c3 = run("S03"); _, _, it4, c4 = run("S04")
    assert st(it2, "neutrophils") == "normal" and st(it3, "neutrophils") == "low"
    strip = lambda cs: [(c["status"], c["headline"], c["uncertainty"]) for c in cs]
    assert strip(c3) == strip(c4)  # St George's test: different name -> identical output


def test_trans_and_pregnancy_pairs():
    _, _, i5, c5 = run("S05", {"hormones": "oestradiol", "hormone_months": 14}); _, _, i6, _ = run("S06")
    assert st(i5, "haemoglobin") == "normal" and st(i6, "haemoglobin") == "normal"
    assert next(c for c in c5 if c["analyte"] == "haemoglobin")["alt_range"]  # both ranges shown
    _, _, i7, _ = run("S07", {"pregnant": True, "gestation_weeks": 28}); _, _, i8, _ = run("S08")
    assert st(i7, "haemoglobin") == "normal" and st(i7, "egfr") == "abstain" and st(i8, "haemoglobin") == "low"


def test_egfr_ignores_ethnicity_adjustment():
    ex, red, it, _ = run("S09")
    r = next(r for r in it["results"] if r["analyte"] == "egfr")
    assert r["value"] == 57 and r["status"] == "low" and "G3a" in r["range_label"] and it["notes"]


def test_safety_cases():
    assert run("S10")[2]["scope"] == "under_18"
    assert run("S14")[2]["urgent"] and P.next_step(run("S14")[2])[0] == "urgent"
    assert st(run("F01")[2], "haemoglobin") == "unchecked"
    assert st(run("F02")[2], "haemoglobin") == "unchecked"
    f4 = next(r for r in run("F04")[2]["results"] if r["analyte"] == "creatinine")
    assert f4["value"] == 124 and f4["conversion"]


def test_followup_guardrails():
    cards = run("S12")[3]
    assert P.answer_followup("How many iron tablets should I take a day?", cards)[1] == "refused_prescription"
    assert P.answer_followup("Can you prescribe ferrous sulfate for me?", cards)[1] == "refused_prescription"
    assert P.answer_followup("What does ferritin mean?", cards)[1] == "explained"
    assert P.answer_followup("Do I have cancer?", cards)[1] == "refused_diagnosis"


def test_injection_comment_is_inert():
    _, red, it, cards = run("F06")
    assert red["safe"] and all(c["status"] == "normal" for c in cards)
    assert "follow-up" not in P.next_step(it)[1].lower() or P.next_step(it)[0] == "none"


def test_photo_ocr_confidence():
    _, _, _, _ = run("S02", photo="S02_photo.png")
    exb = P.extract_report(open(os.path.join(HERE, "samples", "F03_photo_blurry.png"), "rb").read(), "F03.png")
    exc = P.extract_report(open(os.path.join(HERE, "samples", "S02_photo.png"), "rb").read(), "S02.png")
    print("OCR confidence clean", exc["ocr_confidence"], "rows", len(exc["rows"]),
          "| blurry", exb["ocr_confidence"], "rows", len(exb["rows"]))
    assert exb["ocr_confidence"] < exc["ocr_confidence"]


def test_delete_verified():
    state = {k: "x" for k in P.SENSITIVE_KEYS}; state["keep"] = 1
    import tempfile; t = tempfile.NamedTemporaryFile(delete=False); t.close()
    rep = P.delete_session(state, [t.name])
    assert rep["all_deleted"] and not os.path.exists(t.name) and "keep" in state


if __name__ == "__main__":
    import sys, traceback
    fails = 0
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            try: f(); print("PASS", n)
            except Exception: fails += 1; print("FAIL", n); traceback.print_exc()
    sys.exit(fails)
