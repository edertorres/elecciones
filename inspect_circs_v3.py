
import os
import json
from core import RegistraduriaBot, load_env

def check_se_ca_circs():
    load_env()
    bot = RegistraduriaBot(user=os.getenv("REG_USER"), password=os.getenv("REG_PASS"))
    
    # Check CA Risaralda (24)
    print("--- CA RISARALDA (BOL_CA_24_0000_3279.json.gz) ---")
    try:
        content = bot.download_gz("CA/0000/BOL_CA_24_0000_3279.json.gz")
        data = json.loads(content)
        circs = {c.get("Desc_Circunscripcion") for b in data["Boletin"] for c in b.get("Detalle_Circunscripcion", [])}
        for c in sorted(list(circs)): print(f"  {c}")
    except Exception as e: print(f"  Error: {e}")

    # Check SE Index 0000
    print("\n--- SE INDEX 0000 ---")
    try:
        index = json.loads(bot.download_text("SE/0000/DESEINDEX0000.json"))
        rel = index["Avance"]["URL_Json_COLOMBIA"]
        print(f"  SE Colombia file: {rel}")
        content = bot.download_gz(f"SE/0000/{rel.lstrip('./')}")
        data = json.loads(content)
        circs = {c.get("Desc_Circunscripcion") for b in data["Boletin"] for c in b.get("Detalle_Circunscripcion", [])}
        for c in sorted(list(circs)): print(f"  {c}")
    except Exception as e: print(f"  Error: {e}")

if __name__ == "__main__":
    check_se_ca_circs()
