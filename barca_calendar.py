# -*- coding: utf-8 -*-
"""יוצר קובץ יומן (iCal) עם כל משחקי ברצלונה: לה ליגה, אלופות, גביע המלך וסופרקופה.
הנתונים מגיעים מה-API הציבורי של ESPN (בלי מפתח). הרצה:  python barca_calendar.py
"""
import json
import sys
import unicodedata
import urllib.request
from datetime import datetime, timedelta, timezone

from teams import COMPETITIONS, GENERIC_DESC, TEAMS

BARCA_ID = "83"  # מזהה ברצלונה ב-ESPN
OUT_FILE = "barca.ics"
URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/teams/" + BARCA_ID + "/schedule{q}"
MATCH_LENGTH = timedelta(hours=2)


def norm(name):
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    return " ".join(s.lower().replace(".", " ").split())


def lookup(name):
    key = norm(name)
    if key in TEAMS:
        return TEAMS[key]
    for k, v in TEAMS.items():  # התאמה חלקית, למשל "FC Porto" / "Porto"
        if k in key or key in k:
            return v
    return None


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "barca-calendar/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def score_of(c):
    s = c.get("score")
    if isinstance(s, dict):
        return s.get("displayValue")
    return s


def collect():
    events = {}
    for lg in COMPETITIONS:
        for q in ("?fixture=true", ""):  # משחקים עתידיים + תוצאות
            try:
                data = fetch(URL.format(lg=lg, q=q))
            except Exception as e:
                print(f"warn: {lg}{q}: {e}", file=sys.stderr)
                continue
            for ev in data.get("events", []):
                ev["_lg"] = lg
                events[ev["id"]] = ev
    return list(events.values())


def esc(t):
    return t.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line):
    """שבירת שורות ל-75 בתים בלי לחתוך תו עברי באמצע."""
    out, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > (75 if not out else 74):
            out.append(cur)
            cur = b""
        cur += b
    out.append(cur)
    return "\r\n ".join(x.decode("utf-8") for x in out)


def build_event(ev, now):
    comp = ev["competitions"][0]
    teams = comp.get("competitors", [])
    barca = next((t for t in teams if str(t.get("team", {}).get("id")) == BARCA_ID), None)
    opp = next((t for t in teams if t is not barca), None)
    if not barca or not opp:
        return None

    opp_en = opp["team"].get("displayName", "?")
    info = lookup(opp_en)
    opp_he = info[0] if info else opp_en
    about = info[1] if info else GENERIC_DESC.get(ev["_lg"], "")
    home = barca.get("homeAway") == "home"
    lg_he = COMPETITIONS[ev["_lg"]]

    title = f"⚽ ברצלונה נגד {opp_he} ({'בית' if home else 'חוץ'})"
    state = comp.get("status", {}).get("type", {}).get("state") or ev.get("status", {}).get("type", {}).get("state")
    if state == "post":
        bs, os_ = score_of(barca), score_of(opp)
        if bs is not None and os_ is not None:
            try:
                mark = "✅" if int(bs) > int(os_) else ("❌" if int(bs) < int(os_) else "🤝")
            except ValueError:
                mark = ""
            title += f" | {bs}:{os_} {mark}".rstrip()

    start = datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
    time_known = comp.get("timeValid", True)
    venue = comp.get("venue", {}) or {}
    place = venue.get("fullName", "")
    city = (venue.get("address") or {}).get("city", "")

    desc = [f"🏆 מסגרת: {lg_he}"]
    if place:
        desc.append(f"🏟️ מגרש: {place}" + (f", {city}" if city else ""))
    if about:
        desc.append(f"ℹ️ על היריבה: {about}")
    if not time_known:
        desc.append("🕒 שעת המשחק עדיין לא נקבעה – היומן יתעדכן אוטומטית כשתיקבע.")

    lines = ["BEGIN:VEVENT", f"UID:espn-{ev['id']}@barca-calendar",
             f"DTSTAMP:{now:%Y%m%dT%H%M%SZ}"]
    if time_known:
        end = start + MATCH_LENGTH
        lines += [f"DTSTART:{start:%Y%m%dT%H%M%SZ}", f"DTEND:{end:%Y%m%dT%H%M%SZ}"]
    else:  # שעה לא ידועה – אירוע של יום שלם (לפי שעון ישראל, משחקי ערב באירופה)
        d = (start + timedelta(hours=2)).date()
        lines += [f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{d + timedelta(days=1):%Y%m%d}"]
        title += " 🕒"
    lines += [f"SUMMARY:{esc(title)}", f"DESCRIPTION:{esc(chr(10).join(desc))}"]
    if place:
        lines.append(f"LOCATION:{esc(place + (', ' + city if city else ''))}")
    if state != "post":
        for trig, txt in (("-P1D", "מחר משחק של ברצלונה!"), ("-PT1H", "עוד שעה משחק של ברצלונה!")):
            if not time_known and trig == "-PT1H":
                continue
            lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{esc(txt)}",
                      f"TRIGGER:{trig}", "END:VALARM"]
    lines.append("END:VEVENT")
    return start, lines


def main():
    now = datetime.now(timezone.utc)
    events = collect()
    built = [b for b in (build_event(e, now) for e in events) if b]
    if not built:
        sys.exit("לא התקבלו משחקים מ-ESPN – לא דורסים את הקובץ הקיים.")
    built.sort(key=lambda x: x[0])

    cal = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Idan Diva//Barca Calendar//HE",
           "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
           "X-WR-CALNAME:⚽ משחקי ברצלונה",
           "X-WR-TIMEZONE:Asia/Jerusalem",
           "X-WR-CALDESC:" + esc("כל משחקי ברצלונה – לה ליגה, אלופות, גביע המלך וסופרקופה. נוצר ע״י עידן דיוה"),
           "REFRESH-INTERVAL;VALUE=DURATION:PT6H", "X-PUBLISHED-TTL:PT6H"]
    for _, lines in built:
        cal += lines
    cal.append("END:VCALENDAR")

    with open(OUT_FILE, "w", encoding="utf-8", newline="") as f:
        f.write("\r\n".join(fold(l) for l in cal) + "\r\n")
    print(f"נכתבו {len(built)} משחקים ל-{OUT_FILE}")


if __name__ == "__main__":
    main()
