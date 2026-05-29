"""
=============================================================
  MERCADO LIBRE AUTOMATION BOT
  Sistema completo: preguntas, publicaciones y dashboard
=============================================================

INSTRUCCIONES DE INSTALACIÓN (solo la primera vez):
  1. Instalá Python desde https://python.org (si no lo tenés)
  2. Abrí una terminal en esta carpeta
  3. Ejecutá: pip install requests anthropic flask schedule

CONFIGURACIÓN:
  Completá las variables en la sección CONFIGURACIÓN abajo.

PARA CORRER:
  python bot.py

Luego abrí tu navegador en: http://localhost:5000
=============================================================
"""

import os
import json
import time
import threading
import requests
import schedule
from datetime import datetime, timedelta
from flask import Flask, jsonify, render_template_string, request
import anthropic

# =============================================================
#  ⚙️  CONFIGURACIÓN — completá con tus datos de ML y Claude
# =============================================================

CONFIG = {
    # --- Mercado Libre ---
    "ML_CLIENT_ID":     "TU_CLIENT_ID_AQUI",
    "ML_CLIENT_SECRET": "TU_CLIENT_SECRET_AQUI",
    "ML_ACCESS_TOKEN":  "TU_ACCESS_TOKEN_AQUI",   # se refresca automático
    "ML_REFRESH_TOKEN": "TU_REFRESH_TOKEN_AQUI",
    "ML_USER_ID":       "TU_USER_ID_AQUI",         # número de tu cuenta ML

    # --- Claude (Anthropic) ---
    "ANTHROPIC_API_KEY": "TU_ANTHROPIC_API_KEY_AQUI",

    # --- Precios automáticos ---
    # Margen mínimo sobre costo (0.15 = 15%). No baja de esto nunca.
    "MARGEN_MINIMO": 0.15,
    # Margen máximo sobre competidor más barato (0.05 = 5% más caro máximo)
    "MARGEN_COMPETIDOR": 0.05,

    # --- Respuestas automáticas ---
    # Si es True, responde solo. Si es False, te avisa pero no responde.
    "AUTO_RESPONDER": True,

    # --- Notificaciones (opcional) ---
    "WEBHOOK_ALERTA_URL": "",  # URL de Slack/Discord/Make para alertas (dejar vacío para ignorar)
}

# =============================================================
#  BASE: Cliente de Mercado Libre
# =============================================================

class MercadoLibreClient:
    BASE = "https://api.mercadolibre.com"

    def __init__(self, cfg):
        self.cfg = cfg
        self.token = cfg["ML_ACCESS_TOKEN"]

    def headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def refrescar_token(self):
        """Renueva el access token usando el refresh token."""
        r = requests.post(f"{self.BASE}/oauth/token", data={
            "grant_type":    "refresh_token",
            "client_id":     self.cfg["ML_CLIENT_ID"],
            "client_secret": self.cfg["ML_CLIENT_SECRET"],
            "refresh_token": self.cfg["ML_REFRESH_TOKEN"],
        })
        if r.status_code == 200:
            data = r.json()
            self.token = data["access_token"]
            self.cfg["ML_REFRESH_TOKEN"] = data.get("refresh_token", self.cfg["ML_REFRESH_TOKEN"])
            log("🔑 Token refrescado correctamente")
        else:
            log(f"❌ Error al refrescar token: {r.text}")

    def get(self, endpoint, params=None):
        r = requests.get(f"{self.BASE}{endpoint}", headers=self.headers(), params=params)
        if r.status_code == 401:
            self.refrescar_token()
            r = requests.get(f"{self.BASE}{endpoint}", headers=self.headers(), params=params)
        return r.json()

    def post(self, endpoint, body):
        r = requests.post(f"{self.BASE}{endpoint}", headers=self.headers(), json=body)
        if r.status_code == 401:
            self.refrescar_token()
            r = requests.post(f"{self.BASE}{endpoint}", headers=self.headers(), json=body)
        return r.json()

    def obtener_preguntas_sin_responder(self):
        uid = self.cfg["ML_USER_ID"]
        return self.get(f"/questions/search", params={
            "seller_id": uid,
            "status": "UNANSWERED",
            "limit": 50,
        })

    def responder_pregunta(self, question_id, texto):
        return self.post(f"/answers", {"question_id": question_id, "text": texto})

    def obtener_mis_ventas(self, dias=30):
        uid = self.cfg["ML_USER_ID"]
        desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%dT00:00:00.000-03:00")
        return self.get(f"/orders/search", params={
            "seller": uid,
            "order.status": "paid",
            "order.date_created.from": desde,
        })

    def obtener_mis_publicaciones(self):
        uid = self.cfg["ML_USER_ID"]
        return self.get(f"/users/{uid}/items/search", params={"status": "active"})

    def obtener_detalle_item(self, item_id):
        return self.get(f"/items/{item_id}")

    def actualizar_precio(self, item_id, nuevo_precio):
        return requests.put(
            f"{self.BASE}/items/{item_id}",
            headers=self.headers(),
            json={"price": nuevo_precio}
        ).json()

    def obtener_visitas(self, item_id):
        return self.get(f"/items/{item_id}/visits")

    def publicar_producto(self, datos_producto):
        """Publica un nuevo producto. datos_producto es un dict con title, price, etc."""
        return self.post("/items", datos_producto)


# =============================================================
#  MOTOR DE IA: respuestas y sugerencias con Claude
# =============================================================

class MotorIA:
    def __init__(self, api_key):
        self.client = anthropic.Anthropic(api_key=api_key)

    def responder_pregunta(self, pregunta_texto, titulo_producto, descripcion_producto):
        """Genera una respuesta apropiada a una pregunta de comprador."""
        prompt = f"""Sos un vendedor profesional de Mercado Libre Argentina.
Un comprador te hizo esta pregunta sobre el producto "{titulo_producto}":

DESCRIPCIÓN DEL PRODUCTO:
{descripcion_producto[:800]}

PREGUNTA DEL COMPRADOR:
{pregunta_texto}

Respondé de forma amable, clara y concisa (máximo 3 oraciones). 
Si la pregunta no tiene que ver con el producto, igual respondé cordialmente.
No inventes información que no esté en la descripción.
Usá español rioplatense natural."""

        msg = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        return msg.content[0].text

    def generar_listing(self, info_producto):
        """Genera título y descripción optimizados para ML."""
        prompt = f"""Sos un experto en SEO de Mercado Libre Argentina.
Generá un listing optimizado para este producto:

INFO DEL PRODUCTO:
{json.dumps(info_producto, ensure_ascii=False, indent=2)}

Devolvé SOLO un JSON con este formato exacto:
{{
  "titulo": "título de máximo 60 caracteres, con palabras clave de búsqueda",
  "descripcion": "descripción de 150-300 palabras, beneficios, características, emocional"
}}"""

        msg = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )
        texto = msg.content[0].text
        # Extraer JSON de la respuesta
        inicio = texto.find("{")
        fin = texto.rfind("}") + 1
        return json.loads(texto[inicio:fin])

    def analizar_negocio(self, metricas):
        """Genera sugerencias estratégicas basadas en las métricas actuales."""
        prompt = f"""Sos un consultor de e-commerce experto en Mercado Libre Argentina.
Analizá estas métricas de ventas y dá 3 sugerencias concretas y accionables para mejorar:

MÉTRICAS ACTUALES:
{json.dumps(metricas, ensure_ascii=False, indent=2)}

Respondé en formato JSON:
{{
  "resumen": "un párrafo corto del estado actual del negocio",
  "sugerencias": [
    {{"titulo": "...", "descripcion": "...", "impacto": "alto/medio/bajo", "esfuerzo": "alto/medio/bajo"}},
    {{"titulo": "...", "descripcion": "...", "impacto": "...", "esfuerzo": "..."}},
    {{"titulo": "...", "descripcion": "...", "impacto": "...", "esfuerzo": "..."}}
  ]
}}"""

        msg = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}]
        )
        texto = msg.content[0].text
        inicio = texto.find("{")
        fin = texto.rfind("}") + 1
        return json.loads(texto[inicio:fin])


