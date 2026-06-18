import json
import requests
from requests.auth import HTTPBasicAuth
import pandas as pd
import os
import subprocess
import gzip
import zipfile
from io import BytesIO, StringIO
from datetime import datetime, timezone


def load_env():
    """Carga variables desde .env si existe."""
    if os.path.exists(".env"):
        with open(".env") as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.strip().split("=", 1)
                    os.environ[k] = v.strip('"').strip("'")


load_env()

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
PDF_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "boletines_pdf")


def _decode_election_text(raw: bytes) -> str:
    """Decodifica textos oficiales, prefiriendo UTF-8 y usando Latin-1 como respaldo."""
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]

    for encoding in ("utf-8", "latin-1"):
        try:
            return _clean_election_text(raw.decode(encoding))
        except UnicodeDecodeError:
            continue

    return _clean_election_text(raw.decode("utf-8", errors="replace"))


def _clean_election_text(value) -> str:
    """Corrige mojibake frecuente en textos oficiales ya mal codificados."""
    if value is None:
        return ""

    text = str(value).strip()
    if not text:
        return text

    markers = ("Ã", "Â", "â", "�")
    if not any(marker in text for marker in markers):
        return text

    def score(candidate: str) -> int:
        return sum(candidate.count(marker) for marker in markers) + (
            candidate.count("�") * 3
        )

    candidates = [text]
    for encoding in ("latin-1", "cp1252"):
        try:
            candidates.append(text.encode(encoding).decode("utf-8"))
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue

    return min(candidates, key=score)


def _clean_dataframe_text(df: pd.DataFrame) -> pd.DataFrame:
    """Limpia mojibake en columnas de texto sin alterar columnas numéricas."""
    for col in df.select_dtypes(include=["object", "string"]).columns:
        df[col] = df[col].map(
            lambda value: _clean_election_text(value)
            if isinstance(value, str)
            else value
        )
    return df


def _clean_stats_map_text(stats_map: dict) -> dict:
    """Limpia nombres usados como llaves en estadísticas cacheadas."""
    cleaned = {}
    for key, value in stats_map.items():
        clean_key = key if str(key).startswith("__") else _clean_election_text(key)
        if isinstance(value, dict):
            value = value.copy()
            if isinstance(value.get("by_circ"), dict):
                value["by_circ"] = {
                    _clean_election_text(circ): circ_stats
                    for circ, circ_stats in value["by_circ"].items()
                }
        cleaned[clean_key] = value
    return cleaned


# ---------------------------------------------------------------------------
# Utilidades HTTP
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Bot de Descarga (Portal de Medios)
# ---------------------------------------------------------------------------


class RegistraduriaBot:
    """Bot para descargar archivos desde descargas.registraduria.gov.co."""

    def __init__(
        self,
        base_url="https://descargas.registraduria.gov.co",
        user=None,
        password=None,
    ):
        self.user = user
        self.password = password
        self.base_url = base_url
        self.session = requests.Session()
        if user and password:
            self.session.auth = HTTPBasicAuth(user, password)
        # Headers capturados del navegador para evitar 403
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "es-ES,es;q=0.9",
                "Referer": f"{base_url}/genclaves/index.html",
                "Origin": base_url,
                "sec-ch-ua-platform": '"Linux"',
            }
        )

    def _get_url(self, path):
        return f"{self.base_url}/{path.lstrip('/')}"

    def download_gz(self, path):
        """Descarga un archivo .gz y retorna el contenido descomprimido."""
        url = self._get_url(path)
        print(f"DEBUG: Descargando GZ desde {url}")  # Loguear sin pass
        try:
            response = self.session.get(url, stream=True, timeout=10)
            print(f"DEBUG: Status Code: {response.status_code}")
            response.raise_for_status()

            # Detectar "shadow-ban"
            if response.content.startswith(b"iiiiii"):
                raise Exception(
                    "El servidor está devolviendo datos basura (bloqueo por sesiones concurrentes). Por favor, cierra sesión en el navegador y espera 10 minutos."
                )

            with gzip.GzipFile(fileobj=BytesIO(response.content)) as f:
                return f.read()
        except Exception as e:
            print(f"DEBUG: Error descargando {path}: {e}")
            raise

    def download_text(self, path):
        """Descarga un archivo de texto."""
        url = self._get_url(path)
        print(f"DEBUG: Descargando Texto desde {url}")
        try:
            response = self.session.get(url, timeout=10)
            print(f"DEBUG: Status Code: {response.status_code}")
            response.raise_for_status()
            text = _decode_election_text(response.content)

            # Detectar "shadow-ban" (200 OK pero con basura 'iiii')
            if text.startswith("iiiiii"):
                raise Exception(
                    "El servidor está devolviendo datos basura (posible bloqueo por exceso de peticiones o sesiones concurrentes). Por favor, cierra sesión en el navegador y espera 10 minutos."
                )

            return text
        except Exception as e:
            print(f"DEBUG: Error descargando {path}: {e}")
            raise

    def download_zip_text(self, path, filename_inside):
        """Descarga un ZIP y extrae el contenido de un archivo de texto interior."""
        url = self._get_url(path)
        print(f"DEBUG: Descargando ZIP desde {url}")
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            with zipfile.ZipFile(BytesIO(response.content)) as z:
                with z.open(filename_inside) as f:
                    return _decode_election_text(f.read())
        except Exception as e:
            print(f"DEBUG: Error procesando ZIP {path}: {e}")
            raise


# ---------------------------------------------------------------------------
# Parsers de Archivos Básicos (Ancho Fijo)
# ---------------------------------------------------------------------------


def parse_divipol(content):
    """
    Parsea el archivo DIVIPOL.TXT (Ancho Fijo).
    Estructura aproximada basade en muestras:
    - Dept Code: 0-2
    - Muni Code: 2-5
    - Zone: 5-7
    - Post: 7-9
    - Dept Name: 9-24
    - Muni Name: 24-54
    - Post Name: 54-104
    - Tables: 104-109... (Necesita refinamiento)
    """
    # Usando anchos estimados de la observación de la muestra
    # 01 001 01 01 ANTIOQUIA       MEDELLIN                      ...
    colspecs = [(0, 2), (2, 5), (5, 7), (7, 9), (9, 24), (24, 54), (54, 104)]
    names = [
        "cod_dept",
        "cod_muni",
        "zona",
        "puesto",
        "departamento",
        "municipio",
        "nombre_puesto",
    ]
    df = pd.read_fwf(StringIO(content), colspecs=colspecs, names=names, header=None)
    for col in ("departamento", "municipio", "nombre_puesto"):
        df[col] = df[col].map(_clean_election_text)
    return df


def parse_partidos(content):
    """Parsea PARTIDOS.TXT (Portal de Descargas, 5 dígitos para código)."""
    colspecs = [(0, 5), (5, 105)]
    names = ["cod_partido", "nombre_partido"]
    df = pd.read_fwf(
        StringIO(content), colspecs=colspecs, names=names, header=None, dtype=str
    )
    for col in df.columns:
        df[col] = df[col].str.strip()
    df["nombre_partido"] = df["nombre_partido"].map(_clean_election_text)
    return df


def parse_candidatos(content):
    """
    Parsea CANDIDATOS.TXT del Portal de Descargas (138 chars).
    Indices verificados:
    Corp(2) | Circ(3) | ?(6) | Party(5) | Cand(3) | Pref(1) | Nombre(50) | Apellido(50)
    """
    colspecs = [
        (0, 3),  # Corporación
        (3, 6),  # Circunscripción
        (11, 16),  # Código Partido (5 dígitos)
        (16, 19),  # Número Candidato (3 dígitos)
        (19, 20),  # Preferente (1)
        (20, 70),  # Nombre (Inicia en 20)
        (70, 120),  # Apellido
        (120, 135),  # Cédula
        (135, 136),  # Género
    ]
    names = [
        "corporacion",
        "circunscripcion",
        "cod_partido",
        "n_candidato",
        "preferente",
        "nombre",
        "apellido",
        "cedula",
        "genero",
    ]
    df = pd.read_fwf(
        StringIO(content), colspecs=colspecs, names=names, header=None, dtype=str
    )

    # Limpiar espacios
    for col in df.columns:
        df[col] = df[col].astype(str).str.strip()
        df[col] = df[col].replace("nan", "")
    for col in ("nombre", "apellido"):
        df[col] = df[col].map(_clean_election_text)

    return df


# ---------------------------------------------------------------------------
# Caché local
# ---------------------------------------------------------------------------


