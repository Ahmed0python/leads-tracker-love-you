"""LeadFinder - run with:  streamlit run app.py"""
from datetime import datetime

import pandas as pd
import streamlit as st

from export_excel import COLUMNS, build_workbook
from leads_engine import INDUSTRIES, SIZE_TIERS, run_campaign

st.set_page_config(page_title="LeadFinder", page_icon="🎯", layout="wide")

st.markdown("""
<style>
.hero {padding: 1.6rem 1.8rem; border-radius: 16px; color: #fff; margin-bottom: 1rem;
       background: linear-gradient(135deg, #1F3864 0%, #4f46e5 100%);}
.hero h1 {margin: 0; font-size: 2rem; color: #fff;}
.hero p {margin: .3rem 0 0; opacity: .85;}
div[data-testid="stMetric"] {border: 1px solid rgba(128,128,128,.25); border-radius: 12px; padding: .8rem 1rem;}
.stButton > button, .stDownloadButton > button {border-radius: 10px; font-weight: 600; transition: transform .15s;}
.stButton > button:hover, .stDownloadButton > button:hover {transform: translateY(-2px);}
</style>
<div class="hero"><h1>🎯 LeadFinder</h1>
<p>Describe your campaign, get a scored, enriched lead list, and download it as Excel.
(Dark / light theme: ⋮ menu → Settings → Theme.)</p></div>
""", unsafe_allow_html=True)

RADIUS = {"Within 10 km": 10, "Within 25 km": 25, "Within 50 km": 50, "Within 100 km": 100,
          "Whole region / country": None}

# ---------- Step 1: the 7 inputs (+ business type, which the search needs) ----------
with st.container(border=True):
    st.subheader("1 · Campaign details")
    with st.form("campaign"):
        c1, c2 = st.columns(2)
        location = c1.text_input("Target location *", placeholder="e.g. Karachi, Pakistan")
        radius_label = c2.selectbox("Search radius *", list(RADIUS), index=1)
        c3, c4 = st.columns(2)
        company = c3.text_input("Your company name *")
        product = c4.text_input("Your primary product / service *")
        c5, c6 = st.columns(2)
        campaign = c5.radio("Campaign type", ["Appointment-based sales", "Direct sales (no appointment)"],
                            horizontal=True)
        persona = c6.text_input("Target buyer persona / decision maker", value="Owner, Founder, Manager")
        c7, c8, c9 = st.columns(3)
        size_label = c7.selectbox("Minimum company size", list(SIZE_TIERS))
        industry = c8.selectbox("Target business type", list(INDUSTRIES))
        limit = c9.slider("Max leads", 10, 100, 30, step=5)
        custom = st.text_input("Or type your own business type (overrides the list above)",
                               placeholder="e.g. chimney sweep, moving company, plumber — separate several with commas")
        go = st.form_submit_button("🔎 Find leads", type="primary", use_container_width=True)

# ---------- Step 2: run ----------
if go:
    missing = [n for n, v in [("location", location), ("company name", company), ("product / service", product)]
               if not v.strip()]
    if missing:
        st.error("Please fill in: " + ", ".join(missing))
    else:
        params = dict(location=location.strip(), radius_km=RADIUS[radius_label], company=company.strip(),
                      product=product.strip(), campaign=campaign, persona=persona.strip() or "Owner",
                      min_employees=SIZE_TIERS[size_label], industry=industry, limit=limit,
                      custom=custom.strip())
        bar = st.progress(0.0, text="Starting…")
        try:
            leads = run_campaign(params, lambda f, m: bar.progress(min(f, 1.0), text=m))
            st.session_state["leads"] = leads
            st.session_state["meta"] = dict(location=params["location"], range=radius_label, company=company,
                                            product=product, campaign=campaign, persona=params["persona"],
                                            min_size=size_label, industry=custom.strip() or industry)
            if not leads:
                st.warning("No businesses found. Try a bigger radius or a different business type.")
        except Exception as e:
            st.error(f"Something went wrong: {e}")
        finally:
            bar.empty()

# ---------- Step 3: results ----------
leads = st.session_state.get("leads")
if leads:
    df = pd.DataFrame(leads)[COLUMNS]
    with st.container(border=True):
        st.subheader("2 · Qualified leads")
        m = st.columns(4)
        m[0].metric("Total leads", len(df))
        m[1].metric("High priority", int((df["Priority"] == "High").sum()))
        m[2].metric("Avg match score", f"{df['Match Score'].mean():.0f}%")
        m[3].metric("With email", int((df["Email"] != "").sum()))

        f1, f2, f3 = st.columns([2, 2, 3])
        prios = f1.multiselect("Priority", ["High", "Medium", "Low"], default=["High", "Medium", "Low"])
        min_score = f2.slider("Min match score", 0, 100, 0)
        query = f3.text_input("Search table", placeholder="company, email, address…")
        view = df[df["Priority"].isin(prios) & (df["Match Score"] >= min_score)]
        if query:
            view = view[view.apply(lambda r: query.lower() in " ".join(map(str, r)).lower(), axis=1)]

        st.dataframe(
            view, use_container_width=True, hide_index=True, height=480,
            column_config={
                "Match Score": st.column_config.ProgressColumn("Match Score", format="%d%%", min_value=0, max_value=100),
                "Website": st.column_config.LinkColumn("Website"),
                "LinkedIn": st.column_config.LinkColumn("LinkedIn", display_text="Open"),
                "Pitch Hook": st.column_config.TextColumn("Pitch Hook", width="large"),
                "ICP Fit Notes": st.column_config.TextColumn("ICP Fit Notes", width="large"),
            })
        st.download_button(
            "⬇️ Download Excel (.xlsx)", data=build_workbook(leads, st.session_state["meta"]),
            file_name=f"leads_{datetime.now():%Y%m%d_%H%M}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary", use_container_width=True)
