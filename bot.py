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
from flask import Flask, jsonify, render_template_string
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
        """Calcula y guarda métricas de negocio."""
        log("📊 Actualizando métricas...")
        try:
            ventas_data = self.ml.obtener_mis_ventas(dias=30)
            ordenes = ventas_data.get("results", [])

            total_ventas = sum(o.get("total_amount", 0) for o in ordenes)
            cantidad_ventas = len(ordenes)
            ticket_promedio = total_ventas / cantidad_ventas if cantidad_ventas else 0

            # Ventas de los últimos 7 días
            hace_7_dias = datetime.now() - timedelta(days=7)
            ventas_semana = [o for o in ordenes if
                datetime.fromisoformat(o.get("date_created","2000-01-01T00:00:00.000-03:00")[:19]) > hace_7_dias]

            self.metricas_cache = {
                "total_ventas_30d": round(total_ventas, 2),
                "cantidad_ventas_30d": cantidad_ventas,
                "ticket_promedio": round(ticket_promedio, 2),
                "ventas_ultima_semana": len(ventas_semana),
                "ingresos_ultima_semana": round(sum(o.get("total_amount",0) for o in ventas_semana), 2),
                "ultima_actualizacion": datetime.now().strftime("%d/%m/%Y %H:%M"),
            }
            self.ultima_actualizacion = datetime.now()
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
  <span class="status-badge" id="last-update">Cargando...</span>
</header>
<main>
  <div class="grid-4" id="metrics">
    <div class="card"><p class="card-title">Ingresos 30 días</p><p class="metric-value green" id="m-ingresos">—</p><p class="metric-sub">ventas pagadas</p></div>
    <div class="card"><p class="card-title">Ventas 30 días</p><p class="metric-value blue" id="m-ventas">—</p><p class="metric-sub">órdenes</p></div>
    <div class="card"><p class="card-title">Ticket promedio</p><p class="metric-value" id="m-ticket">—</p><p class="metric-sub">por venta</p></div>
    <div class="card"><p class="card-title">Esta semana</p><p class="metric-value amber" id="m-semana">—</p><p class="metric-sub">ventas en 7 días</p></div>
  </div>

  <div class="grid-2">
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
        <p class="section-title">Actividad reciente</p>
        <button class="btn btn-outline" style="padding:6px 12px;font-size:12px" onclick="procesarPreguntas()">🔄 Procesar preguntas</button>
      </div>
      <div id="actividad"><p class="loading">Sin actividad aún. Corré el ciclo para empezar.</p></div>
    </div>

    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
        <p class="section-title">Sugerencias de la IA</p>
        <button class="btn" style="padding:6px 12px;font-size:12px" onclick="obtenerSugerencias()">✨ Analizar</button>
      </div>
      <div id="sugerencias"><p class="loading">Presioná "Analizar" para recibir recomendaciones de negocio.</p></div>
    </div>
  </div>

  <div style="text-align:center;margin-top:12px">
    <button class="btn btn-outline" onclick="cicloCompleto()">🤖 Ejecutar ciclo completo ahora</button>
  </div>

  <div id="seccion-pendientes" style="margin-top:28px;display:none">
    <p style="font-size:14px;font-weight:500;margin-bottom:14px;color:var(--color-text-primary)">⏳ Ventas pendientes de aprobación</p>
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
    <div style="background:var(--color-background-secondary);border:1px solid var(--color-border-secondary);border-radius:10px;padding:16px;margin-bottom:10px">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px">
        <div style="flex:1">
          <p style="font-size:13px;font-weight:500;margin:0 0 4px">${v.producto}</p>
          <p style="font-size:12px;color:var(--color-text-secondary);margin:0 0 2px">👤 ${v.comprador} · 📍 ${v.ciudad}, ${v.provincia}</p>
          <p style="font-size:12px;color:var(--color-text-secondary);margin:0">🏠 ${v.direccion} (CP: ${v.cp}) · 📦 Cantidad: ${v.cantidad}</p>
          <p style="font-size:12px;font-weight:500;color:var(--color-text-success);margin:4px 0 0">💰 Total ML: $${v.total_ml?.toLocaleString('es-AR')}</p>
        </div>
        <div style="display:flex;gap:8px;flex-shrink:0">
          <button onclick="aprobarVenta('${v.order_id}')" style="background:#10b981;color:white;border:none;padding:8px 16px;border-radius:8px;font-size:13px;font-weight:500;cursor:pointer">✅ Aprobar y pedir en Droppers</button>
          <button onclick="rechazarVenta('${v.order_id}')" style="background:transparent;color:var(--color-text-secondary);border:1px solid var(--color-border-secondary);padding:8px 12px;border-radius:8px;font-size:13px;cursor:pointer">✗ Ignorar</button>
        </div>
      </div>
    </div>`).join('');
}

async function aprobarVenta(orderId) {
  const btn = event.target;
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
  if (d.total_ventas_30d !== undefined) {
    document.getElementById('m-ingresos').textContent = '$' + d.total_ventas_30d.toLocaleString('es-AR');
    document.getElementById('m-ventas').textContent = d.cantidad_ventas_30d;
    document.getElementById('m-ticket').textContent = '$' + d.ticket_promedio.toLocaleString('es-AR');
    document.getElementById('m-semana').textContent = d.ventas_ultima_semana;
    document.getElementById('last-update').textContent = '⏱ ' + (d.ultima_actualizacion || 'Sin datos');
  }
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
