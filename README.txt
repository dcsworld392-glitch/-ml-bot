=========================================================
  MERCADO LIBRE AUTOMATION BOT — Guía de instalación
=========================================================

PASO 1 — Instalar Python
  Si no lo tenés instalado:
  → Ir a https://python.org/downloads
  → Descargar la versión más reciente
  → Instalarlo (tildar "Add to PATH" durante la instalación)

PASO 2 — Instalar las librerías
  Abrí una terminal (símbolo de sistema / PowerShell en Windows,
  o Terminal en Mac/Linux) y pegá este comando:

    pip install requests anthropic flask schedule

  Esperá a que termine (puede tardar 1-2 minutos).

PASO 3 — Completar tus credenciales
  Abrí el archivo "bot.py" con cualquier editor de texto
  (Notepad, VS Code, etc.) y buscá la sección CONFIGURACIÓN.
  
  Completá estos valores con tus datos reales:
  
    "ML_CLIENT_ID":     → tu Client ID de la app ML
    "ML_CLIENT_SECRET": → tu Client Secret
    "ML_ACCESS_TOKEN":  → tu Access Token actual
    "ML_REFRESH_TOKEN": → tu Refresh Token
    "ML_USER_ID":       → tu número de usuario de ML
    "ANTHROPIC_API_KEY" → tu API key de Anthropic/Claude

  ¿Dónde encontrás los datos de ML?
    → https://developers.mercadolibre.com.ar/apps
    → Entrá a tu app → ahí están Client ID y Client Secret
    → Para el Access Token: seguí el flujo OAuth de ML

PASO 4 — Correr el bot
  En la misma terminal, navegá a la carpeta del bot:
    cd ruta/a/la/carpeta/ml_bot

  Y ejecutá:
    python bot.py

PASO 5 — Abrir el dashboard
  Con el bot corriendo, abrí tu navegador y entrá a:
    http://localhost:5000

  ¡Listo! Vas a ver el dashboard con tus ventas en tiempo real.

=========================================================
  ¿QUÉ HACE EL BOT AUTOMÁTICAMENTE?
=========================================================

⏱  Cada 1 hora:
   - Revisa si hay preguntas sin responder en ML
   - Responde automáticamente con IA (Claude)
   - Actualiza las métricas del dashboard

📊  En el dashboard podés:
   - Ver ventas, ingresos y ticket promedio de los últimos 30 días
   - Ver el log de actividad (qué pregunta respondió, cuándo)
   - Pedir sugerencias de negocio con IA (botón "Analizar")
   - Ejecutar un ciclo manual cuando quieras

=========================================================
  PARA CORRER EN LA NUBE (24/7)
=========================================================

Opción recomendada: Railway (gratis para empezar)
  1. Crear cuenta en https://railway.app
  2. Crear nuevo proyecto → Deploy from GitHub
  3. Subir la carpeta ml_bot a un repositorio GitHub
  4. Configurar las variables de entorno en Railway
     (los mismos valores del CONFIGURACIÓN de bot.py)
  5. Railway lo corre solo, 24/7, sin que tengas que hacer nada

=========================================================
  SOPORTE
=========================================================

Si algo no funciona, los errores más comunes son:

❌ "ModuleNotFoundError" → no instalaste las librerías (Paso 2)
❌ "401 Unauthorized"   → el Access Token expiró, actualizalo
❌ "Connection refused" → el bot no está corriendo (Paso 4)

=========================================================
