from core import RegistraduriaBot
import json
import gzip
import re
import urllib.request
import urllib.error

bot = RegistraduriaBot()
bot.login()

# Manual discover
try:
    index_html = bot.download_text("PR/index.html")
    m = re.search(r'data-boletin\s*=\s*"(\d+)"', index_html)
    boletin = m.group(1) if m else "0"
except Exception:
    boletin = "042" # fallback

bot.session.headers["Referer"] = f"{bot.base_url}/PR/index.html"
index_content = bot.download_text(f"PR/{boletin}/DEPRINDEX{boletin}.json")
index_data = json.loads(index_content)
avance = index_data.get("Avance", {})
colombia_url = avance.get("URL_Json_COLOMBIA")

gz_content = bot.download_gz(f"PR/{boletin}/{colombia_url.lstrip('./')}")
results = json.loads(gz_content)

boletines = results.get("Boletin", [])
if not isinstance(boletines, list): boletines = [boletines]
for b in boletines[:10]:
    print("Depto:", b.get("Departamento", b.get("Cod_Departamento")), "DeptoName:", b.get("Desc_Departamento"), "Muni:", b.get("Municipio"), "Result:", list(b.keys())[:5])
