#!/usr/bin/env python3
"""Collecteur ligne J : trains Vernouillet-Verneuil -> Paris Saint-Lazare.

Interroge l'API PRIM d'Ile-de-France Mobilites (prochains passages, SIRI Lite)
et enregistre l'heure prevue et l'heure reelle, ainsi que les suppressions
annoncees en temps reel :
- le matin, trains Vernouillet-Verneuil -> Paris Saint-Lazare (dir "aller") ;
- le soir, trains Paris Saint-Lazare -> Vernouillet-Verneuil (dir "retour").

Un fichier par jour : data/AAAA-MM-JJ.json. Le lancer toutes les 5 minutes.
Variables d'environnement :
  PRIM_API_KEY   (obligatoire) cle API PRIM
  VERNOUILLET_REF, LAZARE_REF  (facultatif) MonitoringRef PRIM a forcer,
                 ex. STIF:StopArea:SP:12345:
  COLLECT_FROM, COLLECT_TO   matin : departs de Vernouillet suivis (05:30, 10:00)
  EVENING_ARR_FROM, EVENING_ARR_TO   soir : arrivees a Vernouillet suivies (15:45, 23:00)
Option --dry-run : affiche ce qui est recu sans rien ecrire.
"""
import json, os, re, sys, unicodedata, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
LINE_J = "STIF:Line::C01739:"
PRIM = "https://prim.iledefrance-mobilites.fr/marketplace"
ODS = ("https://data.iledefrance-mobilites.fr/api/explore/v2.1/catalog/datasets/"
       "arrets-lignes/records?where=" + urllib.parse.quote('id="IDFM:C01739"') + "&limit=100")
DATA = Path(__file__).resolve().parent / "data"
KEY = os.environ.get("PRIM_API_KEY", "").strip()
FROM = os.environ.get("COLLECT_FROM", "05:30")
TO = os.environ.get("COLLECT_TO", "10:00")
# Soir : trains venant de Paris qui arrivent a Vernouillet dans cette plage
EVE_ARR_FROM = os.environ.get("EVENING_ARR_FROM", "15:45")
EVE_ARR_TO = os.environ.get("EVENING_ARR_TO", "23:00")
DRY = "--dry-run" in sys.argv


def get_json(url, prim=False):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "collecteur-ligne-j"})
    if prim:
        req.add_header("apikey", KEY)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def val(x):
    """Les champs SIRI Lite sont tantot une chaine, tantot {"value": ...}, tantot une liste."""
    if isinstance(x, list):
        return val(x[0]) if x else None
    if isinstance(x, dict):
        return x.get("value")
    return x


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def to_refs(stop_id):
    """IDFM:monomodalStopPlace:N -> STIF:StopArea:SP:N: ; IDFM:N -> STIF:StopPoint:Q:N:"""
    m = re.search(r"(\d+)$", stop_id or "")
    if not m:
        return []
    n = m.group(1)
    if "monomodalStopPlace" in stop_id:
        return [f"STIF:StopArea:SP:{n}:", f"STIF:StopPoint:Q:{n}:"]
    return [f"STIF:StopPoint:Q:{n}:", f"STIF:StopArea:SP:{n}:"]


def visits(ref):
    url = f"{PRIM}/stop-monitoring?MonitoringRef={urllib.parse.quote(ref)}&LineRef={urllib.parse.quote(LINE_J)}"
    d = get_json(url, prim=True)
    out = []
    for dl in (d.get("Siri", {}).get("ServiceDelivery", {}).get("StopMonitoringDelivery") or []):
        out += dl.get("MonitoredStopVisit") or []
    return out


