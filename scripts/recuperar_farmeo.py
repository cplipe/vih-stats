"""
Recupera (una sola vez) el farmeo de Sudamerica de los registros antiguos,
que se guardaron contando TODOS los servidores.

Cómo funciona:
  1. Busca en el historial de git la última versión de data/history.json
     anterior al cambio de filtro (sin la clave "gather_servers").
  2. Pide a la API, para cada jugador, el total de TODOS los servidores y el de
     Sudamerica. La diferencia es lo farmeado fuera de Sudamerica.
  3. Para cada registro antiguo: valor_sudamerica = valor_todos - diferencia.

Supone que entre esos registros y ahora los jugadores no farmearon en otros
servidores. Si alguno lo hizo, su valor recuperado tendrá un pequeño error.

Uso: python scripts/recuperar_farmeo.py   (se ejecuta desde el workflow "Recuperar farmeo")
"""
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import colector  # noqa: E402  (reutiliza la configuración y la descarga)

RAIZ = Path(__file__).resolve().parent.parent
RUTA_REL = "data/history.json"
CAMPOS_FARMEO = [f for f in colector.HIST_MEMBER if f.startswith(("gather_", "farming_"))]


def git(*args) -> str:
    return subprocess.run(["git", *args], cwd=RAIZ, check=True, capture_output=True, text=True).stdout


def historial_anterior() -> dict | None:
    """Última versión de history.json que todavía contaba todos los servidores."""
    for sha in git("log", "--format=%H", "--", RUTA_REL).split():
        try:
            data = json.loads(git("show", f"{sha}:{RUTA_REL}"))
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            continue
        if "gather_servers" not in data:
            return data
    return None


def resumen(steam_id: str, servidores: str) -> dict:
    url = colector.PLAYER_URL.format(steam_id=steam_id)
    if servidores:
        url += f"?servers={servidores}"
    s = (colector.pedir_json(url) or {}).get("summary") or {}
    return {k: colector.entero(s.get(k)) for k in CAMPOS_FARMEO}


def main() -> int:
    hist = colector.leer_json(colector.HISTORY, None)
    if not hist or hist.get("gather_servers") != colector.GATHER_SERVERS:
        print("El historial actual no usa el filtro de servidores nuevo; nada que recuperar.")
        return 0
    if hist.get("farmeo_recuperado"):
        print("La recuperación ya se hizo antes; no se repite.")
        return 0

    viejo = historial_anterior()
    if not viejo:
        print("No se encontró en git un historial anterior al cambio de filtro.")
        return 1
    campos_viejos = viejo.get("member_fields", [])
    pos_viejo = {f: i for i, f in enumerate(campos_viejos)}
    pos_nuevo = {f: i for i, f in enumerate(hist["member_fields"])}
    puntos_viejos = {p["t"]: p for p in viejo.get("points", [])}

    # Diferencia actual por jugador: todos los servidores - Sudamerica
    ids = sorted({sid for p in hist["points"] for sid in p.get("m", {})})
    diferencia = {}
    for i, sid in enumerate(ids):
        if i:
            time.sleep(0.5)
        try:
            todos = resumen(sid, "")
            sud = resumen(sid, colector.GATHER_SERVERS)
        except Exception as e:  # noqa: BLE001
            print(f"Aviso: no se pudo consultar {sid}: {e}", file=sys.stderr)
            continue
        diferencia[sid] = {k: (todos[k] - sud[k]) if None not in (todos[k], sud[k]) else None
                           for k in CAMPOS_FARMEO}

    recuperados = 0
    for p in hist["points"]:
        antiguo = puntos_viejos.get(p["t"])
        if not antiguo:
            continue
        for sid, vals in p.get("m", {}).items():
            viejos = antiguo.get("m", {}).get(sid)
            dif = diferencia.get(sid)
            if not viejos or not dif:
                continue
            for k in CAMPOS_FARMEO:
                iv, inu = pos_viejo.get(k), pos_nuevo[k]
                if iv is None or iv >= len(viejos) or viejos[iv] is None or dif[k] is None:
                    continue
                if inu < len(vals) and vals[inu] is not None:
                    continue  # no se pisan datos que ya son de Sudamerica
                valor = viejos[iv] - dif[k]
                if valor < 0:
                    continue
                while len(vals) <= inu:
                    vals.append(None)
                vals[inu] = valor
                recuperados += 1

    hist["farmeo_recuperado"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    colector.escribir_json(colector.HISTORY, hist, compacto=True)
    print(f"Listo: {recuperados} valores de farmeo recuperados en registros antiguos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
