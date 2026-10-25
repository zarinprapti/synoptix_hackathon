"""
CarePath AI - patient chatbot (Member 3: frontend, access).
Run:  streamlit run app.py
Journey: consent -> upload -> automatic redaction -> user checks redacted report -> optional context ->
plain-English explanation with sources -> guarded follow-up chat -> verified deletion.
Synthetic reports only. Explains results; does not diagnose or prescribe.
"""
import html, os
import pandas as pd
import streamlit as st
import pipeline as P

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = {
    "S02 – Ama, neutrophils 1.6 (try with Duffy-null = yes)": "S02.pdf",
    "S03 – same report, Duffy status not given": "S03.pdf",
    "S04 – same values, different name": "S04.pdf",
    "S05 – Hb 125, on oestradiol (add hormone therapy)": "S05.pdf",
    "S07 – pregnant, 28 weeks (add pregnancy)": "S07.pdf",
    "S09 – kidney function with old ethnicity adjustment": "S09.pdf",
    "S12 – low ferritin (try asking for a prescription)": "S12.pdf",
    "S14 – critical potassium": "S14.pdf",
    "F05 – lots of personal details": "F05.pdf",
    "F06 – hidden instruction in lab comment": "F06.pdf",
    "S10 – under 18": "S10.pdf",
    "S01 – everything normal": "S01.pdf",
    "S02 photo – phone picture": "S02_photo.png",
    "F03 photo – blurry phone picture": "F03_photo_blurry.png",
}
STEPS = [("consent", "Agree to how we use your data"), ("upload", "Upload your report"),
         ("check", "Check personal details are removed"), ("context", "Anything that changes your range? (optional)"),
         ("results", "Your results explained"), ("deleted", "Data deleted")]
STATUS_STYLE = {"critical": ("#b3261e", "Needs prompt attention"), "low": ("#b26a00", "Below range"),
                "high": ("#b26a00", "Above range"), "normal": ("#2e7d32", "Within range"),
                "unchecked": ("#5f6368", "Not checked"), "abstain": ("#5f6368", "Not interpreted")}

st.set_page_config(page_title="CarePath AI", page_icon="🩺", layout="centered")
st.markdown("""
<style>
html, body, [class*="css"] { font-size: 17px; }
.block-container { padding-top: 1.6rem; max-width: 820px; }
.cp-title { font-size: 1.9rem; font-weight: 700; margin-bottom: 0; }
.cp-sub { color: #5f6368; margin-top: .1rem; }
.cp-card { border: 1px solid rgba(128,128,128,.28); border-left: 6px solid var(--c); border-radius: 10px;
           padding: .9rem 1rem .7rem; margin: .7rem 0; }
.cp-card h4 { margin: 0 0 .15rem; font-size: 1.08rem; }
.cp-pill { display: inline-block; padding: .08rem .55rem; border-radius: 999px; font-size: .8rem; font-weight: 600;
           color: #fff; background: var(--c); margin-left: .4rem; vertical-align: middle; }
.cp-val { font-size: 1.35rem; font-weight: 700; }
.cp-ranges { display: flex; gap: .6rem; flex-wrap: wrap; margin: .45rem 0; }
.cp-range { border-radius: 8px; padding: .25rem .6rem; font-size: .88rem; background: rgba(128,128,128,.12); }
.cp-range b { font-weight: 600; }
.cp-unsure { background: rgba(66,133,244,.10); border-radius: 8px; padding: .5rem .7rem; font-size: .93rem; margin-top:.4rem; }
.cp-banner { border-radius: 10px; padding: .8rem 1rem; color: #fff; font-weight: 600; margin: .4rem 0 .6rem; }
.cp-chip { display: inline-block; border-radius: 999px; padding: .1rem .6rem; margin: .15rem .2rem 0 0;
           background: rgba(46,125,50,.14); font-size: .85rem; }
.cp-redacted { font-family: ui-monospace, Menlo, monospace; font-size: .85rem; white-space: pre-wrap;
               background: rgba(128,128,128,.10); border-radius: 8px; padding: .6rem .8rem; }
</style>
""", unsafe_allow_html=True)

ss = st.session_state
ss.setdefault("step", "consent"); ss.setdefault("history", []); ss.setdefault("nonce", 0)


def say(role, text): ss.history.append((role, text))


def go(step): ss.step = step; st.rerun()


