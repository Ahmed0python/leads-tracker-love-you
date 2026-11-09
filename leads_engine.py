"""Lead discovery + enrichment using free sources only:
OpenStreetMap (Nominatim + Overpass) for businesses, then each company's own website
for emails / phones / LinkedIn / contact names. No API keys needed."""
import re
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from math import radians, sin, cos, asin, sqrt
from urllib.parse import urljoin, urlparse, quote_plus

import requests
from bs4 import BeautifulSoup

try:
    import dns.resolver  # dnspython (optional but recommended)
except ImportError:  # falls back to a plain DNS lookup
    dns = None

UA = {"User-Agent": "LeadFinderApp/1.0 (personal lead research tool)"}
OVERPASS = ["https://overpass-api.de/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter"]

# Target business types -> OpenStreetMap tag filters
INDUSTRIES = {
    "Restaurants & cafes": ['"amenity"~"restaurant|cafe|fast_food"'],
    "Retail shops": ['"shop"'],
    "Offices & companies": ['"office"'],
    "Hotels & lodging": ['"tourism"~"hotel|guest_house|hostel"'],
    "Clinics & health": ['"amenity"~"clinic|dentist|doctors|pharmacy"'],
    "Gyms & fitness": ['"leisure"~"fitness_centre|sports_centre"'],
    "Salons & beauty": ['"shop"~"hairdresser|beauty"'],
    "Auto & repair": ['"shop"~"car|car_repair|car_parts"'],
    "Education & training": ['"amenity"~"school|college|language_school|driving_school"'],
    "Crafts & trades": ['"craft"'],
}
SIZE_TIERS = {"Any size": 0, "10+ employees": 10, "50+ employees": 50, "250+ employees": 250}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
TITLES = (r"(?:Co-?Founder|Founder|Owner|CEO|CTO|CFO|COO|CMO|Managing Director|General Manager|"
          r"Director|Head of [A-Z][a-z]+|Manager|President|Partner|Principal)")
PERSON_RE = re.compile(r"([A-Z][a-z]+(?:[ ][A-Z]\.)?[ ][A-Z][a-z]+(?:-[A-Z][a-z]+)?)[ \t]*[,\-–—|:][ \t]*("
                       + TITLES + r"[A-Za-z &]{0,30})")
