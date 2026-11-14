# CarePath AI

**Understand your blood test, privately.**

CarePath AI is a chatbot that explains UK blood test reports in plain English. You upload a PDF or a photo of your
report. CarePath removes your personal details, asks you to check what it read, and then explains each result. It
shows which reference range it used for you and links to NHS sources. When you finish, it deletes your data and
checks that the data is gone.

Built for the UWE Responsible AI Hackathon 2026. CarePath is a prototype: it runs on synthetic reports only. It is
not a medical device, and it does not diagnose conditions or recommend medicines.

---

## Why it exists

Standard "normal" ranges come from large population averages, so they don't fit everyone. Some examples:

- People with the **Duffy-null** blood type often have lower neutrophil counts and are healthy.
- **Pregnancy** changes the haemoglobin threshold.
- **Gender-affirming hormones** change which haemoglobin range applies.
- Older eGFR results were **adjusted for ethnicity**. NICE (2021) now recommends the unadjusted value.

CarePath uses a different range only when the user tells it about one of these. It never guesses from someone's
name or background, and it always shows the lab's own range next to the range it used.

## The user journey

1. **Consent:** explains what happens to the data before anything is uploaded.
2. **Upload:** PDF or phone photo. The raw file is held in memory and dropped as soon as the text is read.
   CarePath rejects a blurry photo (OCR confidence below 60%) rather than guessing at the numbers.
3. **Redaction and check:** removes names, NHS and hospital numbers, addresses, postcodes, phone numbers,
   emails, dates and clinician names.
   CarePath stops if any identifier is still there after redaction. The user sees an **editable** table of results
   and confirms it before anything is explained.
4. **Optional context:** pregnancy, gender-affirming hormones, known Duffy-null status. Kept for the session only.
5. **Results:** a next-step banner (urgent, routine or none) and one card per result. Each card shows the lab range,
   the range used for you, what the test measures, what the result can mean, a *What I'm not sure about* note and
   NHS links. The user can download a summary for their GP with no personal details in it.
6. **Follow-up chat:** answers questions about the tests. It refuses to discuss medicines, doses or diagnoses, and
   it suggests questions to ask the GP.
7. **Delete:** clears every sensitive item from the session, then checks each one is gone and shows a checklist.

## Quick start

```bash
cd carepath_app
pip install -r requirements.txt
streamlit run app.py          # opens http://localhost:8501
```

The upload screen has a list of synthetic sample reports, so you can try the app without a real report.

**Optional extras**

| Feature | What you need |
|---|---|
| Photo uploads (OCR) | [Tesseract](https://github.com/tesseract-ocr/tesseract) installed and on your `PATH` |
| Free-text follow-up answers | [Ollama](https://ollama.com) running locally, plus `OLLAMA_MODEL=llama3.2:3b` (or similar) set |

Without Ollama, the follow-up chat still works and answers come from curated explanations. CarePath checks every
model answer against the same guardrails and falls back to the curated text if an answer fails them. The app never
sends data to an outside AI service.

## Running the tests

```bash
cd carepath_app
python -m pytest -q test_pipeline.py     # or: python test_pipeline.py
```

There are 10 test groups. They run the pipeline over the 20 synthetic scenarios and cover:

- parsing and leak-free redaction
- Duffy-null, pregnancy and hormone context pairs
- the "name swap" check (same values with a different name must give identical output)
- eGFR ethnicity adjustment
- under-18 abstention and critical results
- follow-up guardrails
- prompt injection in lab comments
- OCR confidence
- verified deletion

## Project layout

```
carepath_app/
├── app.py              Streamlit UI (talks only to pipeline.py)
├── pipeline.py         extract → redact → interpret → explain → follow-up → delete
├── knowledge.py        Curated plain-English explanations and NHS source links
├── ranges.json         Reference ranges and the sources for each one
├── scenarios.json      Ground truth for the synthetic test scenarios
├── samples/            Synthetic PDF reports and photos (S01–S14, F01–F06)
└── test_pipeline.py    Scenario-based tests
carepath_test_pack_README.md   Details of the synthetic test pack
```

### Pipeline functions (`pipeline.py`)

| Function | Role |
|---|---|
| `extract_report()` | Reads text from a PDF with pdfplumber, or from a photo with Tesseract OCR. Parses the result rows and normalises units. |
| `redact_report()` | Removes identifiers using patterns, keeps only the age band and sex, and fails closed if anything leaks. |
| `interpret()` | Picks the range with fixed rules, not an LLM. Handles context-specific ranges and recalculates eGFR without ethnicity adjustment. |
| `explain()` | Builds the result cards from `knowledge.py`. |
| `answer_followup()` / `validate_response()` | Guarded follow-up chat, with an optional local LLM. |
| `delete_session()` | Clears the session data and checks that each item was removed. |

## Sample scenarios worth trying

| Sample | What it shows |
|---|---|
| **S02** (answer *Duffy-null = Yes*) | The lab flags neutrophils as low, but they are within the Duffy-null range. CarePath shows both ranges. |
| **S03 → S04** | Identical values and different names give identical output. Without context, the low neutrophil result is not quietly reclassified. |
| **S05** (add oestradiol) | Haemoglobin judged against the hormone-adjusted range, with both ranges and an uncertainty note. |
| **S07** (add pregnancy, 28 weeks) | Pregnancy haemoglobin threshold applied. CarePath doesn't interpret eGFR because it isn't validated in pregnancy. |
| **S09** | Ignores the legacy ethnicity-adjusted eGFR and explains why. |
| **S12** | Ask *"Can you prescribe iron tablets?"* and CarePath politely refuses. |
| **S14** | Critical potassium result, with an urgent next-step message. |
| **F05 / F06** | A report full of identifiers, and a lab comment containing a hidden instruction. CarePath scrubs the first and ignores the instruction. |
| **F03 photo** | A blurry photo, which CarePath refuses to read. |

## Known limitations

- Redaction uses regular expressions until Microsoft Presidio is added. OCR on photos is fragile.
- The reference ranges are examples and vary between labs. Entries marked `VERIFY` in `ranges.json` need checking.
  A real deployment would need sign-off from a chemical pathologist or haematologist.
- Streamlit keeps session data in server memory. Deletion clears it, but a production system would need an audited
  data store.
- Tested on synthetic data only. Not clinically validated. Not a medical device.

## Data notice

Every report in this repository is **synthetic**. "Riverside Community Pathology Service" is fictional, and the NHS
numbers use the 999 test prefix. Do not add real patient reports.
