Información Técnica del Repositorio Electoral
Este documento resume los aspectos técnicos para el acceso y procesamiento de los resultados de la jornada electoral para la corporación de Presidencia
.
1. Datos Técnicos Principales
Protocolo de Conexión: Se requiere una conexión HTTPS con autenticación Basic (usuario y contraseña proporcionados por la Registraduría)
.
Formatos de Archivo:
JSON: Formato recomendado a futuro por ser más ligero
.
XML: Formato estándar actual
.
PDF: Formato únicamente visual, no procesable automáticamente
.
Codificación: Texto plano en UTF-8
.
Compresión: Los archivos de datos se descargan comprimidos en formato .gz
.
Frecuencia de Actualización: Los boletines se generan aproximadamente cada 5 minutos
.
Límite de Peticiones: Se recomienda un uso racional, realizando descargas como máximo cada minuto para evitar alertas en el sistema
.
2. Estructura de los Archivos
Tanto los archivos XML como los JSON contienen la misma información y siguen una estructura jerárquica
:
Cabecera: Contiene datos generales del ámbito (ej. nombre del municipio o departamento)
.
Totales de Circunscripciones: Incluye votos válidos, votos en blanco y otras categorías generales
.
Detalle de Partidos: Información consolidada por cada organización política
.
Detalle de Candidatos: Lista de candidatos por partido. Los datos vienen ordenados de mayor a menor votación (el primer candidato de la lista es el que va liderando)
.
En archivos que contienen múltiples ámbitos (como el de un departamento con todos sus municipios), este bloque de información se repite por cada jurisdicción incluida
.
3. Nombre de los Archivos
Los archivos de resultados siguen una nomenclatura estandarizada de caracteres para facilitar su identificación automática
:
Segmento
Caracteres
Descripción
Prefijo
3
Identificador de boletín o avance
.
Corporación
2
Siempre será PR (Presidencia)
.
Ámbito
2
Código del área geográfica (ver abajo)
.
Boletín
4
Número secuencial del avance o boletín
.
Aleatorio
4
Número de 4 dígitos que cambia en cada boletín por seguridad
.
Códigos de Ámbito:
00: Total Nacional
.
DE: Totales de cada departamento
.
CA: Totales de las capitales de departamento
.
Código Numérico (ej. 11): Datos específicos de un departamento (ej. Cauca)
.
4. Descripción de los Archivos
El repositorio se organiza en diferentes categorías de información
:
Archivos Básicos: Contienen datos maestros que no cambian frecuentemente, como códigos de candidatos, partidos, corporaciones y la división político-administrativa (bipol)
.
Archivos Iniciales (Boletín Cero): Archivos con la estructura completa pero con todos los contadores en cero, utilizados para verificar la inicialización del sistema
.
Archivos de Resultados (Preconteo):
Total Nacional: Un único archivo con la visión global del país
.
Totales Departamentales: Contiene el resumen de cada uno de los 33 departamentos
.
Totales de Capitales: Información específica de las ciudades capitales
.
Municipales: Archivos individuales por departamento que detallan los resultados de cada uno de sus municipios
.
Archivos de Índice (HTML/XML/JSON): Ubicados en la raíz de cada directorio de boletín, sirven para conocer los nombres exactos (incluyendo el número aleatorio) de todos los archivos de datos disponibles en ese momento
.
