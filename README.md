# Panel del clan VIH (Rust · LatamGameServers)

Página estática que muestra las estadísticas del clan VIH del servidor Sudamerica,
actualizada automáticamente cada ~15 minutos con GitHub Actions.

- `scripts/colector.py` — descarga `https://webstatsapi.latamgs.com/api/clans/vih` y guarda los datos.
- `data/latest.json` — última foto del clan y sus miembros.
- `data/history.json` — un punto por hora, últimos 60 días (para comparar contra hace 24 h).
- `.github/workflows/actualizar.yml` — ejecuta el colector cada 15 minutos.
- `index.html` — la página que publica GitHub Pages.

Para cambiar de clan, edita `API_URL` en `scripts/colector.py`.