def end_session():
    rep = P.delete_session(ss)
    ss.nonce += 1  # resets the file uploader so the browser-side copy is dropped too
    ss.history = [("assistant", "Your session has ended.")]
    ss.deletion = rep; ss.step = "deleted"


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown("### Your journey")
    order = [s for s, _ in STEPS]; cur = order.index(ss.step)
    for i, (k, label) in enumerate(STEPS):
        mark = "✅" if i < cur else ("➡️" if i == cur else "⬜")
        st.markdown(f"{mark} {label}")
    st.markdown("### Privacy status")
    if ss.step in ("consent", "upload"):
        st.caption("No report uploaded.")
    elif ss.step == "deleted":
        st.caption("All session data deleted and checked.")
    else:
        red = ss.get("redacted", {})
        st.caption(f"Original file: held in memory only, never saved. "
                   f"Personal details removed: {len(red.get('removed_categories', []))} types. "
                   "Nothing is sent to an outside AI service.")
    if ss.step not in ("consent", "deleted"):
        if st.button("End session and delete my data", type="secondary", width="stretch"):
            end_session(); st.rerun()
    st.markdown("---")
    st.caption("CarePath explains blood test results in plain English. It does not diagnose or prescribe. "
               "Hackathon prototype using synthetic reports only.")

# ---------------------------------------------------------------- header + history
st.markdown('<p class="cp-title">CarePath AI</p><p class="cp-sub">Understand your blood test, privately.</p>',
            unsafe_allow_html=True)
for role, text in ss.history:
    with st.chat_message(role): st.markdown(text)

# ---------------------------------------------------------------- steps
if ss.step == "consent":
    with st.chat_message("assistant"):
        st.markdown(
            "Hi, I'm CarePath. I can explain your blood test report in plain English.\n\n"
            "**Before we start, here's what happens to your data:**\n"
            "- I remove your name, NHS number, address and other personal details **before** anything else happens.\n"
            "- I'll show you the cleaned-up report so you can check it.\n"
            "- I explain results using trusted NHS information, and I tell you when I'm unsure.\n"
            "- When you finish, I delete your report and check that it's gone.\n\n"
            "I can't diagnose conditions or recommend medicines. For that, please speak to your GP or pharmacist.")
        ok = st.checkbox("I understand and want to continue")
        if st.button("Start", type="primary", disabled=not ok):
            say("assistant", "Thanks. Let's begin."); say("user", "I agree to continue.")
            go("upload")

elif ss.step == "upload":
    with st.chat_message("assistant"):
        st.markdown("Please upload your blood test report as a **PDF** or a **clear photo**.")
        up = st.file_uploader("Upload report", type=["pdf", "png", "jpg", "jpeg"], key=f"up_{ss.nonce}",
                              label_visibility="collapsed")
        st.caption("For the demo you can also use a synthetic sample report:")
        sample = st.selectbox("Synthetic sample", ["— choose a sample —"] + list(SAMPLES), label_visibility="collapsed")
        go_btn = st.button("Remove my personal details", type="primary",
                           disabled=(up is None and sample.startswith("—")))
        if go_btn:
            if up is not None: data, name = up.getvalue(), up.name
            else: name = SAMPLES[sample]; data = open(os.path.join(HERE, "samples", name), "rb").read()
            with st.status("Working on your report…", expanded=True) as s:
                st.write("Reading the report…")
                try:
                    ex = P.extract_report(data, name)
                except Exception as e:
                    s.update(label="I couldn't read that file", state="error"); st.error(str(e)); st.stop()
                del data  # drop the raw bytes as soon as text is extracted
                if ex["source"] == "ocr" and (ex["ocr_confidence"] < 0.6 or not ex["rows"]):
                    s.update(label="The photo isn't clear enough", state="error")
                    say("user", f"Uploaded {'a photo'}.")
                    say("assistant", f"I couldn't read the photo clearly enough (reading confidence "
                                     f"{ex['ocr_confidence']:.0%}). To avoid explaining the wrong numbers, I've stopped "
                                     "and discarded it. Please retake it flat, in good light, or upload the PDF.")
                    ss.nonce += 1; st.rerun()
                st.write("Removing personal details…")
                red = P.redact_report(ex)
                st.write("Checking nothing identifying is left…")
                if not red["safe"]:
                    s.update(label="Stopped to protect your privacy", state="error")
                    say("assistant", "I couldn't be sure all personal details were removed, so I've stopped and "
                                     "discarded the file. Nothing was explained or stored.")
                    ss.nonce += 1; st.rerun()
                s.update(label="Personal details removed", state="complete")
            ss.redacted = red
            ss.edited_rows = [dict(r) for r in red["rows"]]
            say("user", "I've uploaded my report." if up is not None else f"Using synthetic sample: {sample}")
            go("check")

