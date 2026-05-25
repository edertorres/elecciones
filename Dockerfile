# Dockerfile para Coolify
FROM python:3.10-slim

# Instalar dependencias del sistema y Typst
RUN apt-get update && apt-get install -y \
    curl \
    xz-utils \
    && rm -rf /var/lib/apt/lists/*

# Descargar e instalar Typst CLI (versión x86_64)
RUN curl -L https://github.com/typst/typst/releases/download/v0.12.0/typst-x86_64-unknown-linux-musl.tar.xz \
    | tar -xJ --strip-components=1 -C /usr/local/bin typst-x86_64-unknown-linux-musl/typst

# Instalar uv para gestión de dependencias
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Directorio de trabajo
WORKDIR /app

# Copiar archivos de dependencias
COPY pyproject.toml uv.lock ./

# Instalar dependencias de Python
RUN uv sync --frozen --no-cache

# Copiar el resto del código
COPY . .

# Asegurar permisos en carpetas de ejecución
RUN mkdir -p cache boletines_pdf && chmod 777 cache boletines_pdf

# Variables de entorno por defecto
ENV PRODUCTION=true
ENV PORT=8081
ENV PYTHONUNBUFFERED=1

# Exponer el puerto de NiceGUI
EXPOSE 8081

# Healthcheck para Coolify
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/ || exit 1

# Ejecutar NiceGUI como aplicación ASGI gestionada por ui.run
CMD ["uv", "run", "python", "nicegui_app.py"]