def _cache_paths(dept_code: str) -> tuple[str, str, str]:
    """Devuelve (ruta_df, ruta_stats, ruta_meta) para un departamento."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    prefix = os.path.join(CACHE_DIR, f"pr_{dept_code}")
    return f"{prefix}_data.json", f"{prefix}_stats.json", f"{prefix}_meta.json"


def save_cache(dept_code: str, df: pd.DataFrame, stats_map: dict) -> str:
    """Guarda datos y estadísticas en caché local para Presidencia. Retorna timestamp ISO."""
    df_path, stats_path, meta_path = _cache_paths(dept_code)
    now = datetime.now(timezone.utc).isoformat()
    df = _clean_dataframe_text(df.copy())
    stats_map = _clean_stats_map_text(stats_map)

    df.to_json(df_path, orient="records", force_ascii=False)
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats_map, f, ensure_ascii=False)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "election_type": "PR",
                "timestamp": now,
                "records": len(df),
                "municipios": sorted(df["Municipio"].unique().tolist())
                if not df.empty
                else [],
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    return now


def load_cache(dept_code: str):
    """Carga datos desde caché local.

    Retorna ((df, stats_map, meta), None) si existe, o (None, error_str) si no.
    """
    df_path, stats_path, meta_path = _cache_paths(dept_code)
    if not all(os.path.exists(p) for p in (df_path, stats_path, meta_path)):
        return None, f"No hay caché para Presidencia-{dept_code}"

    try:
        df = pd.read_json(df_path, orient="records")
        df = _clean_dataframe_text(df)
        if not df.empty:
            df = df.sort_values(
                by=["Municipio", "Partido_Votos", "Votos"],
                ascending=[True, False, False],
            )
        with open(stats_path, encoding="utf-8") as f:
            stats_map = _clean_stats_map_text(json.load(f))
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        return (df, stats_map, meta), None
    except Exception as e:
        return None, f"Error leyendo caché: {e}"


def get_cache_info(dept_code: str) -> dict | None:
    """Devuelve metadatos del caché (o None si no existe)."""
    _, _, meta_path = _cache_paths(dept_code)
    if not os.path.exists(meta_path):
        return None
    try:
        with open(meta_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def scrape_official_data(dept_code="2400", user=None, password=None, on_progress=None):
    """
    Descarga datos desde el portal oficial (descargas.registraduria.gov.co)
    siguiendo la estructura de boletines e índices. Adaptado para la Presidencia (PR).
    """
    election_type = "PR"
    bot = RegistraduriaBot(user=user, password=password)

    def _progress(step, current=0, total=0):
        if on_progress:
            on_progress(step, current, total)
        print(f"  [{current}/{total}] {step}")

    _progress("Autenticando y descargando archivos básicos…", 0, 1)

    try:
        # 0. Normalización de códigos (Registraduría usa pads variables: 3, 5, 8)
        def _discover_latest_boletin(base_etype):
            """Busca el número de boletín (avance) más reciente en el portal."""
            try:
                html = bot.download_text(f"{base_etype}/index.html")
                import re

                # Buscar patrones tipo 0000, 0001, etc.
                matches = re.findall(r"00\d\d", html)
                if not matches:
                    return "0000"
                # Tomar los únicos y ordenarlos de mayor a menor
                candidates = sorted(list(set(matches)), reverse=True)
                for cand in candidates:
                    # Verificar que el índice exista para este candidato
                    path = f"{base_etype}/{cand}/DE{base_etype}INDEX{cand}.json"
                    try:
                        bot.download_text(path)
                        return cand  # Encontramos el más alto funcional
                    except:
                        continue
                return "0000"
            except Exception as e:
                print(f"Error descubriendo boletín para {base_etype}: {e}")
                return "0000"

        _norm = lambda x: str(x).lstrip("0") or "0"

        # 1. Archivos básicos de candidatos y partidos (comunes)
        _progress("Cargando maestros de candidatos y partidos…")
        try:
            candidatos_txt = bot.download_zip_text(
                "genclaves/CANDIDATOS.zip", "CANDIDATOS.TXT"
            )
            partidos_txt = bot.download_zip_text(
                "genclaves/PARTIDOS.zip", "PARTIDOS.TXT"
            )

            df_partidos = parse_partidos(partidos_txt)
            party_map = {
                _norm(row["cod_partido"]): _clean_election_text(
                    row["nombre_partido"]
                )
                for _, row in df_partidos.iterrows()
            }

            # Procesar candidatos
            df_cands = parse_candidatos(candidatos_txt)
            cand_map = {}  # key: "{circ_code}-{p_code}-{c_code}"

            for _, row in df_cands.iterrows():
                corp = str(row["corporacion"]).strip()
                # Omitimos filtro estricto por ahora dado que asumimos que PR es el único
                circ_code = str(row["circunscripcion"]).strip()
                p_code = _norm(row["cod_partido"])
                c_code = _norm(row["n_candidato"])
                non_null_name = _clean_election_text(row["nombre"])
                non_null_last = _clean_election_text(row["apellido"])
                full_name = f"{non_null_name} {non_null_last}".strip()
                # Use strictly circ-qualified key to avoid cross-department collisions
                cand_map[f"{circ_code}-{p_code}-{c_code}"] = full_name

            def _dept_to_circ(dept_code_4):
                """Convert 4-digit dept code (e.g. '2400') to 3-digit circ code ('024')."""
                try:
                    return str(int(dept_code_4) // 100).zfill(3)
                except:
                    return "000"

            def _lookup_cand(circ_id, dept_circ_3, party, cand_num):
                """Look up candidate name following true CANDIDATOS.TXT struct for PR."""
                try:
                    cn = int(cand_num)
                except (ValueError, TypeError):
                    cn = -1

                if cn == 0:
                    return _clean_election_text(
                        party_map.get(party, f"Partido {party}")
                    )

                # Presidencia SIEMPRE usa la circunscripción 000 a nivel nacional en CANDIDATOS.txt
                lookup_circ = "000"
                lookup_cand = str(cand_num)

                key = f"{lookup_circ}-{party}-{lookup_cand}"
                return _clean_election_text(
                    cand_map.get(key, f"Candidato {cand_num}")
                )

            _progress("Archivos básicos cargados", 1, 1)

            # 2. Descubrir Boletín más reciente
            _progress("Buscando último avance generado…")
            boletin = _discover_latest_boletin(election_type)
            print(f"DEBUG: Usando boletín {boletin} para {election_type}")

            # Consultar Índice para encontrar el boletín actual
            bot.session.headers["Referer"] = (
                f"{bot.base_url}/{election_type}/index.html"
            )
            index_path = (
                f"{election_type}/{boletin}/DE{election_type}INDEX{boletin}.json"
            )
            index_content = bot.download_text(index_path)
            index_data = json.loads(index_content)

            avance = index_data.get("Avance", {})
        except Exception as e:
            _progress(f"Error cargando maestros o índice: {e}")
            return None, f"Fallo al iniciar el scraper oficial: {e}"

        if not avance:
            return None, f"No se encontró la sección 'Avance' en el índice {index_path}"

        # Mapeo robusto de departamentos (basado en las llaves del JSON oficial)
        dept_name_map = {
            "2400": "RISARALDA",
            "00": "COLOMBIA",
            "1100": "BOGOTA_D_C_",
            "11": "BOGOTA_D_C_",
            "0100": "ANTIOQUIA",
            "0300": "ATLANTICO",
            "0500": "BOLIVAR",
            "0700": "BOYACA",
            "0800": "CALDAS",
            "0900": "CAQUETA",
            "1000": "CAUCA",
            "1200": "CESAR",
            "1300": "CORDOBA",
            "1500": "CUNDINAMARCA",
            "1700": "CHOCO",
            "1900": "HUILA",
            "2000": "LA_GUAJIRA",
            "2100": "MAGDALENA",
            "2200": "META",
            "2300": "NARIÑO",
            "2500": "NORTE_DE_SAN",
            "2600": "QUINDIO",
            "2700": "SANTANDER",
            "2800": "SUCRE",
            "2900": "TOLIMA",
            "3100": "VALLE",
            "4000": "ARAUCA",
            "4400": "CASANARE",
            "4800": "PUTUMAYO",
            "5200": "AMAZONAS",
            "5600": "GUAINIA",
            "6000": "GUAVIARE",
            "6400": "VAUPES",
            "6800": "VICHADA",
            "8800": "CONSULADOS",
        }

        all_data = []
        stats_map = {}

        # -- Helper: procesar un boletín individual -------------------------
        def _process_boletin(b, muni_name, t_code):
            """Extrae stats y candidatos de un boletín y agrega a all_data/stats_map."""

            def _to_int(val):
                try:
                    return int(str(val).replace(".", "").replace(",", ""))
                except:
                    return 0

            muni_name = _clean_election_text(muni_name)

            if muni_name not in stats_map:
                stats_map[muni_name] = {
                    "votantes": _to_int(b.get("Total_Sufragantes", 0)),
                    "pvotantes": f"{b.get('Porc_Sufragantes', 0)}%",
                    "no_marcados": _to_int(b.get("Votos_No_Marcados", 0)),
                    "pno_marcados": f"{b.get('Porc_Votos_No_Marcados', 0)}%",
                    "nulos": _to_int(b.get("Votos_Nulos", 0)),
                    "pnulos": f"{b.get('Porc_Votos_Nulos', 0)}%",
                    "blancos": _to_int(b.get("Votos_Blanco", 0)),
                    "pblancos": f"{b.get('Porc_Votos_Blanco', 0)}%",
                    "validos": _to_int(b.get("Votos_Validos", 0)),
                    "pvalidos": f"{b.get('Porc_Votos_Validos', 0)}%",
                    "mesas_info": f"{b.get('Mesas_Informadas', 0)} de {b.get('Mesas_Instaladas', 0)}",
                    "pmesas": f"{b.get('Porc_Mesas_Informadas', 0)}%",
                }

            circs = b.get("Detalle_Circunscripcion", [])
            if not circs:
                circs = [b]

            for circ in circs:
                circ_desc = _clean_election_text(
                    circ.get("Desc_Circunscripcion", "PRESIDENCIA")
                ).upper()

                c_stats = {}
                for ct in circ.get("Detalle_Partidos_Totales", []):
                    cp_code = ct.get("Partido")
                    try:
                        v_raw = int(
                            str(ct.get("Votos", 0)).replace(".", "").replace(",", "")
                        )
                    except:
                        v_raw = 0
                    p_raw = f"{ct.get('Porc', '0')}%"
                    if cp_code == "00996":
                        c_stats["blancos"] = v_raw
                        c_stats["pblancos"] = p_raw
                    elif cp_code == "00998":
                        c_stats["votantes"] = v_raw
                        c_stats["pvotantes"] = p_raw
                    elif cp_code == "00997":
                        c_stats["nulos"] = v_raw
                        c_stats["pnulos"] = p_raw
                    elif cp_code == "00994":
                        c_stats["no_marcados"] = v_raw
                        c_stats["pno_marcados"] = p_raw

                p_items = circ.get("Detalle_Partido", [])
                v_partidos = 0
                party_votes_info = {}
                for p in p_items:
                    v_p = int(str(p.get("Votos", 0)).replace(".", "").replace(",", ""))
                    v_partidos += v_p
                    cp = _norm(p.get("Partido", ""))
                    party_votes_info[cp] = {"v": v_p, "p": f"{p.get('Porc_Votos', 0)}%"}

                v_bla = c_stats.get("blancos", 0)
                c_stats["validos"] = v_partidos + v_bla

                v_vot = c_stats.get("votantes", 0)
                if v_vot > 0:
                    c_stats["pvalidos"] = f"{(c_stats['validos'] / v_vot * 100):.2f}%"
                    c_stats["pblancos"] = f"{(c_stats['blancos'] / v_vot * 100):.2f}%"
                    c_stats["pnulos"] = (
                        f"{(c_stats.get('nulos', 0) / v_vot * 100):.2f}%"
                    )
                    c_stats["pno_marcados"] = (
                        f"{(c_stats.get('no_marcados', 0) / v_vot * 100):.2f}%"
                    )
                else:
                    for ct in circ.get("Detalle_Partidos_Totales", []):
                        code = ct.get("Partido")
                        p = f"{ct.get('Porc', '0')}%"
                        if code == "00999":
                            c_stats["pvalidos"] = p
                        elif code == "00996":
                            c_stats["pblancos"] = p
                        elif code == "00997":
                            c_stats["pnulos"] = p
                        elif code == "00994":
                            c_stats["pno_marcados"] = p

                if c_stats:
                    if "by_circ" not in stats_map[muni_name]:
                        stats_map[muni_name]["by_circ"] = {}
                    stats_map[muni_name]["by_circ"][circ_desc] = c_stats

                current_circ = _dept_to_circ(
                    t_code if len(t_code) > 2 else t_code.zfill(4)
                )
                circ_id = circ.get("ID_Circunscripcion", "1")

                c_items = circ.get("Detalle_Candidato", [])
                for c in c_items:
                    cp = _norm(c.get("Partido", ""))
                    cc = _norm(c.get("Candidato", ""))
                    p_info = party_votes_info.get(cp, {"v": 0, "p": "0%"})
                    p_name = _clean_election_text(party_map.get(cp, f"Partido {cp}"))
                    cand_full_name = _lookup_cand(circ_id, current_circ, cp, cc)
                    all_data.append(
                        {
                            "Municipio": muni_name,
                            "Circunscripcion": circ_desc,
                            "Partido": p_name,
                            "Partido_Votos": p_info["v"],
                            "Partido_P": p_info["p"],
                            "Candidato": cand_full_name,
                            "Votos": int(c.get("Votos", 0)),
                            "P": f"{c.get('Porc_Votos', 0)}%",
                        }
                    )

                seen_parties = {_norm(c.get("Partido", "")) for c in c_items}
                for cp, info in party_votes_info.items():
                    if cp not in seen_parties and info["v"] > 0:
                        all_data.append(
                            {
                                "Municipio": muni_name,
                                "Circunscripcion": circ_desc,
                                "Partido": _clean_election_text(
                                    party_map.get(cp, f"Partido {cp}")
                                ),
                                "Partido_Votos": info["v"],
                                "Partido_P": info["p"],
                                "Candidato": "Votos por Partido",
                                "Votos": info["v"],
                                "P": info["p"],
                            }
                        )

        # -- Fin helper _process_boletin ------------------------------------

        # -----------------------------------------------------------------
        # Modo Nacional: un solo archivo DE con 34 boletines departamentales
        # -----------------------------------------------------------------
        if dept_code == "00":
            rel_gz_path = avance.get("URL_Json_DEPARTAMENTOS")
            if not rel_gz_path:
                return None, "No se encontró URL_Json_DEPARTAMENTOS en el índice"
            _progress("Descargando consolidado departamental…", 1, 1)
            try:
                gz_path = f"{election_type}/{boletin}/{rel_gz_path.lstrip('./')}"
                gz_content = bot.download_gz(gz_path)
                results_de = json.loads(gz_content)
                boletines_de = results_de.get("Boletin", [])
                if not isinstance(boletines_de, list):
                    boletines_de = (
                        [boletines_de] if isinstance(boletines_de, dict) else []
                    )
                total_targets = len(boletines_de)
                for idx_b, b in enumerate(boletines_de):
                    dept_name = _clean_election_text(b.get("Desc_Departamento", ""))
                    if not dept_name:
                        continue
                    _progress(f"Procesando {dept_name}…", idx_b + 1, total_targets)
                    t_code = str(b.get("Departamento", "00")).zfill(4)
                    _process_boletin(b, dept_name, t_code)
            except Exception as e:
                return None, f"Error descargando archivo departamental: {e}"

        # -----------------------------------------------------------------
        # Modo Departamental: archivo individual del departamento
        # -----------------------------------------------------------------
        else:
            target_name = dept_name_map.get(
                dept_code[: 4 if len(dept_code) > 2 else 2], "COLOMBIA"
            )
            json_url_key = f"URL_Json_{target_name}"
            rel_gz_path = avance.get(json_url_key)
            if not rel_gz_path:
                return None, f"No se encontró {json_url_key} en el índice"

            _progress(f"Descargando {target_name}…", 1, 1)
            try:
                gz_path = f"{election_type}/{boletin}/{rel_gz_path.lstrip('./')}"
                gz_content = bot.download_gz(gz_path)
                results = json.loads(gz_content)

                # Descargar PDF asociado
                try:
                    pdf_rel_path = rel_gz_path.replace(".json.gz", ".pdf")
                    pdf_path_remote = (
                        f"{election_type}/{boletin}/{pdf_rel_path.lstrip('./')}"
                    )
                    pdf_url = bot._get_url(pdf_path_remote)
                    pdf_response = bot.session.get(pdf_url, timeout=15)
                    if pdf_response.status_code == 200:
                        os.makedirs(PDF_DIR, exist_ok=True)
                        b_num = avance.get("Numero", "000")
                        local_pdf_name = (
                            f"boletin_{election_type}_{dept_code}_{b_num}.pdf"
                        )
                        local_pdf_path = os.path.join(PDF_DIR, local_pdf_name)
                        with open(local_pdf_path, "wb") as f:
                            f.write(pdf_response.content)
                        print(f"DEBUG: PDF guardado en {local_pdf_path}")
                except Exception as pdf_e:
                    print(
                        f"DEBUG: No se pudo descargar el PDF para {target_name}: {pdf_e}"
                    )

                boletines = results.get("Boletin", [])
                if not isinstance(boletines, list):
                    boletines = [boletines] if isinstance(boletines, dict) else []

                total_targets = len(boletines)
                for idx_b, b in enumerate(boletines):
                    bmuni = b.get("Municipio")
                    if bmuni == "000":
                        muni_name = "** CONSOLIDADO **"
                    else:
                        muni_name = _clean_election_text(
                            b.get("Desc_Municipio", "DEPARTAMENTO")
                        )
                    t_code = str(b.get("Departamento", dept_code)).zfill(4)
                    _process_boletin(b, muni_name, t_code)

            except Exception as inner_e:
                print(f"Error procesando {target_name}: {inner_e}")

        _progress("Procesando resultados consolidados…", total_targets, total_targets)
        df = pd.DataFrame(all_data)
        df = _clean_dataframe_text(df)
        if not df.empty:
            # ── AGREGAR "Todo el Ámbito" a stats_map ──
            # Sumar contadores de todos los municipios (excluyendo __REPORTE__)
            raw_keys = [k for k in stats_map.keys() if k != "__REPORTE__"]
            if len(raw_keys) > 0:
                total_v = sum(stats_map[k].get("votantes", 0) for k in raw_keys)
                total_nom = sum(stats_map[k].get("no_marcados", 0) for k in raw_keys)
                total_nul = sum(stats_map[k].get("nulos", 0) for k in raw_keys)
                total_bla = sum(stats_map[k].get("blancos", 0) for k in raw_keys)
                total_val = sum(stats_map[k].get("validos", 0) for k in raw_keys)

                # Mesas: Parsear "X de Y"
                total_mi = 0
                total_mt = 0
                for k in raw_keys:
                    mi, mt = 0, 0
                    info = stats_map[k].get("mesas_info", "0 de 0")
                    if " de " in info:
                        parts = info.split(" de ")
                        try:
                            mi = int(parts[0].replace(".", "").replace(",", ""))
                            mt = int(parts[1].replace(".", "").replace(",", ""))
                        except:
                            pass
                    total_mi += mi
                    total_mt += mt

                pmesas = f"{(total_mi / total_mt * 100):.2f}%" if total_mt > 0 else "0%"

                stats_map["Todo el Ámbito"] = {
                    "votantes": total_v,
                    "pvotantes": "---",  # Difícil de calcular sin el censo total aquí
                    "no_marcados": total_nom,
                    "nulos": total_nul,
                    "blancos": total_bla,
                    "validos": total_val,
                    "mesas_info": f"{total_mi} de {total_mt}",
                    "pmesas": pmesas,
                    "by_circ": {},
                }

                # Consolidar by_circ para "Todo el Ámbito"
                for k in raw_keys:
                    muni_by_circ = stats_map[k].get("by_circ", {})
                    for circ_name, c_st in muni_by_circ.items():
                        if circ_name not in stats_map["Todo el Ámbito"]["by_circ"]:
                            stats_map["Todo el Ámbito"]["by_circ"][circ_name] = {
                                "validos": 0,
                                "blancos": 0,
                                "votantes": 0,
                                "nulos": 0,
                                "no_marcados": 0,
                                "pvalidos": "0%",
                                "pblancos": "0%",
                                "pnulos": "0%",
                                "pno_marcados": "0%",
                                "pvotantes": "0%",
                            }
                        cs = stats_map["Todo el Ámbito"]["by_circ"][circ_name]
                        cs["validos"] += c_st.get("validos", 0)
                        cs["blancos"] += c_st.get("blancos", 0)
                        cs["votantes"] += c_st.get("votantes", 0)
                        cs["nulos"] += c_st.get("nulos", 0)
                        cs["no_marcados"] += c_st.get("no_marcados", 0)

                # Calcular porcentajes para cada circunscripción en "Todo el Ámbito"
                for circ_name, cs in stats_map["Todo el Ámbito"]["by_circ"].items():
                    cvot = cs["votantes"]
                    if cvot > 0:
                        cs["pvalidos"] = f"{(cs['validos'] / cvot * 100):.2f}%"
                        cs["pblancos"] = f"{(cs['blancos'] / cvot * 100):.2f}%"
                        cs["pnulos"] = f"{(cs['nulos'] / cvot * 100):.2f}%"
                        cs["pno_marcados"] = f"{(cs['no_marcados'] / cvot * 100):.2f}%"
                    else:
                        # Fallback a total_v si no hay votantes específicos
                        if total_v > 0:
                            cs["pvalidos"] = f"{(cs['validos'] / total_v * 100):.2f}%"
                            cs["pblancos"] = f"{(cs['blancos'] / total_v * 100):.2f}%"

                # Calcular porcentajes globales básicos
                total_emitidos = total_v
                if total_emitidos > 0:
                    stats_map["Todo el Ámbito"]["pno_marcados"] = (
                        f"{(total_nom / total_emitidos * 100):.2f}%"
                    )
                    stats_map["Todo el Ámbito"]["pnulos"] = (
                        f"{(total_nul / total_emitidos * 100):.2f}%"
                    )
                    stats_map["Todo el Ámbito"]["pblancos"] = (
                        f"{(total_bla / total_emitidos * 100):.2f}%"
                    )
                    stats_map["Todo el Ámbito"]["pvalidos"] = (
                        f"{(total_val / total_emitidos * 100):.2f}%"
                    )

            # Agrupar / Consolidar (incluyendo Circunscripcion)
            df = (
                df.groupby(["Municipio", "Circunscripcion", "Partido", "Candidato"])
                .agg(
                    {
                        "Votos": "sum",
                        "Partido_Votos": "max",
                        "Partido_P": "first",
                        "P": "first",
                    }
                )
                .reset_index()
            )

            # Capturar metadatos del boletín
            if all_data:
                stats_map["__REPORTE__"] = {
                    "boletin": avance.get("Numero", "000"),
                    "hora": avance.get("Hora", "---"),
                    "tipo": "Oficial",
                }

            df = df.sort_values(by=["Municipio", "Votos"], ascending=[True, False])
            save_cache(dept_code, df, stats_map)
            return (df, stats_map), None
        else:
            return (
                None,
                "No se encontraron datos de votación en el archivo oficial (Boletines vacíos).",
            )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return None, f"Error en portal oficial: {e}"


# ---------------------------------------------------------------------------
# Cifra repartidora (método D'Hondt)
# ---------------------------------------------------------------------------


def cifra_repartidora(
    party_votes: dict[str, int], n_seats: int, threshold_pct: float = 0.0
):
    """Calcula la cifra repartidora (D'Hondt) para asignar curules.

    Args:
        party_votes: {nombre_partido: total_votos}
        n_seats: número de curules a repartir
        threshold_pct: umbral mínimo como porcentaje (0-100).
                       Para Cámara Colombia ≈ 50% del cociente electoral.

    Returns:
        dict con:
          - "cifra": valor de la cifra repartidora
          - "assignments": {partido: n_curules}
          - "quotients": lista de (cociente, partido, divisor) ordenada desc
          - "threshold": valor del umbral en votos
          - "excluded": lista de partidos que no superan el umbral
          - "total_valid": total de votos válidos considerados
    """
    total_valid = sum(party_votes.values())

    # Calcular umbral
    if threshold_pct > 0 and n_seats > 0:
        cociente_electoral = total_valid / n_seats
        threshold_votes = cociente_electoral * (threshold_pct / 100.0)
    else:
        threshold_votes = 0

    # Filtrar partidos que superan el umbral
    eligible = {p: v for p, v in party_votes.items() if v >= threshold_votes}
    excluded = [p for p in party_votes if p not in eligible]

    if not eligible or n_seats <= 0:
        return {
            "cifra": 0,
            "assignments": {p: 0 for p in party_votes},
            "quotients": [],
            "threshold": threshold_votes,
            "excluded": excluded,
            "total_valid": total_valid,
        }

    # Generar tabla de cocientes: votos / 1, 2, 3, ..., n_seats
    quotients = []
    for party, votes in eligible.items():
        for divisor in range(1, n_seats + 1):
            quotients.append((votes / divisor, party, divisor))

    # Ordenar descendente
    quotients.sort(key=lambda x: -x[0])

    # La cifra repartidora es el cociente en la posición n_seats
    cifra = quotients[n_seats - 1][0] if len(quotients) >= n_seats else 0

    # Asignar curules: votos / cifra (parte entera)
    assignments = {}
    for party in party_votes:
        if party in eligible and cifra > 0:
            assignments[party] = int(party_votes[party] / cifra)
        else:
            assignments[party] = 0

    return {
        "cifra": cifra,
        "assignments": assignments,
        "quotients": quotients[: n_seats * 2],  # top cocientes para visualización
        "threshold": threshold_votes,
        "excluded": excluded,
        "total_valid": total_valid,
    }


def compute_curules_from_df(
    df: pd.DataFrame, n_seats: int = 5, threshold_pct: float = 50.0
):
    """Calcula la cifra repartidora a partir de un DataFrame de resultados.

    Agrega votos por partido a nivel departamental y aplica el cálculo.
    threshold_pct: para Cámara Colombia, 50% del cociente electoral.

    Returns:
        Resultado de cifra_repartidora() enriquecido con colores de partido.
    """
    # Sumar votos por partido a nivel departamental (evitar doble conteo)
    party_totals = (
        df.groupby("Partido")
        .agg({"Partido_Votos": "first", "Municipio": "count"})
        .reset_index()
    )
    # Los Partido_Votos ya están por municipio, necesitamos sumar por municipio
    party_by_muni = df.drop_duplicates(subset=["Municipio", "Partido"])[
        ["Municipio", "Partido", "Partido_Votos"]
    ]
    dept_totals = party_by_muni.groupby("Partido")["Partido_Votos"].sum().to_dict()

    result = cifra_repartidora(dept_totals, n_seats, threshold_pct)

    # Agregar colores
    color_idx = 0
    result["colors"] = {}
    for party in sorted(dept_totals.keys(), key=lambda p: -dept_totals[p]):
        result["colors"][party] = _get_party_color(party, color_idx)
        color_idx += 1

    result["party_votes"] = dept_totals
    return result


def _escape_typst(s: str) -> str:
    """Escapa caracteres especiales de Typst en strings de datos."""
    return (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("#", "\\#")
        .replace("<", "\\<")
        .replace(">", "\\>")
        .replace("@", "\\@")
    )


def generate_typst_pro(
    df,
    title,
    filename,
    stats=None,
    etype_label="",
    exclude_zero_votes=False,
    top_n=None,
    circ_sel=None,
    is_national=False,
    row_radius=2,
    row_inset_y=4,
    page_width=8.5,
):
    """Genera un .typ multipágina. Una página por municipio.
    Si es NACIONAL, compila los departamentos fluidamente sin saltos de página excesivos, empezando con COLOMBIA.
    """
    if exclude_zero_votes:
        df = df[df["Votos"] > 0].copy()
    if top_n is not None:
        top_n = int(top_n)
        parts = []
        for _, grp in df.groupby("Municipio", sort=False):
            parts.append(grp.nlargest(top_n, "Votos"))
        df = pd.concat(parts, ignore_index=True)

    # Ordenar directo por votos globalmente por municipio
    df = df.sort_values(by=["Municipio", "Votos"], ascending=[True, False])

    # ── Preámbulo ──
    L = []
    L.append("#let pure_black = cmyk(0%, 0%, 0%, 100%)")
    L.append("")
    L.append("#set text(")
    L.append('  font: ("PT Sans", "Roboto"),')
    L.append("  size: 9.0pt,")
    L.append("  fill: pure_black,")
    L.append("  fallback: true,")
    L.append("  stretch: 75%,")
    L.append('  features: ("tnum",)')
    L.append(")")
    L.append("#set par(leading: 0.42em)")
    L.append("")
    L.append("// Tabla de candidatos Zebra, UNA COLUMNA")
    L.append(f"#let _crow(c) = grid(")
    L.append("  columns: (1fr, 45pt, 35pt),")
    L.append(f"  inset: (y: 4pt, x: 3pt),")
    L.append(
        '  [#c.at(0)], [#align(right)[#text(weight: "bold")[#c.at(1)]]], [#align(right)[#c.at(2)]]'
    )
    L.append(")")
    L.append("")
    L.append("#let candidate_table(candidatos) = block(")
    L.append("  width: 100%,")
    L.append("  radius: 3pt,")
    L.append("  clip: true,")
    L.append("  breakable: true,")
    L.append(")[")
    L.append("  #set block(spacing: 0pt)")
    L.append("  #grid(")
    L.append("    columns: (1fr, 45pt, 35pt),")
    L.append(f"    inset: (y: 0.5pt, x: 3pt),")
    L.append("    [], [#align(right)[*VOTOS*]], [#align(right)[*%*]],")
    L.append("  )")
    L.append("  #for (i, c) in candidatos.enumerate() {")
    L.append("    if calc.odd(i) {")
    L.append(
        f"      block(width: 100%, fill: luma(255), radius: {row_radius}pt, clip: true, inset: 0pt)["
    )
    L.append("        #_crow(c)")
    L.append("      ]")
    L.append("    } else {")
    L.append("      _crow(c)")
    L.append("    }")
    L.append("  }")
    L.append("]")
    L.append("")

    muni_groups = list(df.groupby("Municipio", sort=False))

    # Si es Nacional, priorizamos imprimir "COLOMBIA" como total nacional primero
    if is_national:
        col_idx = next(
            (i for i, (m, g) in enumerate(muni_groups) if m.upper() == "COLOMBIA"), -1
        )
        if col_idx != -1:
            col_group = muni_groups.pop(col_idx)
            muni_groups.insert(0, col_group)

    for idx, (muni, group) in enumerate(muni_groups):
        if is_national and muni.upper() == "COLOMBIA":
            page_title = "TOTAL NACIONAL"
        else:
            page_title = f"{muni}".strip().upper().replace("*", "")

        cand_entries = []
        for _, row in group.iterrows():
            c_name = _escape_typst(row["Candidato"].upper())
            c_votes = f"{row['Votos']:,}".replace(",", ".")
            c_perc = row["P"]
            cand_entries.append(f'  ("{c_name}", "{c_votes}", "{c_perc}")')

        cands_str = ",\n".join(cand_entries)

        # ── Página (tamaño original) ──
        L.append(f"#page(width: {page_width}cm, height: auto, margin: 0cm)[")
        L.append("#block(width: 100%, stroke: 0.5pt + pure_black, inset: 0pt)[")

        # 1. Encabezado con fondo más oscuro
        L.append("  #block(fill: luma(185), width: 100%, inset: 6pt)[")
        L.append(f'    #text(size: 11pt, weight: "bold")[{page_title}]')
        L.append("  ]")
        L.append("")

        # 2. Tabla zebra de candidatos
        L.append("  #pad(x: 8pt, top: -2pt, bottom: 4pt)[")
        L.append(f"    #candidate_table((\n{cands_str}\n    ))")
        L.append("  ]")

        # 3. Pie de resumen (stats)
        if stats and muni in stats:
            s = stats[muni]
            v_val = s.get("validos", 0)
            v_bla = s.get("blancos", 0)
            v_tot = s.get("votantes", 0)
            v_nom = s.get("no_marcados", 0)
            v_nul = s.get("nulos", 0)
            p_val = s.get("pvalidos", "")
            p_bla = s.get("pblancos", "")
            p_tot = s.get("pvotantes", "")
            p_nom = s.get("pno_marcados", "")
            p_nul = s.get("pnulos", "")

            if circ_sel and circ_sel != "** TODAS LAS CIRCUNSCRIPCIONES **":
                by_circ = s.get("by_circ", {})
                if circ_sel in by_circ:
                    cs = by_circ[circ_sel]
                    v_val = cs.get("validos", v_val)
                    v_bla = cs.get("blancos", v_bla)
                    v_tot = cs.get("votantes", v_tot)
                    v_nom = cs.get("no_marcados", v_nom)
                    v_nul = cs.get("nulos", v_nul)
                    p_val = cs.get("pvalidos", p_val)
                    p_bla = cs.get("pblancos", p_bla)
                    p_tot = cs.get("pvotantes", p_tot)
                    p_nom = cs.get("pno_marcados", p_nom)
                    p_nul = cs.get("pnulos", p_nul)

            def fmt(val):
                if val is None:
                    return ""
                try:
                    n = int(str(val).replace(".", "").replace(",", ""))
                    return f"{n:,}".replace(",", ".")
                except:
                    return str(val)

            L.append("")
            L.append("  #pad(x: 10pt, top: -10pt, bottom: 8pt)[")
            L.append("    #block(")
            L.append("      fill: luma(252),")
            L.append("      radius: 4pt,")
            L.append("      inset: 5pt,")
            L.append("      stroke: 0.25pt + luma(120),")
            L.append("      width: 100%,")
            L.append("    )[")
            if page_width <= 9.5:
                L.append("      #set text(size: 6.2pt)")
                L.append("      #grid(")
                L.append("        columns: (auto, auto, 1fr, auto, auto),")
                L.append("        column-gutter: 4pt,")
                L.append("        row-gutter: 2.2pt,")
                L.append("        inset: 1pt,")
                p_tot_str = f" ({p_tot})" if p_tot else ""
                p_mesas = s.get('pmesas', '')
                p_mesas_str = f" ({p_mesas})" if p_mesas else ""
                L.append(
                    f"        [VOTANTES], [#align(right)[*{fmt(v_tot)}*#text(size: 5.4pt)[{p_tot_str}]]], [], [MESAS INF.], [#align(right)[*{s.get('mesas_info')}*#text(size: 5.4pt)[{p_mesas_str}]]],"
                )
                p_val_str = f" ({p_val})" if p_val else ""
                p_bla_str = f" ({p_bla})" if p_bla else ""
                L.append(
                    f"        [VÁLIDOS], [#align(right)[*{fmt(v_val)}*#text(size: 5.4pt)[{p_val_str}]]], [], [EN BLANCO], [#align(right)[*{fmt(v_bla)}*#text(size: 5.4pt)[{p_bla_str}]]],"
                )
                p_nom_str = f" ({p_nom})" if p_nom else ""
                p_nul_str = f" ({p_nul})" if p_nul else ""
                L.append(
                    f"        [NO MARC.], [#align(right)[*{fmt(v_nom)}*#text(size: 5.4pt)[{p_nom_str}]]], [], [NULOS], [#align(right)[*{fmt(v_nul)}*#text(size: 5.4pt)[{p_nul_str}]]],"
                )
                L.append("      )")
            else:
                L.append("      #grid(")
                L.append("        columns: (auto, auto, auto, 1fr, auto, auto, auto),")
                L.append("        column-gutter: 15pt,")
                L.append("        row-gutter: 2.2pt,")
                L.append("        inset: 1pt,")
                L.append(
                    f"        [VOTANTES], [#align(right)[*{fmt(v_tot)}*]], [#align(right)[{p_tot}]], [],"
                )
                L.append(
                    f"        [MESAS INFORMADAS], [#grid.cell(colspan: 2)[#align(right)[*{s.get('mesas_info')}* ({s.get('pmesas')})]]],"
                )
                L.append(
                    f"        [NO MARCADOS], [#align(right)[*{fmt(v_nom)}*]], [#align(right)[{p_nom}]], [],"
                )
                L.append(
                    f"        [NULOS], [#align(right)[*{fmt(v_nul)}*]], [#align(right)[{p_nul}]],"
                )
                L.append(
                    f"        [VÁLIDOS], [#align(right)[*{fmt(v_val)}*]], [#align(right)[{p_val}]], [],"
                )
                L.append(
                    f"        [EN BLANCO], [#align(right)[*{fmt(v_bla)}*]], [#align(right)[{p_bla}]],"
                )
                L.append("      )")
            L.append("    ]")
            L.append("  ]")

        L.append("]")  # fin block
        L.append("]")  # fin page
        L.append("")

    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    return filename


def generate_typst_national_dept_table(
    df,
    filename,
    stats=None,
    top_n=None,
    exclude_zero_votes=False,
    row_radius=2,
    row_inset_y=4,
    page_width=8.5,
    circ_sel=None,
    etype_label="",
    row_label="DEPARTAMENTO",
):
    """Genera un .typ con cuadro: filas = row_label (DEPARTAMENTO o MUNICIPIO), columnas = candidatos.
    Título: RESULTADO NACIONAL POR {row_label}S.
    """
    if exclude_zero_votes:
        df = df[df["Votos"] > 0].copy()

    if (
        circ_sel
        and circ_sel != "** TODAS LAS CIRCUNSCRIPCIONES **"
        and "Circunscripcion" in df.columns
    ):
        df = df[df["Circunscripcion"] == circ_sel].copy()

    # Aggregate by (Municipio, Candidato) summing votes across circunscripciones
    df_agg = df.groupby(["Municipio", "Candidato"], as_index=False)["Votos"].sum()

    # Per-department total votes
    dept_totals = df_agg.groupby("Municipio")["Votos"].sum().to_dict()

    # Determine top N candidates nationally
    cand_national = (
        df_agg.groupby("Candidato")["Votos"].sum().sort_values(ascending=False)
    )
    if top_n is not None:
        top_n = int(top_n)
        cand_national = cand_national.head(top_n)
    top_candidates = cand_national.index.tolist()
    if not top_candidates:
        return filename

    # Build dept -> candidate matrix
    dept_data = {}
    for dept in sorted(df_agg["Municipio"].unique()):
        dept_df = df_agg[df_agg["Municipio"] == dept]
        dept_total = dept_totals.get(dept, 0)
        cand_map = {}
        for _, row in dept_df.iterrows():
            v = int(row["Votos"])
            pct = f"{(v / dept_total * 100):.2f}%" if dept_total > 0 else "0.00%"
            cand_map[row["Candidato"]] = (v, pct)
        dept_data[dept] = {"cands": cand_map, "total": dept_total}

    # Sort: COLOMBIA first, rest alphabetical
    departments = [d for d in dept_data if d.upper() == "COLOMBIA"] + sorted(
        d for d in dept_data if d.upper() != "COLOMBIA"
    )

    # Column widths & auto page width
    cand_vw = 38  # pt for votes (wider since no % column)
    n_cands = len(top_candidates)
    min_pt = 65 + n_cands * cand_vw + 20
    eff_w = max(page_width, min_pt / 28.45)
    col_spec = "1fr" + "".join([f", {cand_vw}pt"] * n_cands)

    def _esc(s):
        return s.replace("\\", "\\\\").replace("#", "\\#").replace("@", "\\@")

    L = [
        "#let pure_black = cmyk(0%, 0%, 0%, 100%)",
        "",
        "#set text(",
        '  font: ("PT Sans", "Roboto"),',
        "  size: 11pt,",
        "  fill: pure_black,",
        "  fallback: true,",
        "  stretch: 75%,",
        '  features: ("tnum",)',
        ")",
        "#set par(leading: 0.42em)",
        "",
        f"#page(width: {eff_w:.1f}cm, height: auto, margin: 0cm)[",
        "#block(width: 100%, stroke: 0.5pt + pure_black, inset: 0pt)[",
    ]

    # Header bar
    row_label_plural = row_label + "S" if not row_label.endswith("S") else row_label
    L.append("  #block(fill: luma(185), width: 100%, inset: 6pt)[")
    L.append(
        f'    #text(size: 11pt, weight: "bold")[RESULTADO NACIONAL POR {row_label_plural}]'
    )
    L.append("  ]")
    L.append("")

    # Table wrapper
    L.append("  #pad(x: 8pt, top: 4pt, bottom: 4pt)[")
    L.append("    #block(width: 100%, radius: 3pt, clip: true, breakable: true)[")
    L.append("      #set block(spacing: 0pt)")

    # Header row 1: row_label + candidate names (no colspan since 1 col per candidate)
    h1 = [f"[*{row_label}*]"]
    for cand in top_candidates:
        safe = _esc(cand.upper())
        h1.append(
            f'align(center, text(size: 7pt, weight: "bold")[{safe}])'
        )
    L.append(f"      #grid(columns: ({col_spec}), inset: (y: {row_inset_y}pt, x: 3pt),")
    L.append("        " + ", ".join(h1))
    L.append("      )")

    # Data rows with zebra
    for i, dept in enumerate(departments):
        dname = _esc(dept.strip("*").strip().upper())
        cells = [f"[{dname}]"]
        for cand in top_candidates:
            entry = dept_data[dept]["cands"].get(cand)
            if entry:
                v, _p = entry
                vf = f"{v:,}".replace(",", ".")
                cells.append(f"[#align(right)[{vf}]]")
            else:
                cells.append("[#align(right)[0]]")
        row_str = f"#grid(columns: ({col_spec}), inset: (y: {row_inset_y}pt, x: 3pt), {', '.join(cells)})"
        if i % 2 == 1:
            L.append(
                f"      #block(width: 100%, fill: luma(220), radius: {row_radius}pt, clip: true, inset: 0pt)["
            )
            L.append(f"        {row_str}")
            L.append("      ]")
        else:
            L.append(f"      {row_str}")

    L.append("    ]")
    L.append("  ]")

    # Footer: aggregate stats
    if stats:
        if "Todo el Ámbito" in stats:
            s = stats["Todo el Ámbito"]
        else:
            s = None
            dept_keys = set(departments)
            items = {k: stats[k] for k in dept_keys if k in stats}
            if items:

                def _sum(key):
                    return sum(v.get(key, 0) for v in items.values())

                def _avg(key):
                    vals = [v.get(key, "") for v in items.values() if v.get(key)]
                    return vals[-1] if vals else ""

                s = {
                    "votantes": _sum("votantes"),
                    "pvotantes": _avg("pvotantes"),
                    "validos": _sum("validos"),
                    "pvalidos": _avg("pvalidos"),
                    "nulos": _sum("nulos"),
                    "pnulos": _avg("pnulos"),
                    "blancos": _sum("blancos"),
                    "pblancos": _avg("pblancos"),
                    "no_marcados": _sum("no_marcados"),
                    "pno_marcados": _avg("pno_marcados"),
                    "mesas_info": _avg("mesas_info"),
                }

        if s:

            def fmt(val):
                if val is None:
                    return ""
                try:
                    n = int(str(val).replace(".", "").replace(",", ""))
                    return f"{n:,}".replace(",", ".")
                except:
                    return str(val)

            L.append("")
            L.append("  #pad(x: 10pt, top: -3pt, bottom: 8pt)[")
            L.append("    #block(")
            L.append("      fill: luma(252),")
            L.append("      radius: 4pt,")
            L.append("      inset: 5pt,")
            L.append("      stroke: 0.25pt + luma(120),")
            L.append("      width: 100%,")
            L.append("    )[")
            if eff_w <= 9.5:
                L.append("      #set text(size: 6.2pt)")
                L.append("      #grid(")
                L.append("        columns: (auto, auto, 1fr, auto, auto),")
                L.append("        column-gutter: 4pt,")
                L.append("        row-gutter: 2.2pt,")
                L.append("        inset: 1pt,")
                p_tot_str = f" ({s.get('pvotantes', '')})" if s.get('pvotantes') else ""
                p_mesas_str = f" ({s.get('pmesas', '')})" if s.get('pmesas') else ""
                L.append(
                    f"        [VOTANTES], [#align(right)[*{fmt(s.get('votantes', 0))}*#text(size: 5.4pt)[{p_tot_str}]]], [], [MESAS INF.], [#align(right)[*{s.get('mesas_info', '')}*#text(size: 5.4pt)[{p_mesas_str}]]],"
                )
                p_val_str = f" ({s.get('pvalidos', '')})" if s.get('pvalidos') else ""
                p_bla_str = f" ({s.get('pblancos', '')})" if s.get('pblancos') else ""
                L.append(
                    f"        [VÁLIDOS], [#align(right)[*{fmt(s.get('validos', 0))}*#text(size: 5.4pt)[{p_val_str}]]], [], [EN BLANCO], [#align(right)[*{fmt(s.get('blancos', 0))}*#text(size: 5.4pt)[{p_bla_str}]]],"
                )
                p_nom_str = f" ({s.get('pno_marcados', '')})" if s.get('pno_marcados') else ""
                p_nul_str = f" ({s.get('pnulos', '')})" if s.get('pnulos') else ""
                L.append(
                    f"        [NO MARC.], [#align(right)[*{fmt(s.get('no_marcados', 0))}*#text(size: 5.4pt)[{p_nom_str}]]], [], [NULOS], [#align(right)[*{fmt(s.get('nulos', 0))}*#text(size: 5.4pt)[{p_nul_str}]]],"
                )
                L.append("      )")
            else:
                L.append("      #grid(")
                L.append("        columns: (auto, auto, auto, 1fr, auto, auto, auto),")
                L.append("        column-gutter: 15pt,")
                L.append("        row-gutter: 2.2pt,")
                L.append("        inset: 1pt,")
                L.append(
                    f"        [VOTANTES], [#align(right)[*{fmt(s.get('votantes', 0))}*]], [#align(right)[{s.get('pvotantes', '')}]], [],"
                )
                L.append(
                    f"        [MESAS INFORMADAS], [#grid.cell(colspan: 2)[#align(right)[*{s.get('mesas_info', '')}*]]],"
                )
                L.append(
                    f"        [NO MARCADOS], [#align(right)[*{fmt(s.get('no_marcados', 0))}*]], [#align(right)[{s.get('pno_marcados', '')}]], [],"
                )
                L.append(
                    f"        [NULOS], [#align(right)[*{fmt(s.get('nulos', 0))}*]], [#align(right)[{s.get('pnulos', '')}]],"
                )
                L.append(
                    f"        [VÁLIDOS], [#align(right)[*{fmt(s.get('validos', 0))}*]], [#align(right)[{s.get('pvalidos', '')}]], [],"
                )
                L.append(
                    f"        [EN BLANCO], [#align(right)[*{fmt(s.get('blancos', 0))}*]], [#align(right)[{s.get('pblancos', '')}]],"
                )
                L.append("      )")
            L.append("    ]")
            L.append("  ]")

    L.append("]")
    L.append("]")

    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    return filename


# ---------------------------------------------------------------------------
# Paleta de colores para partidos colombianos
# ---------------------------------------------------------------------------
PARTY_COLORS = {
    "PARTIDO LIBERAL COLOMBIANO": "#E53935",
    "PARTIDO CONSERVADOR COLOMBIANO": "#1565C0",
    "PARTIDO CENTRO DEMOCRÁTICO": "#1A237E",
    "PACTO HISTÓRICO": "#6A1B9A",
    "COALICIÓN ALIANZA VERDE Y CENTRO ESPERANZA": "#2E7D32",
    "PARTIDO DE LA UNIÓN POR LA GENTE": "#FF8F00",
    "COALICIÓN MIRA -  COLOMBIA JUSTA LIBRES": "#00838F",
    "FUERZA CIUDADANA LA FUERZA DEL CAMBIO": "#D84315",
    "PARTIDO CAMBIO RADICAL": "#C62828",
    "PARTIDO NUEVO LIBERALISMO": "#0277BD",
    "MOVIMIENTO DE SALVACIÓN NACIONAL": "#4E342E",
    "PARTIDO COMUNES": "#827717",
    "MOVIMIENTO UNITARIO METAPOLITICO": "#37474F",
    "ESTAMOS LISTAS COLOMBIA": "#AD1457",
    "MOVIMIENTO GENTE NUEVA": "#00695C",
    "MOVIMIENTO NACIONAL SECTOR ORGANIZADO DE LA SALUD SOS COLOMBIA": "#558B2F",
}

_FALLBACK_PALETTE = [
    "#5C6BC0",
    "#26A69A",
    "#EF5350",
    "#AB47BC",
    "#FFA726",
    "#66BB6A",
    "#42A5F5",
    "#EC407A",
    "#8D6E63",
    "#78909C",
    "#7E57C2",
    "#29B6F6",
    "#D4E157",
    "#FF7043",
    "#26C6DA",
]


def _get_party_color(name: str, idx: int) -> str:
    """Devuelve un color para un partido, buscando primero en el mapa conocido."""
    upper = name.upper()
    for key, color in PARTY_COLORS.items():
        if key in upper or upper in key:
            return color
    return _FALLBACK_PALETTE[idx % len(_FALLBACK_PALETTE)]


def compile_pdf(typ_path: str) -> str:
    """Compila un archivo .typ a .pdf usando la CLI de Typst, incluyendo fuentes locales."""
    pdf_path = typ_path.replace(".typ", ".pdf")
    fonts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Fonts")
    try:
        # Usamos --font-path para que typst busque en nuestra carpeta local
        subprocess.run(
            ["typst", "compile", "--font-path", fonts_dir, typ_path, pdf_path],
            check=True,
        )
        return pdf_path
    except subprocess.CalledProcessError as e:
        return f"Error compilando PDF: {e}"


def generate_web_html(
    df,
    filename,
    stats=None,
    etype_label="",
    exclude_zero_votes=False,
    top_n=None,
    n_seats=5,
    threshold_pct=50.0,
    circ_sel=None,
):
    """Genera un archivo HTML interactivo autónomo con tablas por municipio."""
    import html as html_mod

    if exclude_zero_votes:
        df = df[df["Votos"] > 0].copy()
    if (
        circ_sel
        and circ_sel != "** TODAS LAS CIRCUNSCRIPCIONES **"
        and "Circunscripcion" in df.columns
    ):
        df = df[df["Circunscripcion"] == circ_sel].copy()
    if top_n is not None:
        top_n = int(top_n)
        parts = []
        for _, grp in df.groupby(["Municipio", "Partido"], sort=False):
            parts.append(grp.nlargest(top_n, "Votos"))
        df = pd.concat(parts, ignore_index=True)
        df = df.sort_values(
            by=["Municipio", "Partido_Votos", "Votos"], ascending=[True, False, False]
        )

    muni_groups = list(df.groupby("Municipio", sort=False))

    # Aggregate global data if more than one municipality
    global_section_html = ""
    if len(muni_groups) > 1:
        # Aggregated votes by party
        global_party_votes = (
            df.groupby("Partido")["Votos"]
            .sum()
            .sort_values(ascending=False)
            .reset_index()
        )
        total_valid_votes = global_party_votes["Votos"].sum()

        # Aggregated votes by candidate
        global_cand_votes = (
            df.groupby(["Partido", "Candidato"])["Votos"].sum().reset_index()
        )

        parties_html = ""
        for idx_p, row_p in global_party_votes.iterrows():
            party_name_raw = row_p["Partido"]
            p_name = html_mod.escape(party_name_raw.upper())
            p_votes_raw = row_p["Votos"]
            p_votes = f"{p_votes_raw:,}".replace(",", ".")
            p_perc_val = (
                (p_votes_raw / total_valid_votes * 100) if total_valid_votes > 0 else 0
            )
            p_perc = f"{p_perc_val:.2f}%"

            # Color for party
            color = _get_party_color(party_name_raw, idx_p)

            # Detail candidates for this party
            p_cands = global_cand_votes[
                global_cand_votes["Partido"] == party_name_raw
            ].sort_values("Votos", ascending=False)
            if top_n is not None:
                p_cands = p_cands.head(int(top_n))

            rows_html = ""
            for _, row_c in p_cands.iterrows():
                c_name = html_mod.escape(row_c["Candidato"].upper())
                c_v_val = int(row_c["Votos"])
                c_votes = f"{c_v_val:,}".replace(",", ".")
                c_perc_val = (c_v_val / p_votes_raw * 100) if p_votes_raw > 0 else 0
                c_perc = f"{c_perc_val:.2f}%"
                rows_html += f"<tr><td class='cand-name'>{c_name}</td><td class='num'>{c_votes}</td><td class='num'>{c_perc}</td></tr>"

            parties_html += f"""
            <div class="party-block" data-votes="{p_votes_raw}" data-party="{html_mod.escape(party_name_raw)}">
                <div class="party-header" style="border-left: 4px solid {color};">
                    <span class="party-name">{p_name}</span>
                    <span class="party-votes">{p_votes}</span>
                    <span class="party-pct">{p_perc}</span>
                </div>
                <table class="cand-table">
                    {rows_html}
                </table>
            </div>"""

        # Global stats
        global_stats_html = ""
        if stats and "Todo el Ámbito" in stats:
            s_ambito = stats["Todo el Ámbito"]

            def _to_int(v):
                if not v:
                    return 0
                try:
                    return int(str(v).replace(".", "").replace(",", ""))
                except:
                    return 0

            g_vot = _to_int(s_ambito.get("votantes"))
            g_val = _to_int(s_ambito.get("validos"))
            g_nul = _to_int(s_ambito.get("nulos"))
            g_bla = _to_int(s_ambito.get("blancos"))
            g_nma = _to_int(s_ambito.get("no_marcados"))

            if circ_sel and circ_sel != "** TODAS LAS CIRCUNSCRIPCIONES **":
                by_circ = s_ambito.get("by_circ", {})
                if circ_sel in by_circ:
                    cs = by_circ[circ_sel]
                    g_vot = _to_int(cs.get("votantes", g_vot))
                    g_val = _to_int(cs.get("validos", g_val))
                    g_nul = _to_int(cs.get("nulos", g_nul))
                    g_bla = _to_int(cs.get("blancos", g_bla))
                    g_nma = _to_int(cs.get("no_marcados", g_nma))

            def _fmt_g(val):
                return f"{val:,}".replace(",", ".")

            def _pct_g(val, total):
                return f"{(val / total * 100):.2f}%" if total > 0 else "0.00%"

            global_stats_html = f"""
            <div class="stats-footer">
                <div class="stat-row"><span>Votantes</span><strong>{_fmt_g(g_vot)}</strong></div>
                <div class="stat-row"><span>Válidos</span><strong>{_fmt_g(g_val)}</strong> <small>{_pct_g(g_val, g_vot)}</small></div>
                <div class="stat-row"><span>Nulos</span><strong>{_fmt_g(g_nul)}</strong> <small>{_pct_g(g_nul, g_vot)}</small></div>
                <div class="stat-row"><span>En Blanco</span><strong>{_fmt_g(g_bla)}</strong> <small>{_pct_g(g_bla, g_val)}</small></div>
                <div class="stat-row"><span>No Marcados</span><strong>{_fmt_g(g_nma)}</strong> <small>{_pct_g(g_nma, g_vot)}</small></div>
            </div>"""

        global_section_html = f"""
        <div class="muni-section" data-muni="__global__">
            <div class="muni-header" style="background: #2563eb;">TOTAL CONSOLIDADO (SELECCIÓN)</div>
            <div class="parties-grid">
                {parties_html}
            </div>
            {global_stats_html}
        </div>"""

    # Build municipality sections
    muni_options_html = ""
    if len(muni_groups) > 1:
        muni_options_html += '<option value="__global__">Consolidado Total</option>\n'

    sections_html = global_section_html
    for idx, (muni, group) in enumerate(muni_groups):
        muni_id = muni.replace(" ", "_").replace("'", "")
        muni_options_html += f'<option value="{html_mod.escape(muni_id)}">{html_mod.escape(muni)}</option>\n'

        page_title = f"{etype_label} {muni}".strip().upper()

        parties_html = ""
        for party, p_group in group.groupby("Partido", sort=False):
            p_name = html_mod.escape(party.upper())
            p_votes_raw = p_group.iloc[0]["Partido_Votos"]
            p_votes = f"{p_votes_raw:,}".replace(",", ".")
            p_perc = html_mod.escape(str(p_group.iloc[0]["Partido_P"]))

            # Color for party
            color = _get_party_color(party, idx)

            rows_html = ""
            for _, row in p_group.iterrows():
                c_name = html_mod.escape(row["Candidato"].upper())
                c_votes = f"{row['Votos']:,}".replace(",", ".")
                c_perc = html_mod.escape(str(row.get("P", "0%")))
                rows_html += f"""<tr>
                    <td class="cand-name">{c_name}</td>
                    <td class="num">{c_votes}</td>
                    <td class="num">{c_perc}</td>
                </tr>"""

            parties_html += f"""
            <div class="party-block" data-votes="{p_votes_raw}" data-party="{html_mod.escape(party)}">
                <div class="party-header" style="border-left: 4px solid {color};">
                    <span class="party-name">{p_name}</span>
                    <span class="party-votes">{p_votes}</span>
                    <span class="party-pct">{p_perc}</span>
                </div>
                <table class="cand-table">
                    {rows_html}
                </table>
            </div>"""

        # Stats footer
        stats_html = ""
        if stats and muni in stats:
            s = stats[muni]
            v_val = s.get("validos", 0)
            v_bla = s.get("blancos", 0)
            p_val = s.get("pvalidos", "")
            p_bla = s.get("pblancos", "")

            if circ_sel and circ_sel != "** TODAS LAS CIRCUNSCRIPCIONES **":
                by_circ = s.get("by_circ", {})
                if circ_sel in by_circ:
                    cs = by_circ[circ_sel]
                    v_val = cs.get("validos", v_val)
                    v_bla = cs.get("blancos", v_bla)
                    p_val = cs.get("pvalidos", p_val)
                    p_bla = cs.get("pblancos", p_bla)

            def _fmt(val):
                if val is None:
                    return ""
                try:
                    n = int(str(val).replace(".", "").replace(",", ""))
                    return f"{n:,}".replace(",", ".")
                except:
                    return str(val)

            stats_html = f"""
            <div class="stats-footer">
                <div class="stat-row"><span>Votantes</span><strong>{_fmt(s.get("votantes", ""))}</strong> <small>{s.get("pvotantes", "")}</small></div>
                <div class="stat-row"><span>Válidos</span><strong>{_fmt(v_val)}</strong> <small>{p_val}</small></div>
                <div class="stat-row"><span>Nulos</span><strong>{_fmt(s.get("nulos", ""))}</strong> <small>{s.get("pnulos", "")}</small></div>
                <div class="stat-row"><span>En Blanco</span><strong>{_fmt(v_bla)}</strong> <small>{p_bla}</small></div>
                <div class="stat-row"><span>No Marcados</span><strong>{_fmt(s.get("no_marcados", ""))}</strong> <small>{s.get("pno_marcados", "")}</small></div>
                <div class="stat-row"><span>Mesas</span><strong>{s.get("mesas_info", "")}</strong> <small>({s.get("pmesas", "")})</small></div>
            </div>"""

        sections_html += f"""
        <div class="muni-section" data-muni="{html_mod.escape(muni_id)}">
            <div class="muni-header">{html_mod.escape(page_title)}</div>
            <div class="parties-grid">
                {parties_html}
            </div>
            {stats_html}
        </div>"""

    total_votos = int(df["Votos"].sum())
    n_munis = df["Municipio"].nunique()
    n_partidos = df["Partido"].nunique()

    full_html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html_mod.escape(etype_label)} — Resultados Electorales</title>
<style>
:root {{
    --bg: #f8fafc; --card: #fff; --text: #1e293b; --text-light: #64748b;
    --border: #e2e8f0; --accent: #3b82f6; --party-bg: #f8fafc;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: var(--bg); color: var(--text); line-height: 1.5;
}}
.toolbar {{
    position: sticky; top: 0; z-index: 100;
    background: var(--card); border-bottom: 1px solid var(--border);
    padding: 12px 24px; display: flex; align-items: center; gap: 16px;
    flex-wrap: wrap; box-shadow: 0 1px 3px rgba(0,0,0,.06);
}}
.toolbar h1 {{ font-size: 16px; font-weight: 700; white-space: nowrap; }}
.toolbar select, .toolbar input {{
    padding: 6px 10px; border: 1px solid var(--border); border-radius: 6px;
    font-size: 13px; background: var(--bg); color: var(--text);
}}
.toolbar input {{ width: 200px; }}
.metrics {{
    display: flex; gap: 12px; padding: 16px 24px; flex-wrap: wrap;
}}
.metric {{
    background: var(--card); border: 1px solid var(--border); border-radius: 8px;
    padding: 12px 20px; flex: 1; min-width: 140px; text-align: center;
}}
.metric .val {{ font-size: 22px; font-weight: 700; color: var(--accent); }}
.metric .lbl {{ font-size: 11px; color: var(--text-light); text-transform: uppercase; letter-spacing: .5px; }}
.muni-section {{
    margin: 16px 24px; background: var(--card);
    border: 1px solid var(--border); border-radius: 10px; overflow: hidden;
}}
.muni-header {{
    background: #1e293b; color: #fff; padding: 10px 20px;
    font-size: 14px; font-weight: 700; letter-spacing: .5px;
}}
.parties-grid {{
    display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
    gap: 8px; padding: 12px;
}}
.party-block {{
    background: var(--party-bg); border: 1px solid var(--border);
    border-radius: 6px; overflow: hidden;
}}
.party-header {{
    display: flex; align-items: center; gap: 8px;
    padding: 6px 10px; background: #f1f5f9; font-size: 12px; font-weight: 700;
}}
.party-name {{ flex: 1; }}
.party-votes, .party-pct {{ font-variant-numeric: tabular-nums; min-width: 50px; text-align: right; }}
.cand-table {{ width: 100%; border-collapse: collapse; font-size: 11.5px; }}
.cand-table tr:nth-child(even) {{ background: #f8fafc; }}
.cand-table td {{ padding: 2px 10px; }}
.cand-table .cand-name {{ color: var(--text-light); padding-left: 18px; }}
.cand-table .num {{ text-align: right; font-variant-numeric: tabular-nums; min-width: 46px; }}
.stats-footer {{
    display: flex; flex-wrap: wrap; gap: 6px 20px;
    padding: 10px 20px; background: #f8fafc; border-top: 1px solid var(--border);
    font-size: 11.5px;
}}
.stat-row span {{ color: var(--text-light); }}
.stat-row strong {{ margin: 0 4px; }}
.stat-row small {{ color: var(--text-light); }}
.hidden {{ display: none !important; }}
@media print {{
    .toolbar {{ position: static; box-shadow: none; }}
    .muni-section {{ break-inside: avoid; }}
}}
</style>
</head>
<body>

<div class="toolbar">
    <h1>📊 {html_mod.escape(etype_label)} — Resultados</h1>
    <select id="filterMuni" onchange="filterByMuni()">
        <option value="__all__">Todos los municipios</option>
        {muni_options_html}
    </select>
    <input type="text" id="searchBox" placeholder="Buscar candidato o partido…" oninput="doSearch()">
</div>

<div class="metrics">
    <div class="metric"><div class="val" id="kpi-votos">{f"{total_votos:,}".replace(",", ".")}</div><div class="lbl">Votos Totales</div></div>
    <div class="metric"><div class="val" id="kpi-munis">{n_munis}</div><div class="lbl">Municipios</div></div>
    <div class="metric"><div class="val" id="kpi-partidos">{n_partidos}</div><div class="lbl">Partidos</div></div>
</div>

{sections_html}

<script>
function filterByMuni() {{
    const val = document.getElementById('filterMuni').value;
    document.querySelectorAll('.muni-section').forEach(el => {{
        el.classList.toggle('hidden', val !== '__all__' && el.dataset.muni !== val);
    }});
    updateKPIs();
}}
function doSearch() {{
    const q = document.getElementById('searchBox').value.toLowerCase();
    if (!q) {{
        document.querySelectorAll('.party-block, .muni-section').forEach(el => el.classList.remove('hidden'));
        updateKPIs();
        return;
    }}
    document.querySelectorAll('.muni-section').forEach(sec => {{
        let anyVisible = false;
        sec.querySelectorAll('.party-block').forEach(pb => {{
            const text = pb.textContent.toLowerCase();
            const match = text.includes(q);
            pb.classList.toggle('hidden', !match);
            if (match) anyVisible = true;
        }});
        sec.classList.toggle('hidden', !anyVisible);
    }});
    updateKPIs();
}}
function updateKPIs() {{
    let totalVotos = 0;
    let munisSet = new Set();
    let partiesSet = new Set();
    
    // Usamos las secciones individuales para evitar doble conteo con el consolidado
    document.querySelectorAll('.muni-section').forEach(sec => {{
        if (sec.classList.contains('hidden')) return;
        if (sec.dataset.muni === '__global__') return;
        
        munisSet.add(sec.dataset.muni);
        sec.querySelectorAll('.party-block').forEach(pb => {{
            if (pb.classList.contains('hidden')) return;
            totalVotos += parseInt(pb.dataset.votes || 0);
            partiesSet.add(pb.dataset.party);
        }});
    }});
    
    // Si la vista es el Consolidado Total, usamos sus datos directamente
    const currentMuni = document.getElementById('filterMuni').value;
    if (currentMuni === '__global__') {{
        totalVotos = 0;
        partiesSet.clear();
        munisSet.clear(); 
        const globalSec = document.querySelector('.muni-section[data-muni="__global__"]');
        if (globalSec) {{
            globalSec.querySelectorAll('.party-block').forEach(pb => {{
                if (pb.classList.contains('hidden')) return;
                totalVotos += parseInt(pb.dataset.votes || 0);
                partiesSet.add(pb.dataset.party);
            }});
            // Para el consolidado, el número de municipios es el total de munis reales en el dataset
            document.querySelectorAll('.muni-section').forEach(s => {{
                if (s.dataset.muni !== '__global__') munisSet.add(s.dataset.muni);
            }});
        }}
    }}

    document.getElementById('kpi-votos').textContent = totalVotos.toLocaleString('es-CO').replace(/,/g, '.');
    document.getElementById('kpi-munis').textContent = munisSet.size;
    document.getElementById('kpi-partidos').textContent = partiesSet.size;
}}
</script>
</body>
</html>"""

    with open(filename, "w", encoding="utf-8") as f:
        f.write(full_html)
    return filename