def resolve_stops():
    cache = DATA / "stops.json"
    stops = {}
    if cache.exists():
        stops = json.loads(cache.read_text())
    if os.environ.get("VERNOUILLET_REF"):
        stops["vernouillet"] = os.environ["VERNOUILLET_REF"]
    if os.environ.get("LAZARE_REF"):
        stops["lazare"] = os.environ["LAZARE_REF"]
    if stops.get("vernouillet") and stops.get("lazare"):
        return stops
    rows = get_json(ODS).get("results", [])
    want = {"vernouillet": "vernouillet", "lazare": "lazare"}
    for key, word in want.items():
        if stops.get(key):
            continue
        cands = []
        for r in rows:
            if word in norm(r.get("stop_name")):
                cands += to_refs(str(r.get("stop_id", "")))
        for ref in dict.fromkeys(cands):
            try:
                visits(ref)
                stops[key] = ref
                break
            except Exception as e:  # format refuse : essayer le suivant
                print(f"  {ref} refuse ({e})")
        if not stops.get(key):
            sys.exit(f"Arret introuvable pour {key}. Renseignez {key.upper()}_REF dans les secrets.")
    if not DRY:
        DATA.mkdir(exist_ok=True)
        cache.write_text(json.dumps(stops, indent=1))
    return stops


