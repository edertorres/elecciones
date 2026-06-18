
import os
import json
from core import RegistraduriaBot, load_env

def inspect_index():
    load_env()
    user = os.getenv("REG_USER")
    pwd = os.getenv("REG_PASS")
    
    if not user or not pwd:
        print("ERROR: No se encontraron credenciales en .env")
        return

    bot = RegistraduriaBot(user=user, password=pwd)
    
    # Intentar descubrir el boletín para CA
    base_etype = "CA"
    try:
        html = bot.download_text(f"{base_etype}/index.html")
        import re
        matches = re.findall(r'00\d\d', html)
        candidates = sorted(list(set(matches)), reverse=True)
        boletin = "0000"
        for cand in candidates:
            path = f"{base_etype}/{cand}/DE{base_etype}INDEX{cand}.json"
            try:
                bot.download_text(path)
                boletin = cand
                break
            except:
                continue
        
        print(f"Usando boletín: {boletin}")
        index_path = f"{base_etype}/{boletin}/DE{base_etype}INDEX{boletin}.json"
        index_content = bot.download_text(index_path)
        index_data = json.loads(index_content)

        print("Keys in index_data:")
        for key in sorted(index_data.keys()):
            print(f"  {key}")
        
        avance = index_data.get("Avance", {})
        print("\nKeys in Avance:")
        for key in sorted(avance.keys()):
            print(f"  {key}: {avance[key]}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    inspect_index()
