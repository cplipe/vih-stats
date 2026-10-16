"""
Descarga las estadísticas públicas del clan desde la API de LatamGameServers
y las guarda en data/latest.json y data/history.json.

Uso local:  python scripts/colector.py
"""
import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

API_URL = "https://webstatsapi.latamgs.com/api/clans/vih"
PLAYER_URL = "https://webstatsapi.latamgs.com/api/player/{steam_id}"
# Servidores que cuentan para el farmeo. Vacío = todos los servidores (igual que las stats del clan).
# Ejemplo solo Sudamerica: GATHER_SERVERS = "sudamerica"
GATHER_SERVERS = ""
DATA = Path(__file__).resolve().parent.parent / "data"
LATEST = DATA / "latest.json"
HISTORY = DATA / "history.json"

HISTORY_STEP = timedelta(minutes=55)  # como máximo un punto de historial por hora
HISTORY_KEEP = timedelta(days=60)     # cuánto historial conservar

CLAN_FIELDS = ["id", "slug", "name", "tag", "logo_url", "member_count"]
CLAN_STATS = [
    "member_count", "active_members", "kills", "deaths", "kdr", "headshots",
    "playtime_seconds", "longest_kill", "avg_elo", "peak_elo",
    "current_kills", "current_deaths", "current_kdr",
    "current_playtime_seconds", "current_longest_kill",
]
MEMBER_STATS = [
    "kills", "deaths", "kdr", "headshots", "playtime_seconds", "longest_kill",
    "current_kills", "current_deaths", "current_kdr",
    "current_playtime_seconds", "elo", "elo_games",
]
# Farmeo: vienen en /api/player/{id} -> summary, como totales históricos
GATHER_STATS = [
    "gather_wood", "gather_stone", "gather_metal", "gather_sulfur", "gather_hqm",
    "gather_total", "farming_hemp", "farming_total", "berries_total",
]
# Campos por miembro que se guardan en el historial (compacto, en este orden).
# Solo se agregan campos al final para que el historial antiguo siga siendo válido.
HIST_MEMBER = ["elo", "kills", "deaths", "current_kills", "current_deaths", "current_playtime_seconds",
               "gather_wood", "gather_stone", "gather_metal", "gather_sulfur", "gather_hqm",
               "gather_total", "farming_total"]
HIST_CLAN = ["kills", "deaths", "current_kills", "current_deaths", "avg_elo", "current_playtime_seconds"]


def pedir_json(url: str):
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "VIH-dashboard/1.0 (uso personal; github actions)",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def entero(v):
    """La API entrega varios números como texto ("1449179")."""
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def descargar_farmeo(steam_id: str) -> dict:
    url = PLAYER_URL.format(steam_id=steam_id)
    if GATHER_SERVERS:
        url += f"?servers={GATHER_SERVERS}"
    summary = (pedir_json(url) or {}).get("summary") or {}
    return {k: entero(summary.get(k)) for k in GATHER_STATS}


def descargar() -> dict:
    data = pedir_json(API_URL)
    clan = data.get("clan")
    if not isinstance(clan, dict):
        raise ValueError(f"La API devolvió un formato inesperado (claves: {list(data)[:10]})")
    # "members" puede venir en el nivel principal o dentro de "clan"
    miembros = data.get("members")
    if not isinstance(miembros, list):
        miembros = clan.get("members")
    if not isinstance(miembros, list):
        raise ValueError(f"No se encontró la lista de miembros (claves de clan: {list(clan)[:30]})")
    data["members"] = miembros
    return data


def limpiar(data: dict, ahora: str) -> dict:
    """Se queda solo con los datos necesarios (sin contactos ni IDs de Discord)."""
    clan = data["clan"]
    stats = clan.get("stats") or {}
    miembros = []
    for m in data["members"]:
        st = m.get("stats") or {}
        miembros.append({
            "steam_id": m.get("steam_id"),
            "name": m.get("personaname") or st.get("personaname"),
            "avatar": m.get("avatar") or st.get("avatar"),
            "profile": m.get("steam_profile_url") or st.get("steam_profile_url"),
            "joined_at": m.get("joined_at"),
            **{k: st.get(k) for k in MEMBER_STATS},
        })
    return {
        "updated_at": ahora,
        "clan": {k: clan.get(k) for k in CLAN_FIELDS},
        "stats": {k: stats.get(k) for k in CLAN_STATS},
        "servers": (clan.get("server_activity") or {}).get("current_wipe", []),
        "members": miembros,
    }


