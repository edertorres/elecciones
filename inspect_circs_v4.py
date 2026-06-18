
import os
import json
from core import RegistraduriaBot, load_env

def check_more_circs():
    load_env()
    bot = RegistraduriaBot(user=os.getenv("REG_USER"), password=os.getenv("REG_PASS"))
    
    # Check Bogota (16)
    print("--- CA BOGOTA ---")
    try:
        content = bot.download_gz("CA/0000/BOL_CA_16_0000_3279.json.gz")
        data = json.loads(content)
        circs = {c.get("Desc_Circunscripcion") for b in data["Boletin"] for c in b.get("Detalle_Circunscripcion", [])}
        for c in sorted(list(circs)): print(f"  {c}")
    except Exception as e: print(f"  Error: {e}")

    # Check Antioquia (01)
    print("\n--- CA ANTIOQUIA ---")
    try:
        content = bot.download_gz("CA/0000/BOL_CA_01_0000_3279.json.gz")
        data = json.loads(content)
        circs = {c.get("Desc_Circunscripcion") for b in data["Boletin"] for c in b.get("Detalle_Circunscripcion", [])}
        for c in sorted(list(circs)): print(f"  {c}")
    except Exception as e: print(f"  Error: {e}")

if __name__ == "__main__":
    check_more_circs()