def parse_t(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(PARIS)
    except ValueError:
        return None


def hm(t):
    return t.strftime("%H:%M") if t else None


def mins(a, b):
    if not a or not b:
        return None
    return round((b - a).total_seconds() / 60)


def journey(v):
    mvj = v.get("MonitoredVehicleJourney") or {}
    call = mvj.get("MonitoredCall") or {}
    num = val((mvj.get("TrainNumbers") or {}).get("TrainNumberRef"))
    dvj = (mvj.get("FramedVehicleJourneyRef") or {}).get("DatedVehicleJourneyRef")
    return mvj, call, str(num or ""), str(val(dvj) or "")


def main():
    if not KEY:
        sys.exit("PRIM_API_KEY manquante.")
    now = datetime.now(PARIS)
    day = now.strftime("%Y-%m-%d")
    stops = resolve_stops()
    path = DATA / f"{day}.json"
    doc = json.loads(path.read_text()) if path.exists() else {"date": day, "trains": [], "messages": []}
    trains = {t["key"]: t for t in doc["trains"]}

    vern = visits(stops["vernouillet"])
    laz = visits(stops["lazare"])

    def sticky(t, status):
        """Une suppression reste acquise tant qu'aucun nouvel etat ne la dement."""
        return status == "cancelled" or (t.get("cancelled", False) and status in ("", "noreport"))

    # 1a. Matin : departs de Vernouillet-Verneuil vers Paris
    # 1b. Soir : arrivees a Vernouillet-Verneuil des trains venant de Paris
    for v in vern:
        mvj, call, num, dvj = journey(v)
        dest = val(mvj.get("DestinationName")) or val(call.get("DestinationDisplay")) or ""
        mission = val(mvj.get("JourneyNote")) or ""
        if "lazare" in norm(dest):
            aimed = parse_t(call.get("AimedDepartureTime"))
            if not aimed or aimed.strftime("%Y-%m-%d") != day or not (FROM <= hm(aimed) <= TO):
                continue
            exp = parse_t(call.get("ExpectedDepartureTime"))
            status = (call.get("DepartureStatus") or "").lower()
            key = num or dvj or f"{hm(aimed)}-{mission}"
            t = trains.setdefault(key, {"key": key, "first_seen": hm(now)})
            t.update({"dir": "aller", "num": num, "ref": dvj, "t": hm(aimed), "mission": mission,
                      "dep_exp": hm(exp), "dep_delay": mins(aimed, exp), "dep_lead": mins(now, exp or aimed),
                      "cancelled": sticky(t, status), "dep_status": status, "last_seen": hm(now)})
        else:
            aimed = parse_t(call.get("AimedArrivalTime")) or parse_t(call.get("AimedDepartureTime"))
            if not aimed or aimed.strftime("%Y-%m-%d") != day or not (EVE_ARR_FROM <= hm(aimed) <= EVE_ARR_TO):
                continue
            exp = parse_t(call.get("ExpectedArrivalTime")) or parse_t(call.get("ExpectedDepartureTime"))
            status = (call.get("ArrivalStatus") or call.get("DepartureStatus") or "").lower()
            key = "R" + (num or dvj or f"{hm(aimed)}-{mission}")
            t = trains.setdefault(key, {"key": key, "first_seen": hm(now)})
            t.update({"dir": "retour", "num": num, "ref": dvj, "mission": mission, "dest": dest[:40],
                      "arr_t": hm(aimed), "arr_exp": hm(exp), "arr_delay": mins(aimed, exp),
                      "arr_lead": mins(now, exp or aimed),
                      "arr_status": status, "cancelled": sticky(t, status), "last_seen": hm(now)})

    # 2. A Saint-Lazare : arrivee des trains du matin, depart des trains du soir
    aller = [t for t in trains.values() if t.get("dir", "aller") == "aller"]
    retour = [t for t in trains.values() if t.get("dir") == "retour"]
    idx = lambda lst: ({t["num"]: t for t in lst if t.get("num")}, {t["ref"]: t for t in lst if t.get("ref")})
    a_num, a_ref = idx(aller)
    r_num, r_ref = idx(retour)
    def quai(t, call, first, second):
        """Voie a Saint-Lazare : on garde la derniere voie annoncee."""
        q = val(call.get(first)) or val(call.get(second))
        if q:
            t["quai"] = str(q).strip()[:12]

    for v in laz:
        mvj, call, num, dvj = journey(v)
        t = a_num.get(num) or a_ref.get(dvj)
        if t:
            quai(t, call, "ArrivalPlatformName", "DeparturePlatformName")
            a_aim = parse_t(call.get("AimedArrivalTime"))
            a_exp = parse_t(call.get("ExpectedArrivalTime"))
            st = (call.get("ArrivalStatus") or "").lower()
            t.update({"arr_t": hm(a_aim), "arr_exp": hm(a_exp), "arr_delay": mins(a_aim, a_exp),
                      "arr_lead": mins(now, a_exp or a_aim), "arr_status": st, "arr_seen": hm(now)})
            if st == "cancelled":
                t["cancelled"] = True
            continue
        t = r_num.get(num) or r_ref.get(dvj)
        if t:
            quai(t, call, "DeparturePlatformName", "ArrivalPlatformName")
            d_aim = parse_t(call.get("AimedDepartureTime"))
            d_exp = parse_t(call.get("ExpectedDepartureTime"))
            st = (call.get("DepartureStatus") or "").lower()
            t.update({"t": hm(d_aim), "dep_exp": hm(d_exp), "dep_delay": mins(d_aim, d_exp),
                      "dep_lead": mins(now, d_exp or d_aim), "dep_status": st, "dep_seen": hm(now)})
            if st == "cancelled":
                t["cancelled"] = True

    # 3. Messages d'info trafic de la ligne J (motifs de suppression)
    try:
        g = get_json(f"{PRIM}/general-message?LineRef={urllib.parse.quote(LINE_J)}", prim=True)
        for dl in (g.get("Siri", {}).get("ServiceDelivery", {}).get("GeneralMessageDelivery") or []):
            for m in dl.get("InfoMessage") or []:
                content = m.get("Content") or {}
                txt = val((content.get("Message") or [{}])[0].get("MessageText") if content.get("Message") else None)
                if txt and txt not in doc["messages"]:
                    doc["messages"].append(txt[:500])
        doc["messages"] = doc["messages"][-30:]
    except Exception as e:
        print("info trafic indisponible :", e)

    doc["trains"] = sorted(trains.values(), key=lambda t: (t.get("dir", "aller"), t.get("t") or t.get("arr_t") or ""))
    doc["updated"] = now.isoformat(timespec="minutes")
    doc["stops"] = stops
    print(f"{day} {hm(now)} : {len(doc['trains'])} trains suivis")
    for t in doc["trains"]:
        print(f"  {t.get('dir','aller'):6} {t.get('t')} {t.get('mission',''):5} dep {t.get('dep_delay')} arr {t.get('arr_delay')}"
              f"{' SUPPRIME' if t.get('cancelled') else ''}")
    if not DRY:
        DATA.mkdir(exist_ok=True)
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
