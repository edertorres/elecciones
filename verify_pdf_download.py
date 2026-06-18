
import os
from core import scrape_official_data, load_env

def verify_official_scrape_pdf():
    load_env()
    user = os.getenv("REG_USER")
    pwd = os.getenv("REG_PASS")
    
    if not user or not pwd:
        print("ERROR: No se encontraron credenciales en .env")
        return

    print("Iniciando scrape oficial para verificar descarga de PDF...")
    # Probar con Risaralda (2400) para Cámara (CA)
    result, error = scrape_official_data("CA", "2400", user=user, password=pwd)
    
    if error:
        print(f"Error en scrape: {error}")
    else:
        print("Scrape completado exitosamente.")
        
        # Verificar si la carpeta boletines_pdf existe y tiene archivos
        pdf_dir = "boletines_pdf"
        if os.path.exists(pdf_dir):
            files = os.listdir(pdf_dir)
            print(f"Archivos en {pdf_dir}: {files}")
            if any(f.endswith(".pdf") for f in files):
                print("¡Veredicto: ÉXITO! Se encontraron PDFs descargados.")
            else:
                print("Veredicto: FALLO. No se encontraron archivos PDF.")
        else:
            print(f"Veredicto: FALLO. La carpeta {pdf_dir} no fue creada.")

if __name__ == "__main__":
    verify_official_scrape_pdf()
