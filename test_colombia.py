import sys, json, os, traceback
import requests
import gzip

def get_colombia():
    bot = requests.Session()
    bot.headers.update({"User-Agent": "Mozilla/5.0"})
    
    url_index = "https://resultados.registraduria.gov.co/elecciones/2022/presidencia/PR/042/DEPRINDEX042.json"
    res = bot.get(url_index)
    av = res.json().get("Avance", {})
    url_col = av.get("URL_Json_COLOMBIA")
    
    gz_url = f"https://resultados.registraduria.gov.co/elecciones/2022/presidencia/PR/042/{url_col.lstrip('./')}"
    resp = bot.get(gz_url)
    
    data = json.loads(gzip.decompress(resp.content).decode("utf-8"))
    boletines = data.get("Boletin", [])
    if not isinstance(boletines, list): boletines = [boletines]
    for b in boletines[:10]:
        print("Muni:", b.get("Municipio"), "Depto:", b.get("Desc_Departamento", "N/A"), "DescMuni:", b.get("Desc_Municipio", "N/A"))

if __name__ == "__main__":
    try:
        get_colombia()
    except Exception as e:
        traceback.print_exc()
