"""
Plain-English explanations per test.

PLACEHOLDER for Member 2's retrieve_evidence()/generate_explanation(). Texts are written by the team in our own
words (not copied from NHS pages) and each links to the NHS page a reader can check. URLs verified 24 Oct 2026.
Swap this module for the RAG version without changing app.py: keep the same function signatures.
"""

NHS = {
    "blood_tests": ("Blood tests - NHS", "https://www.nhs.uk/tests-and-treatments/blood-tests/"),
    "red_blood_count": ("Red blood count - NHS", "https://www.nhs.uk/tests-and-treatments/red-blood-count/"),
    "low_wbc": ("Low white blood cell count - NHS", "https://www.nhs.uk/conditions/low-white-blood-cell-count/"),
    "ida": ("Iron deficiency anaemia - NHS", "https://www.nhs.uk/conditions/iron-deficiency-anaemia/"),
    "electrolytes": ("Electrolyte test - NHS", "https://www.nhs.uk/tests-and-treatments/electrolyte-test/"),
    "ckd": ("Chronic kidney disease: diagnosis - NHS", "https://www.nhs.uk/conditions/kidney-disease/diagnosis/"),
    "t2d": ("Type 2 diabetes: getting diagnosed - NHS", "https://www.nhs.uk/conditions/type-2-diabetes/getting-diagnosed/"),
    "thyroid": ("Underactive thyroid: diagnosis - NHS",
                "https://www.nhs.uk/conditions/underactive-thyroid-hypothyroidism/diagnosis/"),
    "antenatal": ("Antenatal checks and tests - NHS",
                  "https://www.nhs.uk/pregnancy/your-pregnancy-care/antenatal-checks-and-tests/"),
}

TESTS = {
    "haemoglobin": dict(
        name="Haemoglobin (Hb)",
        what="Haemoglobin is the protein in red blood cells that carries oxygen around your body.",
        low="A lower level can mean fewer red blood cells or less haemoglobin in them, often called anaemia. "
            "Common reasons include low iron, blood loss or pregnancy, but only a clinician can say why.",
        high="A higher level can happen with dehydration, smoking or living at altitude, among other reasons.",
        sources=["red_blood_count", "ida"]),
    "wbc": dict(
        name="White cell count",
        what="White blood cells are part of your immune system and help fight infection.",
        low="A lower count can follow a recent viral infection, some medicines, or can simply be normal for some "
            "people.",
        high="A higher count often happens when the body is fighting an infection or inflammation.",
        sources=["low_wbc"]),
    "neutrophils": dict(
        name="Neutrophils",
        what="Neutrophils are the most common type of white blood cell. They are the body's first responders to "
             "bacterial infection.",
        low="A mildly low count is common and often harmless. It can follow a viral infection or some medicines. "
            "Some healthy people, including many with the 'Duffy-null' blood type, naturally have lower counts.",
        high="A higher count often happens during infection, inflammation, stress or with some medicines.",
        sources=["low_wbc"]),
    "lymphocytes": dict(
        name="Lymphocytes",
        what="Lymphocytes are white blood cells that help your body recognise and remember infections.",
        low="A lower count can follow a viral infection, stress or some medicines.",
        high="A higher count is often seen during or after a viral infection.",
        sources=["blood_tests"]),
    "platelets": dict(
        name="Platelets",
        what="Platelets are tiny cells that help your blood clot when you are cut or injured.",
        low="A lower count can follow infections or some medicines; your GP may want to recheck it.",
        high="A higher count can happen with inflammation, infection or low iron.",
        sources=["blood_tests"]),
    "mcv": dict(
        name="MCV (red cell size)",
        what="MCV is the average size of your red blood cells.",
        low="Smaller red cells are often linked with low iron.",
        high="Larger red cells can be linked with low vitamin B12 or folate, alcohol, or some medicines.",
        sources=["red_blood_count", "ida"]),
    "sodium": dict(
        name="Sodium", what="Sodium is a salt in your blood that helps control fluid balance and nerves.",
        low="Lower sodium can be related to fluid balance or some medicines.",
        high="Higher sodium is often related to not drinking enough fluid.", sources=["electrolytes"]),
    "potassium": dict(
        name="Potassium", what="Potassium is a salt in your blood that helps your heart and muscles work properly.",
        low="Lower potassium can happen with sickness, diarrhoea or some medicines.",
        high="Higher potassium can affect the heart. Very high levels need checking quickly. Sometimes a high result "
             "is caused by the blood sample itself, which is why clinicians often repeat it.",
        sources=["electrolytes"]),
    "urea": dict(
        name="Urea", what="Urea is a waste product your kidneys remove from your blood.",
        low="Lower urea is usually not a concern.",
        high="Higher urea can be linked with dehydration or how well the kidneys are filtering.", sources=["ckd"]),
    "creatinine": dict(
        name="Creatinine", what="Creatinine is a waste product from your muscles. Your kidneys filter it out, so it is "
                                "used to estimate kidney function.",
        low="Lower creatinine is often linked with lower muscle mass and is usually not a concern.",
        high="Higher creatinine can mean the kidneys are filtering less well, but muscle mass, diet and hydration "
             "also affect it.", sources=["ckd"]),
    "egfr": dict(
        name="eGFR (estimated kidney function)",
        what="eGFR estimates how well your kidneys filter blood. It is calculated from creatinine, age and sex.",
        low="A lower eGFR can mean the kidneys are filtering less well. One result on its own does not confirm kidney "
            "disease; clinicians usually repeat the test and check a urine test too.",
        high="", sources=["ckd"]),
    "hba1c": dict(
        name="HbA1c (average blood sugar)",
        what="HbA1c shows your average blood sugar level over roughly the last 2 to 3 months.",
        low="", high="A higher HbA1c means blood sugar has been higher than usual. Your GP uses this alongside other "
                     "information to decide whether anything needs doing.", sources=["t2d"]),
    "ferritin": dict(
        name="Ferritin (iron stores)", what="Ferritin shows how much iron your body has stored.",
        low="Low ferritin usually means your iron stores are low.",
        high="Higher ferritin can happen with inflammation, infection, liver conditions or iron overload.",
        sources=["ida"]),
    "tsh": dict(
        name="TSH (thyroid stimulating hormone)",
        what="TSH is made by a gland in your brain and tells your thyroid how hard to work.",
        low="A lower TSH can mean the thyroid is more active than usual.",
        high="A higher TSH can mean the brain is asking the thyroid to work harder. If free T4 is normal, GPs often "
             "recheck before deciding anything.", sources=["thyroid"]),
    "free_t4": dict(
        name="Free T4 (thyroid hormone)", what="Free T4 is the main hormone your thyroid gland makes.",
        low="A lower level can mean the thyroid is less active.", high="A higher level can mean it is more active.",
        sources=["thyroid"]),
}


def retrieve_evidence(analyte):
    """Contract: returns list of {title, url, source_id}."""
    t = TESTS.get(analyte)
    if not t: return []
    return [{"title": NHS[s][0], "url": NHS[s][1], "source_id": s} for s in t["sources"]]


def test_text(analyte, direction):
    """direction: 'low' | 'high' | None. Returns (name, what, meaning)."""
    t = TESTS.get(analyte)
    if not t: return analyte, "", ""
    meaning = t.get(direction, "") if direction else ""
    return t["name"], t["what"], meaning