# =============================================================
#  MOTOR DE PRECIOS DINÁMICOS
# =============================================================

class MotorPrecios:
    def __init__(self, ml_client, config):
        self.ml = ml_client
        self.cfg = config

    def buscar_competidores(self, item_id):
        """Busca el mismo producto en ML y devuelve precios de competidores."""
        item = self.ml.obtener_detalle_item(item_id)
        if "title" not in item:
            return []

        # Buscar por título en la misma categoría
        resultados = self.ml.get("/sites/MLA/search", params={
            "q": item["title"][:40],
            "category": item.get("category_id", ""),
            "limit": 10,
        })

        precios = []
        for r in resultados.get("results", []):
            if r["id"] != item_id and r.get("price"):
                precios.append(r["price"])

        return sorted(precios)

    def calcular_precio_optimo(self, precio_actual, costo_estimado, precios_competidores):
        """Calcula el precio óptimo según competencia y margen."""
        if not precios_competidores:
            return precio_actual

        precio_min_competidor = precios_competidores[0]
        precio_sugerido = precio_min_competidor * (1 + self.cfg["MARGEN_COMPETIDOR"])

        # Nunca bajar del margen mínimo sobre el costo
        precio_piso = costo_estimado * (1 + self.cfg["MARGEN_MINIMO"]) if costo_estimado else 0

        return max(precio_sugerido, precio_piso, precio_actual * 0.85)  # no bajar más del 15%

    def ajustar_precios(self, items_con_costos):
        """
        items_con_costos: lista de {"item_id": "...", "costo": 1500}
        Ajusta precios automáticamente.
        """
        resultados = []
        for item_info in items_con_costos:
            item_id = item_info["item_id"]
            costo = item_info.get("costo", 0)

            item = self.ml.obtener_detalle_item(item_id)
            precio_actual = item.get("price", 0)
            competidores = self.buscar_competidores(item_id)
            precio_nuevo = self.calcular_precio_optimo(precio_actual, costo, competidores)

            if abs(precio_nuevo - precio_actual) > precio_actual * 0.02:  # solo actualiza si cambia >2%
                self.ml.actualizar_precio(item_id, precio_nuevo)
                log(f"💰 {item.get('title','?')[:40]}: ${precio_actual:.0f} → ${precio_nuevo:.0f}")
                resultados.append({"item": item.get("title"), "anterior": precio_actual, "nuevo": precio_nuevo})

        return resultados


# =============================================================
#  ORQUESTADOR: corre todo junto
# =============================================================

