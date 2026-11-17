"""Finds recent public Reddit posts from people asking for a service (key-free RSS search)."""
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.parse import quote_plus

import requests

UA = {"User-Agent": "LeadFinderApp/1.0 (personal research tool)"}
NS = {"a": "http://www.w3.org/2005/Atom"}
POST_COLUMNS = ["Community", "Post Date", "Post Title", "Snippet", "Post URL", "Matched Keyword", "Reply Starter"]


def clean_sub(text):
    """'r/moving', 'https://reddit.com/r/moving/' or 'moving' -> 'moving'"""
    return text.strip().rstrip("/").split("/")[-1].strip()


def _feed_url(sub, keyword, days):
    t = "day" if days <= 1 else "week" if days <= 7 else "month"
    q = quote_plus(keyword)
    if sub:
        return f"https://www.reddit.com/r/{sub}/search.rss?q={q}&restrict_sr=on&sort=new&t={t}"
    return f"https://www.reddit.com/search.rss?q={q}&sort=new&t={t}"


def _parse(xml_bytes, cutoff):
    out = []
    for e in ET.fromstring(xml_bytes).findall("a:entry", NS):
        link_el = e.find("a:link", NS)
        cat = e.find("a:category", NS)
        updated = e.findtext("a:updated", "", NS).replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(updated)
        except ValueError:
            continue
        if dt < cutoff:
            continue
        text = unescape(re.sub(r"<[^>]+>", " ", e.findtext("a:content", "", NS)))
        text = re.sub(r"\s+", " ", text).strip()
        text = re.sub(r"\s*submitted by.*$", "", text)[:300]
        out.append({
            "Community": "r/" + cat.get("term") if cat is not None and cat.get("term") else "",
            "Post Date": dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "Post Title": unescape(e.findtext("a:title", "", NS)),
            "Snippet": text,
            "Post URL": link_el.get("href") if link_el is not None else "",
        })
    return out


def find_posts(subs, keywords, days, company, service, progress=lambda f, m: None):
    """Returns (posts, errors). subs may be empty = search all of Reddit."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    targets = [clean_sub(s) for s in subs if s.strip()] or [None]
    jobs = [(s, k) for s in targets for k in keywords]
    posts, seen, errors = [], set(), []
    for i, (sub, kw) in enumerate(jobs, 1):
        progress(i / len(jobs), f"Searching {'r/' + sub if sub else 'all Reddit'} for “{kw}” ({i}/{len(jobs)})")
        try:
            r = requests.get(_feed_url(sub, kw, days), headers=UA, timeout=15)
            if r.status_code == 429:
                errors.append("Reddit is rate-limiting requests (429). Wait a minute and try again.")
                time.sleep(5)
                continue
            if r.status_code in (403, 401):
                errors.append("Reddit refused the request (403). This happens on online hosting; run the app on your own computer.")
                continue
            r.raise_for_status()
            for p in _parse(r.content, cutoff):
                if p["Post URL"] in seen:
                    continue
                seen.add(p["Post URL"])
                p["Matched Keyword"] = kw
                p["Reply Starter"] = (f"Hi! Saw your post. I run {company} and we offer {service}. "
                                      "Happy to answer questions or give you a quote if that helps, no pressure.")
                posts.append(p)
        except Exception as e:
            errors.append(f"{kw}: {str(e)[:100]}")
        time.sleep(1.2)  # be polite to Reddit
    posts.sort(key=lambda p: p["Post Date"], reverse=True)
    return posts, list(dict.fromkeys(errors))
