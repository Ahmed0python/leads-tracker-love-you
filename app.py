"""LeadFinder - run with:  python -m streamlit run app.py"""
from datetime import datetime

import pandas as pd
import streamlit as st

from export_excel import COLUMNS, build_posts_workbook, build_workbook
from leads_engine import INDUSTRIES, SIZE_TIERS, run_campaign
from people_finder import POST_COLUMNS, find_posts

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
<p>Find businesses to partner with, or people who are asking for your service right now, and download the list as Excel.
(Dark / light theme: ⋮ menu → Settings → Theme.)</p></div>
""", unsafe_allow_html=True)

RADIUS = {"Within 10 km": 10, "Within 25 km": 25, "Within 50 km": 50, "Within 100 km": 100,
          "Whole region / country": None}
BIZ, HOME = "🏢 Businesses (partners / B2B)", "🏠 Home clients (people asking for help)"


def business_mode():
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
                                   placeholder="e.g. real estate agent, property management, plumber (separate with commas)")
            go = st.form_submit_button("🔎 Find leads", type="primary", use_container_width=True)

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


def home_mode():
    with st.container(border=True):
        st.subheader("1 · What do you offer, and where do people ask for it?")
        st.caption("Finds recent public Reddit posts from people looking for your service. "
                   "Works best when the app runs on your own computer; Reddit often blocks online hosting.")
        with st.form("home"):
            c1, c2 = st.columns(2)
            company = c1.text_input("Your company name *")
            service = c2.text_input("Your service *", placeholder="e.g. chimney cleaning, local moving")
            c3, c4 = st.columns(2)
            subs = c3.text_area("Communities to watch (one per line, optional)", height=130,
                                placeholder="r/moving\nr/jerseycity\n(leave empty to search all of Reddit)")
            kws = c4.text_area("Keywords people would use *", height=130,
                               placeholder="moving company recommendation\nneed movers\nchimney cleaning")
            days = st.slider("Only posts from the last … days", 1, 30, 2)
            go = st.form_submit_button("🔎 Find people asking for help", type="primary", use_container_width=True)

    if go:
        keywords = [k.strip() for k in kws.splitlines() if k.strip()]
        sub_list = [s for s in subs.splitlines() if s.strip()]
        if not (company.strip() and service.strip() and keywords):
            st.error("Please fill in: company name, service, and at least one keyword.")
        else:
            bar = st.progress(0.0, text="Starting…")
            try:
                posts, errors = find_posts(sub_list, keywords, days, company.strip(), service.strip(),
                                           lambda f, m: bar.progress(min(f, 1.0), text=m))
                st.session_state["posts"] = posts
                st.session_state["pmeta"] = dict(company=company, service=service, days=days,
                                                 communities=", ".join(sub_list) or "All of Reddit",
                                                 keywords=", ".join(keywords))
                for e in errors:
                    st.warning(e)
                if not posts and not errors:
                    st.info("No posts found in that time window. Try more keywords or more days.")
            finally:
                bar.empty()

    posts = st.session_state.get("posts")
    if posts:
        df = pd.DataFrame(posts)[POST_COLUMNS]
        with st.container(border=True):
            st.subheader("2 · People asking for help")
            m = st.columns(3)
            m[0].metric("Posts found", len(df))
            m[1].metric("Communities", df["Community"].nunique())
            m[2].metric("Newest post", df["Post Date"].iloc[0])
            st.dataframe(
                df, use_container_width=True, hide_index=True, height=480,
                column_config={
                    "Post URL": st.column_config.LinkColumn("Post URL", display_text="Open post"),
                    "Post Title": st.column_config.TextColumn("Post Title", width="large"),
                    "Snippet": st.column_config.TextColumn("Snippet", width="large"),
                    "Reply Starter": st.column_config.TextColumn("Reply Starter", width="large"),
                })
            st.caption("Reply helpfully on the post and follow each community's rules on self-promotion.")
            st.download_button(
                "⬇️ Download Excel (.xlsx)", data=build_posts_workbook(posts, st.session_state["pmeta"]),
                file_name=f"people_asking_{datetime.now():%Y%m%d_%H%M}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary", use_container_width=True)


mode = st.radio("What do you want to find?", [BIZ, HOME], horizontal=True)
business_mode() if mode == BIZ else home_mode()