def leer_json(path: Path, defecto):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return defecto


def escribir_json(path: Path, obj, compacto=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    texto = (json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
             if compacto else json.dumps(obj, ensure_ascii=False, indent=2))
    path.write_text(texto + "\n", encoding="utf-8")


def detectar_wipe(anterior: dict, nuevo: dict) -> bool:
    """
    Hay wipe si la mayoría de los jugadores que estaban en ambas consultas
    tiene menos horas de "wipe actual" que antes (los contadores volvieron a cero).
    """
    previos = {m.get("steam_id"): m for m in anterior.get("members", [])}
    comparables = bajaron = 0
    for m in nuevo["members"]:
        p = previos.get(m["steam_id"])
        if not p or p.get("current_playtime_seconds") is None or m.get("current_playtime_seconds") is None:
            continue
        comparables += 1
        if m["current_playtime_seconds"] < p["current_playtime_seconds"]:
            bajaron += 1
    return comparables >= 2 and bajaron > comparables / 2


def sin_fecha(obj: dict) -> dict:
    return {k: v for k, v in obj.items() if k != "updated_at"}


def main() -> int:
    ahora_dt = datetime.now(timezone.utc).replace(microsecond=0)
    ahora = ahora_dt.isoformat().replace("+00:00", "Z")

    try:
        nuevo = limpiar(descargar(), ahora)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR al consultar la API: {e}", file=sys.stderr)
        return 1

    # Farmeo: una consulta por miembro. Si una falla, se sigue con el resto.
    fallos = 0
    for i, m in enumerate(nuevo["members"]):
        if i:
            time.sleep(0.5)  # no saturar la API
        try:
            m.update(descargar_farmeo(m["steam_id"]))
        except Exception as e:  # noqa: BLE001
            fallos += 1
            m.update({k: None for k in GATHER_STATS})
            print(f"Aviso: sin farmeo para {m.get('name')}: {e}", file=sys.stderr)
    print(f"Farmeo: {len(nuevo['members']) - fallos}/{len(nuevo['members'])} jugadores")

    # latest.json: solo se reescribe si cambió algo (evita commits innecesarios)
    anterior = leer_json(LATEST, {})
    hubo_wipe = detectar_wipe(anterior, nuevo)
    if hubo_wipe:
        print("Wipe detectado")
    if sin_fecha(anterior) != sin_fecha(nuevo):
        escribir_json(LATEST, nuevo)
        print(f"latest.json actualizado ({len(nuevo['members'])} miembros)")
    else:
        print("latest.json sin cambios")

    # history.json: un punto por hora como máximo, últimos 60 días
    hist = leer_json(HISTORY, {"member_fields": HIST_MEMBER, "clan_fields": HIST_CLAN, "points": []})
    puntos = hist.get("points", [])
    wipes = hist.get("wipes", [])
    if hubo_wipe:
        wipes = (wipes + [ahora])[-20:]
    ultimo_t = None
    if puntos:
        ultimo_t = datetime.fromisoformat(puntos[-1]["t"].replace("Z", "+00:00"))
    # Tras un wipe se guarda un punto de inmediato: es la base del farmeo del nuevo wipe
    if hubo_wipe or ultimo_t is None or ahora_dt - ultimo_t >= HISTORY_STEP:
        puntos.append({
            "t": ahora,
            "c": [nuevo["stats"].get(k) for k in HIST_CLAN],
            "m": {m["steam_id"]: [m.get(k) for k in HIST_MEMBER] for m in nuevo["members"]},
        })
        limite = ahora_dt - HISTORY_KEEP
        puntos = [p for p in puntos
                  if datetime.fromisoformat(p["t"].replace("Z", "+00:00")) >= limite]
        escribir_json(HISTORY, {"member_fields": HIST_MEMBER, "clan_fields": HIST_CLAN,
                                "wipes": wipes, "points": puntos}, compacto=True)
        print(f"history.json: {len(puntos)} puntos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