class SistemaAutomatizado:
    def __init__(self):
        self.ml = MercadoLibreClient(CONFIG)
        self.ia = MotorIA(CONFIG["ANTHROPIC_API_KEY"])
        self.precios = MotorPrecios(self.ml, CONFIG)
        self.log_actividad = []
        self.metricas_cache = {}
        self.ultima_actualizacion = None

    def procesar_preguntas(self):
        """Lee todas las preguntas sin responder y las responde con IA."""
        log("🔍 Buscando preguntas sin responder...")
        data = self.ml.obtener_preguntas_sin_responder()
        preguntas = data.get("questions", [])

        if not preguntas:
            log("✅ No hay preguntas pendientes")
            return

        log(f"📬 Encontré {len(preguntas)} pregunta(s) sin responder")

        for pregunta in preguntas:
            try:
                item_id = pregunta.get("item_id")
                item = self.ml.obtener_detalle_item(item_id) if item_id else {}
                titulo = item.get("title", "producto")
                descripcion = item.get("description", {}).get("plain_text", "")

                texto_pregunta = pregunta.get("text", "")
                log(f"❓ Pregunta: {texto_pregunta[:80]}")

                respuesta = self.ia.responder_pregunta(texto_pregunta, titulo, descripcion)
                log(f"💬 Respuesta: {respuesta[:80]}")

                if CONFIG["AUTO_RESPONDER"]:
                    self.ml.responder_pregunta(pregunta["id"], respuesta)
                    log("✅ Respuesta enviada")

                    self.log_actividad.append({
                        "tipo": "pregunta",
                        "hora": datetime.now().strftime("%H:%M"),
                        "detalle": f"{titulo[:30]} — {texto_pregunta[:50]}",
                        "accion": "respondida automáticamente"
                    })
                else:
                    log("⏸️ AUTO_RESPONDER desactivado — no se envió")

            except Exception as e:
                log(f"❌ Error procesando pregunta {pregunta.get('id')}: {e}")

    def actualizar_metricas(self):
        """Calcula y guarda métricas de negocio incluyendo hoy, ayer y ganancia neta."""
        log("📊 Actualizando métricas...")
        try:
            from costos import calculadora, registro_costos

            ventas_data = self.ml.obtener_mis_ventas(dias=30)
            ordenes = ventas_data.get("results", [])

            ahora = datetime.now()
            hoy = ahora.date()
            ayer = hoy - timedelta(days=1)

            def fecha_orden(o):
                try:
                    return datetime.fromisoformat(o.get("date_created","2000-01-01T00:00:00.000-03:00")[:19]).date()
                except:
                    return hoy - timedelta(days=999)

            ordenes_hoy  = [o for o in ordenes if fecha_orden(o) == hoy]
            ordenes_ayer = [o for o in ordenes if fecha_orden(o) == ayer]
            hace_7_dias  = ahora - timedelta(days=7)
            ordenes_semana = [o for o in ordenes if
                datetime.fromisoformat(o.get("date_created","2000-01-01T00:00:00.000-03:00")[:19]) > hace_7_dias]

            total_30d   = sum(o.get("total_amount", 0) for o in ordenes)
            total_hoy   = sum(o.get("total_amount", 0) for o in ordenes_hoy)
            total_ayer  = sum(o.get("total_amount", 0) for o in ordenes_ayer)
            ticket_prom = total_30d / len(ordenes) if ordenes else 0

            # Calcular ganancia neta estimada (usando costos registrados o estimando 20% si no hay datos)
            def ganancia_orden(o):
                items = o.get("order_items", [{}])
                item_id = str(items[0].get("item", {}).get("id", "")) if items else ""
                precio = o.get("total_amount", 0)
                datos = registro_costos.obtener(item_id)
                costo = datos.get("costo") or precio * 0.55  # estimado si no hay costo registrado
                calc = calculadora.calcular(precio, costo, datos.get("categoria","default"), datos.get("envio_gratis", False))
                return calc["ganancia_neta"]

            ganancia_hoy  = sum(ganancia_orden(o) for o in ordenes_hoy)
            ganancia_ayer = sum(ganancia_orden(o) for o in ordenes_ayer)
            ganancia_30d  = sum(ganancia_orden(o) for o in ordenes)

            # Feed de ventas recientes con detalle
            feed_ventas = []
            for o in sorted(ordenes, key=lambda x: x.get("date_created",""), reverse=True)[:20]:
                items = o.get("order_items", [{}])
                item  = items[0].get("item", {}) if items else {}
                precio = o.get("total_amount", 0)
                item_id = str(item.get("id",""))
                datos = registro_costos.obtener(item_id)
                costo = datos.get("costo") or precio * 0.55
                calc = calculadora.calcular(precio, costo, datos.get("categoria","default"), datos.get("envio_gratis",False))

                try:
                    fecha = datetime.fromisoformat(o.get("date_created","2000-01-01T00:00:00")[:19])
                    diff = ahora - fecha
                    if diff.seconds < 3600:
                        hace = f"hace {diff.seconds // 60} min"
                    elif diff.days == 0:
                        hace = f"hace {diff.seconds // 3600}h"
                    else:
                        hace = f"hace {diff.days}d"
                except:
                    hace = "—"

                feed_ventas.append({
                    "order_id":      str(o.get("id","")),
                    "titulo":        item.get("title","?")[:50],
                    "imagen":        item.get("thumbnail",""),
                    "precio":        round(precio, 2),
                    "ganancia_neta": round(calc["ganancia_neta"], 2),
                    "margen_pct":    round(calc["margen_neto_pct"], 1),
                    "hace":          hace,
                    "estado":        o.get("status",""),
                })

            self.metricas_cache = {
                "total_ventas_30d":      round(total_30d, 2),
                "cantidad_ventas_30d":   len(ordenes),
                "ticket_promedio":       round(ticket_prom, 2),
                "ventas_ultima_semana":  len(ordenes_semana),
                "total_hoy":             round(total_hoy, 2),
                "total_ayer":            round(total_ayer, 2),
                "ventas_hoy":            len(ordenes_hoy),
                "ventas_ayer":           len(ordenes_ayer),
                "ganancia_neta_hoy":     round(ganancia_hoy, 2),
                "ganancia_neta_ayer":    round(ganancia_ayer, 2),
                "ganancia_neta_30d":     round(ganancia_30d, 2),
                "feed_ventas":           feed_ventas,
                "ultima_actualizacion":  ahora.strftime("%d/%m/%Y %H:%M"),
            }
            self.ultima_actualizacion = ahora
            log("✅ Métricas actualizadas")

        except Exception as e:
            log(f"❌ Error al obtener métricas: {e}")

    def obtener_sugerencias(self):
        """Pide a Claude sugerencias de negocio basadas en las métricas."""
        if not self.metricas_cache:
            self.actualizar_metricas()
        return self.ia.analizar_negocio(self.metricas_cache)

    def ciclo_completo(self):
        """Corre un ciclo completo de automatización."""
        log("=" * 50)
        log(f"🤖 Ciclo automático — {datetime.now().strftime('%d/%m %H:%M')}")
        self.procesar_preguntas()
        self.actualizar_metricas()
        log("=" * 50)


# =============================================================
#  DASHBOARD WEB (Flask)
# =============================================================

