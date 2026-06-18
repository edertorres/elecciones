Repositorio de Datos
Sistema de Resultados Electorales

•Cámara
•Senado
•CITREP
•Consulta CNS

Hoy vamos a ver

Cambios con respecto a otras elecciones

Para los que repiten, ¿Qué hemos cambiado en el sistema, en comparación con otros años?

Aproximación genérica del sistema

Sistema de Resultados Electorales: qué lugar ocupa el Repositorio de Datos y qué papel juega

Repositorio de Datos Electorales

Arquitectura, generalidades y datos técnicos del Repositorio de Datos que conviene conocer

Información disponible en el repositorio

¿Qué archivos se pueden descargar y cómo? ¿Qué estructura tienen? ¿Qué aportan?

Siguientes pasos

Pruebas, mesa de ayuda, jornada electoral...

2

Cambios con respecto a otras elecciones

3

Cambios con respecto a otras elecciones

Todo sigue igual

… pero hay cosas nuevas

Hasta 2023

En 2025

A partir de 2026

4

Aproximación genérica al sistema

5

Aproximación genérica al sistema

Departamento

Generación de

archivos con datos

de escrutinio

departamental

01

Web de
Resultados

Web pública de

resultados de la

Registraduría

03

03

Repositorio
de datos

Repositorio con

archivos de

datos

Consolidación

Divulgación

Apps móviles

Consolidación de

datos enviados

por los

departamentos

02

Generación de

03

archivos de

divulgación

IOS

Android

6

Repositorio de datos electorales

7

Repositorio de datos electorales

Conexión

Https, con basic auth

Formato

Descarga

XML y JSON de texto plano UTF-8 y pdf

Manual (en portal web) o automática (bots)

Archivos básicos

Claves con información genérica

Archivos iniciales

Datos de ámbitos, a 0 (avance 0)

Archivos de datos

Datos de preconteo (avances)

01

02

03

04

05

06

8

01

02

03

04

05

06

Repositorio de datos electorales

¿Qué tendrá?

Archivos de Cámara, Senado, CITREP y consultas

¿Cómo estará? Comprimidos con .gz

¿Cuándo estará? Misma frecuencia que la web de divulgación

¿Dónde estará?

descargas.registraduria.gov.co

¿Quién estará?

Total Nacional

Totales Departamentales

Totales de capitales de departamentos

Totales de municipios

9

Definición de los archivos

10

Definición de los archivos

Archivo GZ

BOL_MM_XX_YYYY_1234.xml.gz

BOL caracteres fijos

MM es el código de corporación (CA, SE, CT o CN)

XX es el código de ámbito, con truco

YYYY es el número de avance

1234 es un número aleatorio

CA

XX

Sólo capitales
de
departamento

Sólo totales
de
departamento

DE

00

Total nacional

11

Definición de los archivos

Archivo GZ

Departamento
11:  Cauca

11

Código de corporación:
SE: Datos de Senado

SE

Literal fijo:
Boletín / avance

BOL

0012

Boletín
número 12

9876

Número
aleatorio

BOL

SE

11

0012 9876

12

Definición de los archivos

Archivo GZ

XML

BOL_MM_XX_YYYY_1234.xml

BOL son caracteres fijos

MM es el código de la corporación (CA, SE, CT o CN)

XX es el código de ámbito, con truco

YYYY es el número de avance

1234 es un número aleatorio

CA

XX

Sólo capitales
de
departamento

Sólo totales
de
departamento

DE

00

Total nacional

13

Definición de los archivos

Archivo GZ

XML

CONTENIDO GENERAL

Cabecera: datos generales del ámbito

Totales de circunscripciones: válidos, a listas y blancos

Detalles de cada uno de los partidos

Detalles de cada uno de los candidatos

Bloque repetido n veces, por cada ámbito

14

Definición de los archivos

Archivo GZ

XML y JSON

CONTENIDO

CABECERA

15

Definición de los archivos

Archivo GZ

XML y JSON

CONTENIDO

CABECERA

CIRCUNSCRIPCIONES

Totales de partidos

16

Definición de los archivos

Archivo GZ

XML y JSON

CONTENIDO

CABECERA

CIRCUNSCRIPCIONES

Detalles de partidos
y
candidatos

17

Definición de los archivos

Archivo GZ

XML y JSON

CONTENIDO

CABECERA

CIRCUNSCRIPCIONES

Detalles de partidos
y
candidatos

18

Acceso a los archivos

19

Acceso a los archivos

Índice en HTML

Links de xml

Links de json

Links de pdf

Índice en XML

Links de xml

Índice en json

Links de json

20

Siguientes pasos

21

Mesa de ayuda

Teléfono

Mail

Pruebas técnicas

Bog. 601 7956420

Nal. 018000 413600

L-V de 9 a 18hs

Pruebas, Simulacros,

Jornada Electoral

mdaelecciones@

minsait.com

Pruebas acordadas con

RNEC

Pruebas diarias

anunciadas en portal de

descargas

22

Dudas

23