BAD_EMAIL = ("sentry", "wixpress", "example.", "@2x", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")


def _hav(lat1, lon1, lat2, lon2):
    a = sin(radians(lat2 - lat1) / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(radians(lon2 - lon1) / 2) ** 2
    return 6371 * 2 * asin(sqrt(a))


def geocode(place):
    r = requests.get("https://nominatim.openstreetmap.org/search", headers=UA, timeout=20,
                     params={"q": place, "format": "json", "limit": 1})
    r.raise_for_status()
    d = r.json()
    if not d:
        raise ValueError(f"Could not find the location '{place}'. Try 'City, Country'.")
    s, n, w, e = map(float, d[0]["boundingbox"])
    return float(d[0]["lat"]), float(d[0]["lon"]), (s, w, n, e)


def discover(lat, lon, bbox, radius_km, industry, limit):
    area = f"(around:{int(radius_km * 1000)},{lat},{lon})" if radius_km else "({},{},{},{})".format(*bbox)
    body = "".join(f"nwr[{f}][name]{area};" for f in INDUSTRIES[industry])
    query = f"[out:json][timeout:60];({body});out center tags {limit * 5};"
    data, last_err = None, None
    for url in OVERPASS:
        try:
            r = requests.post(url, data={"data": query}, headers=UA, timeout=90)
            r.raise_for_status()
            data = r.json()
            break
        except Exception as e:  # try the mirror
            last_err = e
    if data is None:
        raise RuntimeError(f"OpenStreetMap search failed ({last_err}). Try a smaller area.")
    seen, recs = set(), []
    for el in data.get("elements", []):
        t = el.get("tags", {})
        key = t["name"].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        elat = el.get("lat", el.get("center", {}).get("lat"))
        elon = el.get("lon", el.get("center", {}).get("lon"))
        addr = ", ".join(x for x in [(t.get("addr:housenumber", "") + " " + t.get("addr:street", "")).strip(),
                                     t.get("addr:city", ""), t.get("addr:postcode", "")] if x)
        emp = t.get("employees", "")
        recs.append({
            "name": t["name"].strip(),
            "website": t.get("website") or t.get("contact:website", ""),
            "phone": t.get("phone") or t.get("contact:phone", ""),
            "email": t.get("email") or t.get("contact:email", ""),
            "address": addr,
            "category": next((t[k] for k in ("shop", "amenity", "office", "craft", "tourism", "leisure") if k in t),
                             "business").replace("_", " "),
            "employees": int(emp) if emp.isdigit() else None,
            "dist": _hav(lat, lon, elat, elon) if elat is not None and elon is not None else None,
        })
    # businesses that already publish contact details are the best leads -> keep those first
    recs.sort(key=lambda r: -(bool(r["website"]) * 2 + bool(r["phone"]) + bool(r["email"])))
    return recs[:limit]


def _fetch(url):
    try:
        r = requests.get(url, headers=UA, timeout=8)
        if r.ok and "html" in r.headers.get("content-type", ""):
            return r.text
    except requests.RequestException:
        pass
    return ""


def enrich_site(site, persona):
    out = {"emails": [], "phones": [], "linkedin": "", "person": ""}
    if not site:
        return out
    if not site.startswith("http"):
        site = "http://" + site
    host = urlparse(site).netloc.replace("www.", "")
    people = []
    for path in ("", "/contact", "/contact-us", "/about", "/team"):
        html = _fetch(urljoin(site, path) if path else site)
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            h = a["href"]
            if h.startswith("mailto:"):
                out["emails"].append(h[7:].split("?")[0])
            elif h.startswith("tel:"):
                out["phones"].append(h[4:].strip())
            elif "linkedin.com/company" in h and not out["linkedin"]:
                out["linkedin"] = h.split("?")[0]
        text = soup.get_text("\n")
        out["emails"] += EMAIL_RE.findall(text)
        people += [(m.group(1), m.group(2).strip()) for m in PERSON_RE.finditer(text)]
    emails = [e.strip().lower() for e in out["emails"] if not any(b in e.lower() for b in BAD_EMAIL)]
    out["emails"] = sorted(dict.fromkeys(emails), key=lambda e: host not in e)  # same-domain first
    out["phones"] = list(dict.fromkeys(out["phones"]))
    words = [w for w in re.split(r"\W+", persona.lower()) if len(w) > 2]
    best = next((p for p in people if any(w in p[1].lower() for w in words)), people[0] if people else None)
    out["person"] = f"{best[0]} — {best[1]}" if best else ""
    out["person_matches"] = bool(best and any(w in best[1].lower() for w in words))
    return out


def check_email(addr):
    """Checks syntax + whether the domain can receive mail. It does NOT confirm the mailbox exists."""
    if not addr:
        return "Not found"
    if not EMAIL_RE.fullmatch(addr):
        return "Invalid format"
    domain = addr.split("@")[-1]
    try:
        if dns:
            dns.resolver.resolve(domain, "MX", lifetime=5)
            return "Domain OK (MX found)"
        socket.gethostbyname(domain)
        return "Domain exists"
    except Exception:
        return "Domain unreachable"


def _work(rec, persona):
    info = enrich_site(rec["website"], persona)
    email = rec["email"] or (info["emails"][0] if info["emails"] else "")
    return info, email, check_email(email)


def _build_lead(r, info, email, status, p):
    if r["employees"] is not None and r["employees"] < p["min_employees"]:
        return None  # known to be below the minimum size
    phone = r["phone"] or (info["phones"][0] if info["phones"] else "")
    site = r["website"]
    if site and not site.startswith("http"):
        site = "http://" + site
    score = 20  # industry match (search is filtered by the chosen business type)
    score += 15 if site else 0
    score += (20 if email else 0) + (5 if status.startswith("Domain OK") else 0)
    score += 10 if phone else 0
    score += (15 if info.get("person_matches") else 8) if info["person"] else 0
    score += 10 * max(0, 1 - r["dist"] / p["radius_km"]) if p["radius_km"] and r["dist"] is not None else 5
    if r["employees"] is not None and r["employees"] >= p["min_employees"]:
        score += 5
    score = int(min(100, round(score)))
    priority = "High" if score >= 75 else "Medium" if score >= 50 else "Low"

    notes = [f"{r['category'].title()} business"]
    if r["dist"] is not None:
        notes.append(f"~{r['dist']:.0f} km from search centre")
    notes.append("email + phone available" if email and phone else "email available" if email
                 else "phone available" if phone else "no direct contact found yet")
    notes.append(f"decision-maker found: {info['person']}" if info["person"] else "no named decision-maker found")
    notes.append(f"{r['employees']} employees" if r["employees"] else "size unknown")

    first = info["person"].split()[0] if info["person"] else ""
    how = (f"I'd love to book 15 minutes to see if it could help you." if p["campaign"].startswith("Appointment")
           else "you can get started right away, no meeting needed.")
    verb = "helps with" if p["campaign"].startswith("Appointment") else "offers"
    hook = (f"Hi{' ' + first if first else ''}, I came across {r['name']} while looking at "
            f"{r['category']} businesses near {p['location']}. {p['company']} {verb} {p['product']}; {how}")
    return {
        "Company Name": r["name"], "Contact Person": info["person"], "Email": email, "Email Status": status,
        "Phone": phone, "Website": site,
        "LinkedIn": info["linkedin"] or f"https://www.linkedin.com/search/results/companies/?keywords={quote_plus(r['name'])}",
        "Address": r["address"], "Match Score": score, "Priority": priority,
        "Lead Source": "OpenStreetMap" + (" + company website" if site else ""),
        "ICP Fit Notes": "; ".join(notes), "Pitch Hook": hook,
    }


def run_campaign(p, progress=lambda frac, msg: None):
    """p keys: location, radius_km (None = whole area), company, product, campaign, persona,
    min_employees, industry, limit. Returns a list of lead dicts sorted by match score."""
    progress(0.05, "Locating the area…")
    lat, lon, bbox = geocode(p["location"])
    progress(0.15, "Searching OpenStreetMap for businesses…")
    recs = discover(lat, lon, bbox, p["radius_km"], p["industry"], p["limit"])
    leads = []
    if not recs:
        return leads
    with ThreadPoolExecutor(8) as ex:
        futs = {ex.submit(_work, r, p["persona"]): r for r in recs}
        for i, f in enumerate(as_completed(futs), 1):
            r = futs[f]
            try:
                info, email, status = f.result()
            except Exception:
                info, email, status = {"emails": [], "phones": [], "linkedin": "", "person": ""}, "", "Not found"
            lead = _build_lead(r, info, email, status, p)
            if lead:
                leads.append(lead)
            progress(0.2 + 0.78 * i / len(recs), f"Enriched {i}/{len(recs)}: {r['name']}")
    leads.sort(key=lambda l: -l["Match Score"])
    progress(1.0, f"Done — {len(leads)} leads")
    return leads