elif ss.step == "check":
    red = ss.redacted
    with st.chat_message("assistant"):
        st.markdown("I've removed your personal details. **Please check this is correct before I explain anything.**")
        st.markdown("**Removed:** " + "".join(f'<span class="cp-chip">✓ {html.escape(c)}</span>'
                                              for c in red["removed_categories"]), unsafe_allow_html=True)
        st.markdown(f'<div class="cp-redacted">{html.escape(red["header_preview"])}</div>', unsafe_allow_html=True)
        if red["source"] == "ocr":
            st.info(f"This came from a photo (reading confidence {red['ocr_confidence']:.0%}). Please check each "
                    "number carefully against your paper copy.")
        st.markdown("**Your results as I read them.** If a number or unit is wrong, edit it in the table.")
        df = pd.DataFrame([{"Test": P.K.TESTS.get(r["analyte"], {}).get("name", r["label"]), "Result": r["value"],
                            "Unit": r["unit"], "Lab range": r["printed_range"], "Lab flag": r["lab_flag"]}
                           for r in ss.edited_rows])
        edited = st.data_editor(df, hide_index=True, width="stretch", disabled=["Test", "Lab flag"],
                                key="editor")
        missing = [r["Test"] for _, r in edited.iterrows() if not str(r["Unit"]).strip()]
        if missing:
            st.warning("No unit was read for: " + ", ".join(missing) + ". Add it from your report, or I'll skip it.")
        if red["comment"]:
            st.markdown("**Lab comment (personal details removed, shown as written; I won't follow instructions in it):**")
            st.text(red["comment"])
        c1, c2 = st.columns(2)
        if c1.button("Yes, this is correct", type="primary", width="stretch"):
            for row, (_, e) in zip(ss.edited_rows, edited.iterrows()):
                row["value"] = float(e["Result"]); row["unit"] = P._norm_unit(str(e["Unit"]))
                row["printed_range"] = str(e["Lab range"])
            ss.redacted["rows"] = ss.edited_rows
            say("assistant", "Personal details removed: " + ", ".join(red["removed_categories"]) + ".")
            say("user", "Yes, this is correct.")
            go("context")
        if c2.button("Something's wrong: delete it", width="stretch"):
            end_session(); st.rerun()

elif ss.step == "context":
    d = ss.redacted["derived"]
    with st.chat_message("assistant"):
        st.markdown(
            "**Optional:** some things change which 'normal' range is right for you. Standard ranges are based on "
            "large groups of people, and they don't fit everyone. Answer only if you want to. I keep this for this "
            "session only and delete it when you finish.")
        st.caption(f"From your report I'm only using: age band {d['age_band']}, sex as printed "
                   f"({'female' if d['sex'] == 'F' else 'male' if d['sex'] == 'M' else 'not stated'}).")
        preg = st.radio("Are you pregnant?", ["No", "Yes", "Prefer not to say"], horizontal=True)
        weeks = st.number_input("How many weeks?", 1, 42, 20) if preg == "Yes" else None
        horm = st.selectbox("Are you taking gender-affirming hormones?",
                            ["No", "Oestradiol (feminising)", "Testosterone (masculinising)", "Prefer not to say"])
        months = st.number_input("For how many months?", 0, 600, 12) if horm.startswith(("Oest", "Test")) else None
        duffy = st.selectbox("Has a doctor told you that you have the Duffy-null blood type?",
                             ["No / I don't know", "Yes"],
                             help="Some healthy people naturally have lower neutrophil counts. A blood test can show "
                                  "this. We never guess it from your name or background.")
        c1, c2 = st.columns(2)
        explain_now = c1.button("Explain my results", type="primary", width="stretch")
        skip = c2.button("Skip", width="stretch")
        if explain_now or skip:
            ctx = {}
            if explain_now:
                if preg == "Yes": ctx.update(pregnant=True, gestation_weeks=int(weeks))
                if horm.startswith("Oest"): ctx.update(hormones="oestradiol", hormone_months=int(months))
                if horm.startswith("Test"): ctx.update(hormones="testosterone", hormone_months=int(months))
                if duffy == "Yes": ctx["duffy_null"] = True
            ss.context = ctx
            ss.interp = P.interpret(ss.redacted, ctx); ss.cards = P.explain(ss.interp)
            ss.summary = P.gp_summary(ss.redacted, ss.interp, ss.cards, ctx)
            ss.chat = []
            say("user", "Here's some context about me." if ctx else "Skip the extra questions.")
            go("results")

