# CarePath AI – patient chatbot (Member 3)

## Run it
```bash
pip install -r requirements.txt          # also needs Tesseract installed for photo uploads
streamlit run app.py                     # opens http://localhost:8501
python3 test_pipeline.py                 # 10 test groups over the 20 synthetic scenarios
```
Optional local model for open follow-up questions: run Ollama and set `OLLAMA_MODEL=llama3.2:3b` (or similar).
Without it, the chatbot still works: answers come from the curated explanations.

## The journey
1. **Consent:** plain-English explanation of what happens to the data.
2. **Upload:** PDF or photo (or a synthetic sample for the demo). Raw bytes are dropped as soon as text is read.
   Blurry photos (OCR confidence < 60%) are rejected, not guessed.
3. **Redaction + check:** shows what was removed, the redacted header, and an **editable** results table. Nothing
   is explained until the user clicks *Yes, this is correct*. Fails closed if any identifier survives.
4. **Optional context:** pregnancy, gender-affirming hormones, known Duffy-null status. Never inferred from name or
   background. Kept for the session only.
5. **Results:** next-step banner (urgent / routine / none), a card per result showing **lab range vs range used for
   you**, what it measures, what it can mean, *What I'm not sure about*, and NHS source links. Downloadable GP summary.
6. **Follow-up chat:** refuses medicine/dose and diagnosis questions; explains tests; suggests GP questions.
7. **Delete:** clears every sensitive session item, then **checks** each is gone before saying so.

## Files and who swaps what
| File | Owner | Notes |
|---|---|---|
| `app.py` | Member 3 | Streamlit UI. Only talks to `pipeline.py`. |
| `pipeline.py` | Members 1 & 2 | Same function names as the brief: `extract_report`, `redact_report`, `interpret`, `explain`, `answer_followup`, `validate_response`, `delete_session`. |
| `knowledge.py` | Member 2 | Curated plain-English text + verified NHS links. Replace with RAG, keeping `retrieve_evidence()` / `test_text()`. |
| `ranges.json`, `scenarios.json`, `samples/` | Member 4 | From the synthetic test pack. |

**Member 1:** `redact_report()` is a regex stand-in for Presidio. Keep its output shape (`safe`, `leaks`,
`removed_categories`, `derived`, `rows`, `comment`, `header_preview`) and the UI won't need changes.

## 3-minute demo script
1. **S02 + Duffy-null = Yes:** lab says neutrophils LOW; CarePath shows both ranges and says within range for her.
2. **S03, then S04:** same numbers, no Duffy info → stays low with a gentle note; a different name gives an
   identical answer (the St George's test).
3. **S09:** ignores the old ethnicity-adjusted eGFR and explains why.
4. **S12:** ask *"Can you prescribe iron tablets?"* → polite refusal.
5. **F05:** show the redaction chips; **F03 photo:** blurry photo is refused.
6. Click **I'm finished: delete my data** → verified deletion checklist.

## Known limits (say these out loud – judges like honesty)
- Redaction is pattern-based until Presidio is wired in; OCR on photos is fragile.
- Ranges are illustrative; items marked VERIFY in `ranges.json` need checking.
- Streamlit keeps data in server memory per session; deletion clears it, but production would need an audited store.
- Synthetic reports only. Not clinically validated. Not a medical device.