app = Flask(__name__)
sistema = SistemaAutomatizado()

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ML Bot — Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #0d0f14;
    --surface: #161920;
    --surface2: #1e2230;
    --border: rgba(255,255,255,0.07);
    --text: #e8eaf0;
    --muted: #6b7280;
    --accent: #3b82f6;
    --accent2: #10b981;
    --warn: #f59e0b;
    --danger: #ef4444;
    --mono: 'DM Mono', monospace;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'DM Sans', sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; }
  header { border-bottom: 1px solid var(--border); padding: 18px 32px; display: flex; align-items: center; justify-content: space-between; }
  .logo { font-size: 15px; font-weight: 600; letter-spacing: -.3px; display: flex; align-items: center; gap: 8px; }
  .dot { width: 8px; height: 8px; background: var(--accent2); border-radius: 50%; animation: pulse 2s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
  .status-badge { font-size: 12px; font-family: var(--mono); background: rgba(16,185,129,.12); color: var(--accent2); border: 1px solid rgba(16,185,129,.2); padding: 4px 12px; border-radius: 20px; }
  main { max-width: 1100px; margin: 0 auto; padding: 32px 24px; }
  .grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 28px; }
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 28px; }
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }
  .card-title { font-size: 11px; font-weight: 500; text-transform: uppercase; letter-spacing: .8px; color: var(--muted); margin-bottom: 10px; }
  .metric-value { font-size: 28px; font-weight: 600; letter-spacing: -1px; }
  .metric-sub { font-size: 12px; color: var(--muted); margin-top: 4px; }
  .green { color: var(--accent2); }
  .blue { color: var(--accent); }
  .amber { color: var(--warn); }
  .section-title { font-size: 14px; font-weight: 600; margin-bottom: 14px; letter-spacing: -.2px; }
  .log-item { display: flex; align-items: flex-start; gap: 10px; padding: 10px 0; border-bottom: 1px solid var(--border); font-size: 13px; }
  .log-item:last-child { border-bottom: none; }
  .log-time { font-family: var(--mono); font-size: 11px; color: var(--muted); min-width: 42px; margin-top: 2px; }
  .log-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); margin-top: 5px; flex-shrink: 0; }
  .btn { background: var(--accent); color: white; border: none; padding: 10px 20px; border-radius: 8px; font-size: 13px; font-weight: 500; cursor: pointer; font-family: 'DM Sans', sans-serif; }
  .btn:hover { opacity: .85; }
  .btn-outline { background: transparent; border: 1px solid var(--border); color: var(--text); }
  .btn-outline:hover { background: var(--surface2); }
  .sugerencia { background: var(--surface2); border-radius: 10px; padding: 14px 16px; margin-bottom: 10px; }
  .sug-titulo { font-size: 13px; font-weight: 600; margin-bottom: 4px; }
  .sug-desc { font-size: 12px; color: var(--muted); line-height: 1.5; margin-bottom: 8px; }
  .tags { display: flex; gap: 6px; }
  .tag { font-size: 11px; padding: 2px 8px; border-radius: 4px; font-family: var(--mono); }
  .tag-alto { background: rgba(239,68,68,.15); color: #fca5a5; }
  .tag-medio { background: rgba(245,158,11,.15); color: #fcd34d; }
  .tag-bajo { background: rgba(107,114,128,.15); color: #9ca3af; }
  .loading { color: var(--muted); font-size: 13px; font-style: italic; }
  @media (max-width: 700px) { .grid-4 { grid-template-columns: 1fr 1fr; } .grid-2 { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<header>
  <div class="logo"><div class="dot"></div> ML Bot Dashboard</div>
  <div style="display:flex;gap:10px;align-items:center">
    <a href="/publicar" style="font-size:12px;font-weight:500;background:rgba(59,130,246,.15);color:#60a5fa;border:1px solid rgba(59,130,246,.3);padding:6px 14px;border-radius:8px;text-decoration:none">📦 Publicar productos</a>
    <span class="status-badge" id="last-update">Cargando...</span>
  </div>
</header>
<main>
  <!-- FILA 1: Dinero en tiempo real -->
  <p style="font-size:11px;font-weight:500;text-transform:uppercase;letter-spacing:.8px;color:var(--muted);margin-bottom:10px">💰 Ingresos</p>
  <div class="grid-4" style="margin-bottom:28px">
    <div class="card"><p class="card-title">Hoy</p><p class="metric-value green" id="m-hoy">—</p><p class="metric-sub" id="m-hoy-ventas">— ventas</p></div>
    <div class="card"><p class="card-title">Ayer</p><p class="metric-value" id="m-ayer">—</p><p class="metric-sub" id="m-ayer-ventas">— ventas</p></div>
    <div class="card"><p class="card-title">Últimos 30 días</p><p class="metric-value blue" id="m-ingresos">—</p><p class="metric-sub" id="m-ventas">— órdenes</p></div>
    <div class="card"><p class="card-title">Ticket promedio</p><p class="metric-value amber" id="m-ticket">—</p><p class="metric-sub">por venta</p></div>
  </div>

  <!-- FILA 1b: Ganancia neta -->
  <p style="font-size:11px;font-weight:500;text-transform:uppercase;letter-spacing:.8px;color:var(--muted);margin-bottom:10px">💚 Ganancia neta (después de impuestos y comisiones)</p>
  <div class="grid-4" style="margin-bottom:28px">
    <div class="card"><p class="card-title">Ganancia hoy</p><p class="metric-value green" id="m-gan-hoy">—</p><p class="metric-sub">neto real</p></div>
    <div class="card"><p class="card-title">Ganancia ayer</p><p class="metric-value" id="m-gan-ayer">—</p><p class="metric-sub">neto real</p></div>
    <div class="card"><p class="card-title">Ganancia 30 días</p><p class="metric-value blue" id="m-gan-30d">—</p><p class="metric-sub">neto real</p></div>
    <div class="card"><p class="card-title">Margen estimado</p><p class="metric-value amber" id="m-margen">—</p><p class="metric-sub">% promedio</p></div>
  </div>

  <!-- FILA 2: Feed de ventas + Actividad -->
  <div class="grid-2" style="margin-bottom:28px">
    <div class="card">
      <p class="section-title">🛒 Ventas recientes</p>
      <div id="feed-ventas"><p class="loading">Sin ventas aún. Las ventas aparecen acá en tiempo real.</p></div>
    </div>
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
        <p class="section-title">⚡ Actividad del bot</p>
        <button class="btn btn-outline" style="padding:6px 12px;font-size:12px" onclick="procesarPreguntas()">🔄 Procesar preguntas</button>
      </div>
      <div id="actividad"><p class="loading">Sin actividad aún.</p></div>
    </div>
  </div>

  <!-- FILA 3: Sugerencias IA -->
  <div class="grid-2" style="margin-bottom:28px">
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
        <p class="section-title">✨ Sugerencias de la IA</p>
        <button class="btn" style="padding:6px 12px;font-size:12px" onclick="obtenerSugerencias()">Analizar</button>
      </div>
      <div id="sugerencias"><p class="loading">Presioná "Analizar" para recibir recomendaciones.</p></div>
    </div>
    <div class="card">
      <p class="section-title">🚨 Alertas — Requieren atención</p>
      <div id="alertas"><p class="loading">Sin alertas pendientes. ✅</p></div>
    </div>
  </div>

  <div style="text-align:center;margin-top:12px">
    <button class="btn btn-outline" onclick="cicloCompleto()">🤖 Ejecutar ciclo completo ahora</button>
  </div>

  <!-- Ventas pendientes de aprobación -->
  <div id="seccion-pendientes" style="margin-top:28px;display:none">
    <p style="font-size:14px;font-weight:600;margin-bottom:14px">⏳ Ventas pendientes — Aprobá para pedir en Droppers</p>
    <div id="lista-pendientes"></div>
  </div>
</main>

<script>
async function cargarPendientes() {
  const r = await fetch('/api/ventas-pendientes');
  const ventas = await r.json();
  const seccion = document.getElementById('seccion-pendientes');
  const lista = document.getElementById('lista-pendientes');
  if (!ventas.length) { seccion.style.display='none'; return; }
  seccion.style.display='block';
  lista.innerHTML = ventas.map(v => `
    <div style="background:var(--surface2);border:1px solid rgba(245,158,11,.3);border-radius:10px;padding:16px;margin-bottom:10px">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px">
        <div style="flex:1">
          <p style="font-size:13px;font-weight:600;margin:0 0 4px">${v.producto}</p>
          <p style="font-size:12px;color:var(--muted);margin:0 0 2px">👤 ${v.comprador} · 📍 ${v.ciudad}, ${v.provincia}</p>
          <p style="font-size:12px;color:var(--muted);margin:0">🏠 ${v.direccion} (CP: ${v.cp}) · 📦 x${v.cantidad}</p>
          <p style="font-size:13px;font-weight:600;color:#10b981;margin:6px 0 0">💰 $${v.total_ml?.toLocaleString('es-AR')} · ${v.hora}</p>
        </div>
        <div style="display:flex;gap:8px;flex-shrink:0;align-items:center">
          <button onclick="aprobarVenta('${v.order_id}', this)" style="background:#10b981;color:white;border:none;padding:8px 16px;border-radius:8px;font-size:13px;font-weight:500;cursor:pointer">✅ Aprobar y pedir en Droppers</button>
          <button onclick="rechazarVenta('${v.order_id}')" style="background:transparent;color:var(--muted);border:1px solid var(--border);padding:8px 12px;border-radius:8px;font-size:13px;cursor:pointer">✗</button>
        </div>
      </div>
    </div>`).join('');
}

async function aprobarVenta(orderId, btn) {
  btn.textContent = '⏳ Procesando...';
  btn.disabled = true;
  await fetch('/api/aprobar-venta/' + orderId, {method:'POST'});
  setTimeout(cargarPendientes, 3000);
}

async function rechazarVenta(orderId) {
  await fetch('/api/rechazar-venta/' + orderId, {method:'POST'});
  cargarPendientes();
}

async function cargarMetricas() {
  const r = await fetch('/api/metricas');
  const d = await r.json();
  if (d.total_ventas_30d === undefined) return;

  document.getElementById('m-hoy').textContent     = '$' + (d.total_hoy||0).toLocaleString('es-AR');
  document.getElementById('m-hoy-ventas').textContent = (d.ventas_hoy||0) + ' ventas';
  document.getElementById('m-ayer').textContent    = '$' + (d.total_ayer||0).toLocaleString('es-AR');
  document.getElementById('m-ayer-ventas').textContent = (d.ventas_ayer||0) + ' ventas';
  document.getElementById('m-ingresos').textContent = '$' + d.total_ventas_30d.toLocaleString('es-AR');
  document.getElementById('m-ventas').textContent  = d.cantidad_ventas_30d + ' órdenes';
  document.getElementById('m-ticket').textContent  = '$' + d.ticket_promedio.toLocaleString('es-AR');

  document.getElementById('m-gan-hoy').textContent  = '$' + (d.ganancia_neta_hoy||0).toLocaleString('es-AR');
  document.getElementById('m-gan-ayer').textContent = '$' + (d.ganancia_neta_ayer||0).toLocaleString('es-AR');
  document.getElementById('m-gan-30d').textContent  = '$' + (d.ganancia_neta_30d||0).toLocaleString('es-AR');
  const margen = d.total_ventas_30d > 0 ? ((d.ganancia_neta_30d / d.total_ventas_30d) * 100).toFixed(1) : 0;
  document.getElementById('m-margen').textContent  = margen + '%';

  // Feed de ventas
  const feed = d.feed_ventas || [];
  const feedEl = document.getElementById('feed-ventas');
  if (!feed.length) { feedEl.innerHTML = '<p class="loading">Sin ventas aún.</p>'; }
  else {
    feedEl.innerHTML = feed.map(v => `
      <div style="display:flex;gap:12px;align-items:center;padding:10px 0;border-bottom:1px solid var(--border)">
        ${v.imagen ? `<img src="${v.imagen}" style="width:44px;height:44px;object-fit:cover;border-radius:6px;flex-shrink:0" onerror="this.style.display='none'">` : '<div style="width:44px;height:44px;background:var(--surface2);border-radius:6px;flex-shrink:0"></div>'}
        <div style="flex:1;min-width:0">
          <p style="font-size:12px;font-weight:500;margin:0 0 2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${v.titulo}</p>
          <p style="font-size:11px;color:var(--muted);margin:0">${v.hace} · $${v.precio?.toLocaleString('es-AR')}</p>
        </div>
        <div style="text-align:right;flex-shrink:0">
          <p style="font-size:12px;font-weight:600;color:#10b981;margin:0">+$${v.ganancia_neta?.toLocaleString('es-AR')}</p>
          <p style="font-size:11px;color:var(--muted);margin:0">${v.margen_pct}% margen</p>
        </div>
      </div>`).join('');
  }

  document.getElementById('last-update').textContent = '⏱ ' + (d.ultima_actualizacion || 'Sin datos');
}

async function cargarActividad() {
  const r = await fetch('/api/actividad');
  const d = await r.json();
  const el = document.getElementById('actividad');
  if (!d.length) { el.innerHTML = '<p class="loading">Sin actividad reciente.</p>'; return; }
  el.innerHTML = d.slice(-10).reverse().map(a =>
    `<div class="log-item"><span class="log-time">${a.hora}</span><div class="log-dot"></div><div><strong>${a.tipo}</strong> — ${a.detalle}<br><span style="color:var(--muted);font-size:11px">${a.accion}</span></div></div>`
  ).join('');
}

async function obtenerSugerencias() {
  document.getElementById('sugerencias').innerHTML = '<p class="loading">Analizando tu negocio...</p>';
  const r = await fetch('/api/sugerencias');
  const d = await r.json();
  if (d.error) { document.getElementById('sugerencias').innerHTML = `<p class="loading">${d.error}</p>`; return; }
  const colores = { alto:'tag-alto', medio:'tag-medio', bajo:'tag-bajo' };
  let html = `<p style="font-size:12px;color:var(--muted);margin-bottom:12px;line-height:1.5">${d.resumen}</p>`;
  (d.sugerencias||[]).forEach(s => {
    html += `<div class="sugerencia">
      <p class="sug-titulo">${s.titulo}</p>
      <p class="sug-desc">${s.descripcion}</p>
      <div class="tags">
        <span class="tag ${colores[s.impacto]||'tag-bajo'}">impacto ${s.impacto}</span>
        <span class="tag ${colores[s.esfuerzo]||'tag-bajo'}">esfuerzo ${s.esfuerzo}</span>
      </div></div>`;
  });
  document.getElementById('sugerencias').innerHTML = html;
}

async function procesarPreguntas() {
  document.getElementById('actividad').innerHTML = '<p class="loading">Procesando preguntas...</p>';
  await fetch('/api/procesar-preguntas', {method:'POST'});
  setTimeout(() => { cargarMetricas(); cargarActividad(); }, 3000);
}

async function cicloCompleto() {
  await fetch('/api/ciclo', {method:'POST'});
  setTimeout(() => { cargarMetricas(); cargarActividad(); }, 5000);
}

cargarMetricas();
cargarActividad();
cargarPendientes();
setInterval(() => { cargarMetricas(); cargarActividad(); cargarPendientes(); }, 30000);
</script>
</body>
</html>"""


@app.route("/")
def index():
    return DASHBOARD_HTML


@app.route("/api/metricas")
def api_metricas():
    if not sistema.metricas_cache:
        sistema.actualizar_metricas()
    return jsonify(sistema.metricas_cache)


@app.route("/api/actividad")
def api_actividad():
    return jsonify(sistema.log_actividad[-50:])


@app.route("/api/sugerencias")
def api_sugerencias():
    try:
        return jsonify(sistema.obtener_sugerencias())
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/api/procesar-preguntas", methods=["POST"])
def api_preguntas():
    threading.Thread(target=sistema.procesar_preguntas).start()
    return jsonify({"status": "procesando en background"})


@app.route("/api/ciclo", methods=["POST"])
def api_ciclo():
    threading.Thread(target=sistema.ciclo_completo).start()
    return jsonify({"status": "ciclo iniciado"})


# =============================================================
#  RUTAS DEL PUBLICADOR
# =============================================================

try:
    from publicador import PublicadorML, CATEGORIAS_ML
    publicador = PublicadorML(sistema.ml, CONFIG.get("ANTHROPIC_API_KEY",""))
    PUBLICADOR_ACTIVO = True
except Exception as e:
    PUBLICADOR_ACTIVO = False
    print(f"⚠️  Publicador no disponible: {e}")

publicaciones_progreso = {"total": 0, "actual": 0, "resultados": [], "corriendo": False}


@app.route("/api/categorias-ml")
def api_categorias():
    from publicador import CATEGORIAS_ML
    return jsonify([{"nombre": k, "id": v} for k, v in CATEGORIAS_ML.items()])


@app.route("/api/calcular-precio", methods=["POST"])
def api_calcular_precio():
    try:
        from costos import CalculadoraCostos
        datos = request.json
        calc = CalculadoraCostos()
        resultado = calc.calcular(
            precio_venta=datos.get("precio_venta", 0),
            costo_droppers=datos.get("costo_droppers", 0),
            categoria=datos.get("categoria", "default"),
            envio_gratis=datos.get("envio_gratis", False),
        )
        precio_sugerido = calc.calcular_precio_para_margen(
            costo_droppers=datos.get("costo_droppers", 0),
            margen_deseado_pct=datos.get("margen_pct", 25),
            categoria=datos.get("categoria", "default"),
            envio_gratis=datos.get("envio_gratis", False),
        )
        resultado["precio_sugerido"] = precio_sugerido
        return jsonify(resultado)
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/api/publicar-masivo", methods=["POST"])
def api_publicar_masivo():
    global publicaciones_progreso
    if not PUBLICADOR_ACTIVO:
        return jsonify({"error": "Publicador no activo"})
    if publicaciones_progreso["corriendo"]:
        return jsonify({"error": "Ya hay una publicación en curso"})

    datos = request.json
    productos = datos.get("productos", [])
    config = datos.get("config", {})

    publicaciones_progreso = {"total": len(productos), "actual": 0, "resultados": [], "corriendo": True}

    def callback(actual, total, resultado):
        publicaciones_progreso["actual"] = actual
        publicaciones_progreso["resultados"].append(resultado)
        if actual >= total:
            publicaciones_progreso["corriendo"] = False

    threading.Thread(
        target=publicador.publicar_masivo,
        args=(productos, config, callback),
        daemon=True
    ).start()

    return jsonify({"status": "publicando", "total": len(productos)})


@app.route("/api/progreso-publicacion")
def api_progreso():
    return jsonify(publicaciones_progreso)


@app.route("/publicar")
def pagina_publicar():
    return PUBLICAR_HTML


# =============================================================
#  RUTAS DE PROMOCIONES
# =============================================================

try:
    from promociones import MotorPromociones
    motor_promociones = MotorPromociones(sistema.ml, CONFIG.get("ANTHROPIC_API_KEY",""))
    PROMOCIONES_ACTIVO = True
except Exception as e:
    PROMOCIONES_ACTIVO = False
    print(f"⚠️  Promociones no disponible: {e}")


@app.route("/api/promociones/resumen")
def api_promociones_resumen():
    if not PROMOCIONES_ACTIVO:
        return jsonify({"promociones_activas": 0, "detalle_activas": [], "historial": []})
    return jsonify(motor_promociones.obtener_resumen())


@app.route("/api/promociones/analizar")
def api_promociones_analizar():
    if not PROMOCIONES_ACTIVO:
        return jsonify([])
    try:
        return jsonify(motor_promociones.analizar_productos())
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/api/promociones/aplicar", methods=["POST"])
def api_aplicar_promocion():
    if not PROMOCIONES_ACTIVO:
        return jsonify({"ok": False})
    datos = request.json
    return jsonify(motor_promociones.aplicar_descuento(
        datos["item_id"], datos["descuento_pct"], datos.get("motivo", "manual")
    ))


@app.route("/api/promociones/revertir/<item_id>", methods=["POST"])
def api_revertir_promocion(item_id):
    if not PROMOCIONES_ACTIVO:
        return jsonify({"ok": False})
    return jsonify(motor_promociones.revertir_descuento(item_id))


@app.route("/api/promociones/ciclo", methods=["POST"])
def api_ciclo_promociones():
    if not PROMOCIONES_ACTIVO:
        return jsonify({"ok": False})
    threading.Thread(target=motor_promociones.ciclo_promociones, daemon=True).start()
    return jsonify({"status": "ciclo de promociones iniciado"})


# =============================================================
#  ARRANQUE
# =============================================================

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")
    # Guardar en memoria para el dashboard
    if hasattr(sistema, 'log_actividad') and "Pregunta" in msg or "respondida" in msg.lower():
        pass  # procesarPreguntas ya lo agrega al log


def scheduler_thread():
    """Corre el ciclo automático cada hora."""
    schedule.every(1).hours.do(sistema.ciclo_completo)
    schedule.every(6).hours.do(sistema.actualizar_metricas)
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════╗
║   🤖  MERCADO LIBRE AUTOMATION BOT           ║
║   Dashboard: http://localhost:5000           ║
╚══════════════════════════════════════════════╝
    """)

    # Verificar configuración
    if CONFIG["ML_ACCESS_TOKEN"] == "TU_ACCESS_TOKEN_AQUI":
        print("⚠️  ATENCIÓN: Completá tus credenciales en la sección CONFIGURACIÓN")
        print("   Abrí bot.py con un editor de texto y completá los datos.\n")
    else:
        # Primer ciclo al arrancar
        threading.Thread(target=sistema.ciclo_completo, daemon=True).start()
        # Arrancar scheduler en background
        threading.Thread(target=scheduler_thread, daemon=True).start()

    app.run(host="0.0.0.0", port=5000, debug=False)


# =============================================================
#  INTEGRACIÓN CON DROPPERS (agregar al final de bot.py)
# =============================================================

# Importar el módulo de Droppers
try:
    from droppers_bot import MonitorVentas
    monitor_ventas = MonitorVentas(sistema.ml)
    DROPPERS_ACTIVO = True
    print("✅ Módulo Droppers cargado correctamente")
except Exception as e:
    DROPPERS_ACTIVO = False
    print(f"⚠️  Módulo Droppers no disponible: {e}")


@app.route("/api/ventas-nuevas", methods=["POST"])
def api_ventas_nuevas():
    if DROPPERS_ACTIVO:
        threading.Thread(target=monitor_ventas.verificar_ventas_nuevas).start()
        return jsonify({"status": "verificando ventas nuevas"})
    return jsonify({"status": "módulo Droppers no activo"})


@app.route("/api/estado-droppers")
def api_estado_droppers():
    return jsonify({
        "activo": DROPPERS_ACTIVO,
        "ventas_procesadas": len(monitor_ventas.ventas_procesadas) if DROPPERS_ACTIVO else 0
    })


# --- Rutas para el flujo de aprobación de ventas ---

@app.route("/api/ventas-pendientes")
def api_ventas_pendientes():
    if not DROPPERS_ACTIVO:
        return jsonify([])
    pendientes = list(monitor_ventas.ventas_pendientes.values())
    # No enviar orden_raw al frontend
    for v in pendientes:
        v.pop("orden_raw", None)
    return jsonify(pendientes)

@app.route("/api/aprobar-venta/<order_id>", methods=["POST"])
def api_aprobar_venta(order_id):
    if not DROPPERS_ACTIVO:
        return jsonify({"ok": False, "error": "Droppers no activo"})
    threading.Thread(target=monitor_ventas.aprobar_venta, args=(order_id,)).start()
    return jsonify({"ok": True, "status": "procesando pedido en Droppers"})

@app.route("/api/rechazar-venta/<order_id>", methods=["POST"])
def api_rechazar_venta(order_id):
    if not DROPPERS_ACTIVO:
        return jsonify({"ok": False})
    return jsonify(monitor_ventas.rechazar_venta(order_id))

PUBLICAR_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ML Bot — Publicar Productos</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root { --bg:#0d0f14;--surface:#161920;--surface2:#1e2230;--border:rgba(255,255,255,0.07);--text:#e8eaf0;--muted:#6b7280;--accent:#3b82f6;--accent2:#10b981;--warn:#f59e0b;--danger:#ef4444; }
  * { box-sizing:border-box; margin:0; padding:0; }
  body { font-family:'DM Sans',sans-serif; background:var(--bg); color:var(--text); min-height:100vh; }
  header { border-bottom:1px solid var(--border); padding:18px 32px; display:flex; align-items:center; justify-content:space-between; }
  .logo { font-size:15px; font-weight:600; }
  main { max-width:900px; margin:0 auto; padding:32px 24px; }
  h2 { font-size:20px; font-weight:600; margin-bottom:6px; }
  .sub { font-size:13px; color:var(--muted); margin-bottom:32px; }
  .card { background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:24px; margin-bottom:20px; }
  .card-title { font-size:13px; font-weight:600; margin-bottom:16px; text-transform:uppercase; letter-spacing:.6px; color:var(--muted); }
  label { font-size:13px; font-weight:500; display:block; margin-bottom:6px; }
  select, input[type=number], input[type=text] { width:100%; background:var(--surface2); border:1px solid var(--border); border-radius:8px; padding:10px 12px; color:var(--text); font-size:13px; font-family:inherit; }
  select:focus, input:focus { outline:none; border-color:var(--accent); }
  .grid-2 { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
  .toggle-row { display:flex; align-items:center; justify-content:space-between; padding:12px 0; border-bottom:1px solid var(--border); }
  .toggle-row:last-child { border-bottom:none; }
  .toggle-label { font-size:13px; font-weight:500; }
  .toggle-sub { font-size:12px; color:var(--muted); margin-top:2px; }
  .toggle { position:relative; width:44px; height:24px; flex-shrink:0; }
  .toggle input { opacity:0; width:0; height:0; }
  .slider { position:absolute; inset:0; background:#374151; border-radius:24px; cursor:pointer; transition:.3s; }
  .slider:before { content:""; position:absolute; width:18px; height:18px; left:3px; top:3px; background:white; border-radius:50%; transition:.3s; }
  input:checked + .slider { background:var(--accent2); }
  input:checked + .slider:before { transform:translateX(20px); }
  .calc-box { background:var(--surface2); border-radius:10px; padding:16px; margin-top:16px; }
  .calc-row { display:flex; justify-content:space-between; font-size:13px; padding:4px 0; }
  .calc-total { font-weight:600; font-size:14px; color:var(--accent2); border-top:1px solid var(--border); margin-top:8px; padding-top:8px; }
  .btn { background:var(--accent); color:white; border:none; padding:12px 24px; border-radius:8px; font-size:14px; font-weight:500; cursor:pointer; font-family:inherit; width:100%; }
  .btn:hover { opacity:.85; }
  .btn:disabled { opacity:.5; cursor:not-allowed; }
  .btn-back { background:transparent; border:1px solid var(--border); color:var(--text); padding:8px 16px; border-radius:8px; font-size:13px; cursor:pointer; font-family:inherit; text-decoration:none; display:inline-block; }
  .progress-bar { height:8px; background:var(--surface2); border-radius:4px; overflow:hidden; margin-top:12px; }
  .progress-fill { height:100%; background:var(--accent2); border-radius:4px; transition:width .3s; }
  .resultado-item { padding:10px 0; border-bottom:1px solid var(--border); font-size:13px; display:flex; gap:8px; align-items:center; }
  .badge-ok { background:rgba(16,185,129,.15); color:#10b981; padding:2px 8px; border-radius:4px; font-size:11px; }
  .badge-err { background:rgba(239,68,68,.15); color:#ef4444; padding:2px 8px; border-radius:4px; font-size:11px; }
  .margen-warning { color:var(--warn); font-size:12px; margin-top:4px; }
  .margen-ok { color:var(--accent2); font-size:12px; margin-top:4px; }
</style>
</head>
<body>
<header>
  <div class="logo">📦 Publicar Productos en ML</div>
  <a href="/" class="btn-back">← Volver al dashboard</a>
</header>
<main>
  <h2>Panel de Publicación Masiva</h2>
  <p class="sub">Configurá los parámetros y el bot publica con títulos y precios optimizados por IA para el algoritmo de ML.</p>

  <!-- PASO 1: Configuración -->
  <div class="card">
    <p class="card-title">1 — Configuración de publicación</p>
    <div class="grid-2" style="margin-bottom:16px">
      <div>
        <label>Categoría de Mercado Libre</label>
        <select id="categoria" onchange="calcularPrecio()">
          <option value="">Cargando categorías...</option>
        </select>
      </div>
      <div>
        <label>Costo en Droppers (ARS)</label>
        <input type="number" id="costo" placeholder="ej: 5000" oninput="calcularPrecio()">
      </div>
    </div>
    <div class="grid-2" style="margin-bottom:16px">
      <div>
        <label>Margen de ganancia deseado (%)</label>
        <input type="number" id="margen" value="25" min="5" max="80" oninput="calcularPrecio()">
        <div id="margen-estado" style="margin-top:4px"></div>
      </div>
      <div>
        <label>Precio de venta estimado (ARS)</label>
        <input type="number" id="precio-venta" placeholder="se calcula automático" oninput="calcularDesde('precio')">
      </div>
    </div>

    <!-- Toggles -->
    <div class="toggle-row">
      <div>
        <p class="toggle-label">🚚 Envío gratis</p>
        <p class="toggle-sub">Aumenta el CTR un 35%. El costo se suma al precio automáticamente.</p>
      </div>
      <label class="toggle"><input type="checkbox" id="envio-gratis" onchange="calcularPrecio()"><span class="slider"></span></label>
    </div>

    <!-- Calculadora en tiempo real -->
    <div class="calc-box" id="calc-box" style="display:none">
      <p style="font-size:12px;font-weight:600;margin-bottom:8px;color:var(--muted)">DESGLOSE DE COSTOS</p>
      <div class="calc-row"><span>Precio de venta</span><span id="c-precio">—</span></div>
      <div class="calc-row"><span>Costo Droppers</span><span id="c-droppers" style="color:var(--danger)">—</span></div>
      <div class="calc-row"><span id="c-comision-label">Comisión ML</span><span id="c-comision" style="color:var(--danger)">—</span></div>
      <div class="calc-row"><span>IVA + IIBB</span><span id="c-impuestos" style="color:var(--danger)">—</span></div>
      <div class="calc-row"><span>Costo envío</span><span id="c-envio" style="color:var(--danger)">—</span></div>
      <div class="calc-row calc-total"><span>💚 Ganancia neta por venta</span><span id="c-ganancia">—</span></div>
      <div class="calc-row" style="font-size:12px;color:var(--muted)"><span>Margen neto real</span><span id="c-margen-real">—</span></div>
    </div>
  </div>

  <!-- PASO 2: Productos -->
  <div class="card">
    <p class="card-title">2 — Productos a publicar</p>
    <p style="font-size:13px;color:var(--muted);margin-bottom:12px">Pegá la lista de productos de Droppers en formato JSON, o ingresá uno manualmente.</p>
    <textarea id="productos-json" rows="8" style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:12px;color:var(--text);font-size:12px;font-family:'DM Mono',monospace;resize:vertical" placeholder='[
  {
    "titulo": "Auriculares Bluetooth JBL Tune 510BT",
    "costo": 8500,
    "stock": 5,
    "imagenes": ["https://..."],
    "atributos": []
  }
]'></textarea>
    <button class="btn-back" style="margin-top:10px" onclick="cargarEjemplo()">Cargar ejemplo</button>
  </div>

  <!-- PASO 3: Publicar -->
  <div class="card">
    <p class="card-title">3 — Publicar</p>
    <div id="preview-info" style="margin-bottom:16px;display:none">
      <p style="font-size:13px;color:var(--muted)">Productos a publicar: <strong id="cant-productos">0</strong> · Precio promedio estimado: <strong id="precio-promedio">—</strong></p>
    </div>
    <button class="btn" id="btn-publicar" onclick="iniciarPublicacion()">🚀 Publicar con IA</button>

    <!-- Progreso -->
    <div id="seccion-progreso" style="display:none;margin-top:20px">
      <p style="font-size:13px;margin-bottom:8px">Publicando... <span id="prog-texto">0 / 0</span></p>
      <div class="progress-bar"><div class="progress-fill" id="prog-barra" style="width:0%"></div></div>
      <div id="prog-resultados" style="margin-top:16px"></div>
    </div>
  </div>
</main>

<script>
let categoriasData = [];

async function cargarCategorias() {
  const r = await fetch('/api/categorias-ml');
  const cats = await r.json();
  categoriasData = cats;
  const sel = document.getElementById('categoria');
  sel.innerHTML = '<option value="">Seleccioná una categoría</option>' +
    cats.map(c => `<option value="${c.nombre}">${c.nombre}</option>`).join('');
}

async function calcularPrecio() {
  const costo = parseFloat(document.getElementById('costo').value) || 0;
  const margen = parseFloat(document.getElementById('margen').value) || 25;
  const categoria = document.getElementById('categoria').value || 'default';
  const envioGratis = document.getElementById('envio-gratis').checked;
  if (!costo) { document.getElementById('calc-box').style.display='none'; return; }

  const r = await fetch('/api/calcular-precio', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({costo_droppers: costo, margen_pct: margen, categoria, envio_gratis: envioGratis,
      precio_venta: parseFloat(document.getElementById('precio-venta').value) || 0})
  });
  const d = await r.json();

  if (d.precio_sugerido) document.getElementById('precio-venta').value = d.precio_sugerido;

  document.getElementById('calc-box').style.display = 'block';
  document.getElementById('c-precio').textContent = '$' + (d.precio_sugerido||0).toLocaleString('es-AR');
  document.getElementById('c-droppers').textContent = '-$' + costo.toLocaleString('es-AR');
  document.getElementById('c-comision-label').textContent = `Comisión ML (${d.tasa_comision_pct||14}%)`;
  document.getElementById('c-comision').textContent = '-$' + (d.comision_ml||0).toLocaleString('es-AR');
  document.getElementById('c-impuestos').textContent = '-$' + ((d.iva_comision||0)+(d.iibb||0)).toLocaleString('es-AR');
  document.getElementById('c-envio').textContent = envioGratis ? '-$' + (d.costo_envio||0).toLocaleString('es-AR') : '$0';
  document.getElementById('c-ganancia').textContent = '$' + (d.ganancia_neta||0).toLocaleString('es-AR');
  document.getElementById('c-margen-real').textContent = (d.margen_neto_pct||0) + '%';

  const margenEl = document.getElementById('margen-estado');
  if (d.margen_neto_pct < 10) margenEl.innerHTML = '<span class="margen-warning">⚠️ Margen muy bajo — considerá subir el precio</span>';
  else if (d.margen_neto_pct < 20) margenEl.innerHTML = '<span class="margen-warning">⚡ Margen ajustado — útil para ganar volumen al inicio</span>';
  else margenEl.innerHTML = '<span class="margen-ok">✅ Buen margen</span>';
}

function cargarEjemplo() {
  document.getElementById('productos-json').value = JSON.stringify([
    {"titulo": "Auriculares Bluetooth Inalámbricos con Micrófono", "costo": 8500, "stock": 10, "imagenes": [], "atributos": []},
    {"titulo": "Cargador USB Carga Rápida 20W Universal", "costo": 3200, "stock": 15, "imagenes": [], "atributos": []}
  ], null, 2);
  document.getElementById('preview-info').style.display='block';
  document.getElementById('cant-productos').textContent = '2';
}

async function iniciarPublicacion() {
  let productos;
  try { productos = JSON.parse(document.getElementById('productos-json').value); }
  catch(e) { alert('El JSON de productos tiene un error. Verificalo.'); return; }
  if (!productos.length) { alert('No hay productos para publicar.'); return; }

  const cat = document.getElementById('categoria').value;
  const catData = categoriasData.find(c => c.nombre === cat);
  if (!cat || !catData) { alert('Seleccioná una categoría.'); return; }

  const config = {
    categoria_nombre: cat,
    categoria_id: catData.id,
    margen_pct: parseFloat(document.getElementById('margen').value) || 25,
    envio_gratis: document.getElementById('envio-gratis').checked,
    costo_droppers: parseFloat(document.getElementById('costo').value) || 0,
  };

  document.getElementById('btn-publicar').disabled = true;
  document.getElementById('btn-publicar').textContent = '⏳ Publicando...';
  document.getElementById('seccion-progreso').style.display = 'block';

  await fetch('/api/publicar-masivo', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({productos, config})
  });

  // Polling del progreso
  const intervalo = setInterval(async () => {
    const r = await fetch('/api/progreso-publicacion');
    const p = await r.json();
    const pct = p.total > 0 ? (p.actual / p.total * 100) : 0;
    document.getElementById('prog-texto').textContent = `${p.actual} / ${p.total}`;
    document.getElementById('prog-barra').style.width = pct + '%';

    const resEl = document.getElementById('prog-resultados');
    resEl.innerHTML = p.resultados.map(r => `
      <div class="resultado-item">
        ${r.ok ? '<span class="badge-ok">✅ OK</span>' : '<span class="badge-err">❌ Error</span>'}
        <span style="flex:1">${r.titulo || r.error || '...'}</span>
        ${r.ok ? `<span style="color:var(--accent2);font-size:12px">$${r.precio?.toLocaleString('es-AR')} · ${r.margen_pct}% margen</span>` : ''}
      </div>`).join('');

    if (!p.corriendo && p.actual >= p.total && p.total > 0) {
      clearInterval(intervalo);
      document.getElementById('btn-publicar').disabled = false;
      document.getElementById('btn-publicar').textContent = '🚀 Publicar con IA';
    }
  }, 2000);
}

cargarCategorias();
</script>
</html>"""