elif ss.step == "results":
    it, cards = ss.interp, ss.cards
    kind, msg = P.next_step(it)
    colour = {"urgent": "#b3261e", "routine": "#8a5a00", "none": "#2e7d32", "abstain": "#5f6368"}[kind]
    with st.chat_message("assistant"):
        st.markdown(f'<div class="cp-banner" style="background:{colour}">{html.escape(msg)}</div>',
                    unsafe_allow_html=True)
        for n in it["notes"]: st.info(n)
        if it["scope"] != "under_18":
            checked = [c for c in cards if c["status"] in ("normal", "low", "high", "critical")]
            inr = sum(c["status"] == "normal" for c in checked)
            st.markdown(f"I checked **{len(checked)}** results: **{inr}** within range, "
                        f"**{len(checked) - inr}** outside it." + (" Some I couldn't check; I explain why below."
                                                                    if len(checked) < len(cards) else ""))
            order = {"critical": 0, "low": 1, "high": 1, "unchecked": 2, "abstain": 2, "normal": 3}

            def card(c):
                col, label = STATUS_STYLE[c["status"]]
                e = html.escape
                rng = f'<span class="cp-range"><b>Lab range:</b> {e(c["lab_range"] or "—")}</span>'
                if c["status"] not in ("unchecked", "abstain"):
                    rng += f'<span class="cp-range"><b>Range used for you:</b> {e(c["your_range"])}</span>'
                if c["alt_range"]:
                    rng += f'<span class="cp-range"><b>Other range:</b> {e(c["alt_range"])}</span>'
                body = (f'<div class="cp-card" style="--c:{col}"><h4>{e(c["title"])}'
                        f'<span class="cp-pill">{label}</span></h4><div class="cp-val">{e(c["value_line"])}</div>'
                        f'<div class="cp-ranges">{rng}</div><div>{e(c["headline"])}</div>'
                        f'<div style="margin-top:.35rem"><b>What it measures:</b> {e(c["what"])}</div>')
                if c["meaning"]: body += f'<div style="margin-top:.35rem"><b>What it can mean:</b> {e(c["meaning"])}</div>'
                if c["conversion"]: body += f'<div style="margin-top:.35rem">{e(c["conversion"])}</div>'
                if c["uncertainty"]: body += f'<div class="cp-unsure"><b>What I\'m not sure about:</b> {e(c["uncertainty"])}</div>'
                if c["sources"]:
                    body += '<div style="margin-top:.4rem;font-size:.88rem">Source: ' + " · ".join(
                        f'<a href="{e(s["url"])}" target="_blank">{e(s["title"])}</a>' for s in c["sources"]) + "</div>"
                st.markdown(body + "</div>", unsafe_allow_html=True)

            show = lambda c: c["status"] != "normal" or c["lab_flag"] or c["alt_range"]
            flagged = [c for c in sorted(cards, key=lambda c: order[c["status"]]) if show(c)]
            normal = [c for c in cards if not show(c)]
            for c in flagged: card(c)
            if normal:
                with st.expander(f"Results within range ({len(normal)})", expanded=not flagged):
                    for c in normal: card(c)
            st.markdown("**Questions you could ask your GP**\n" + "\n".join(f"- {q}" for q in P.gp_questions(cards)))
            st.download_button("Download summary for my GP (no personal details)", ss.summary,
                               file_name="carepath_summary.txt", width="stretch")
            st.caption("Explanations are written by the CarePath team from NHS information, with links so you can "
                       "check them. This is not medical advice.")
    for role, text in ss.chat:
        with st.chat_message(role): st.markdown(text)
    if it["scope"] != "under_18":
        sugg = ["What should I ask my GP?", "Why is my range different?"]
        first = next((c for c in cards if c["status"] in ("low", "high", "critical")), None)
        if first: sugg.insert(0, f"What does {first['title'].split(' (')[0]} mean?")
        cols = st.columns(len(sugg)); clicked = None
        for col, s_ in zip(cols, sugg):
            if col.button(s_, width="stretch"): clicked = s_
        q = st.chat_input("Ask about your results…") or clicked
        if q:
            ans, _ = P.answer_followup(q, cards)
            ss.chat += [("user", q), ("assistant", ans)]; st.rerun()
    if st.button("I'm finished: delete my data", type="primary"):
        end_session(); st.rerun()

elif ss.step == "deleted":
    rep = ss.get("deletion", {"all_deleted": False, "items": []})
    with st.chat_message("assistant"):
        if rep["all_deleted"]:
            st.success(f"Your data has been deleted and I've checked it's gone ({rep['time']}).")
        else:
            st.error("I couldn't confirm everything was deleted. Please close this browser tab. "
                     "The items marked ✗ below were not confirmed.")
        st.markdown("\n".join(f"- {'✓' if ok else '✗'} {name}" for name, ok in rep["items"]))
        st.caption("Your uploaded file was only ever held in memory, and nothing was written to logs.")
        if st.button("Start again", type="primary"):
            for k in ("deletion",): ss.pop(k, None)
            ss.history = []; go("consent")
