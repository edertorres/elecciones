# Elecciones Dashboard

Dashboard electoral construido con NiceGUI, Pandas, Plotly y Typst.

## Desarrollo local

```bash
uv sync
PRODUCTION=false PORT=8081 uv run python nicegui_app.py
```

La app queda disponible en `http://127.0.0.1:8081`.

## Variables de entorno

Configurar en local con `.env` o en el panel de Coolify:

```env
PRODUCTION=true
PORT=8081
REG_USER=usuario_registraduria
REG_PASS=clave_registraduria
STORAGE_SECRET=cambiar-por-un-secreto-largo
```

## Despliegue en Coolify

1. Crear una aplicación desde este repositorio.
2. Seleccionar build pack `Dockerfile`.
3. Usar puerto interno `8081`.
4. Crear volúmenes persistentes para:

```text
/app/cache
/app/boletines_pdf
```

5. Configurar las variables de entorno desde el panel de Coolify.
6. Desplegar.
