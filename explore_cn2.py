import json, os
from core import RegistraduriaBot, load_env

def run():
    load_env()
    bot = RegistraduriaBot(user=os.getenv('REG_USER'), password=os.getenv('REG_PASS'))
    try:
        gz = bot.download_gz('CN/0008/BOL_CN_24_0008_6257.json.gz')
        data = json.loads(gz)
        bols = data.get('Boletin', [])
        print('Total boletines (Ris CN):', len(bols))
        if not bols: return
        b0 = bols[0]
        print('Mun:', b0.get('Desc_Municipio'))
        circs = b0.get('Detalle_Circunscripcion', [])
        if not circs: return
        c0 = circs[0]
        print('Circ:', c0.get('Desc_Circunscripcion'))
        print('Partidos Totales:')
        for p in c0.get('Detalle_Partidos_Totales', []):
            print(' ', p)
        print('Partidos:')
        for p in c0.get('Detalle_Partido', []):
            print(' ', p)
        print('Candidatos (primeros 5):')
        for c in c0.get('Detalle_Candidato', [])[:5]:
            print(' ', c)
    except Exception as e:
        print("Error:", e)

if __name__ == '__main__':
    run()
