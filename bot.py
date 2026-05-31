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
    "ML_CLIENT_ID":     os.environ.get("ML_CLIENT_ID", ""),
    "ML_CLIENT_SECRET": os.environ.get("ML_CLIENT_SECRET", ""),
    "ML_ACCESS_TOKEN":  os.environ.get("ML_ACCESS_TOKEN", ""),   # se refresca automático
    "ML_REFRESH_TOKEN": os.environ.get("ML_REFRESH_TOKEN", ""),
    "ML_USER_ID":       os.environ.get("ML_USER_ID", ""),         # número de tu cuenta ML

    # --- Claude (Anthropic) ---
    "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", ""),

    # --- GitHub (para historial persistente de reportes) ---
    "GITHUB_TOKEN": os.environ.get("GITHUB_TOKEN", ""),
    "GITHUB_REPO":  os.environ.get("GITHUB_REPO", "dcsworld392-glitch/-ml-bot"),

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

TOKEN_FILE = "/tmp/ml_tokens.json"

class MercadoLibreClient:
    BASE = "https://api.mercadolibre.com"

    def __init__(self, cfg):
        self.cfg = cfg
        self._ultimo_refresh = datetime.now()
        # Cargar tokens desde archivo si existe (persiste entre reinicios)
        self.token = self._cargar_token_guardado() or cfg["ML_ACCESS_TOKEN"]

    def _cargar_token_guardado(self):
        """Carga el token más reciente guardado en disco."""
        try:
            if os.path.exists(TOKEN_FILE):
                with open(TOKEN_FILE, "r") as f:
                    data = json.load(f)
                # Actualizar refresh token en config también
                if data.get("refresh_token"):
                    self.cfg["ML_REFRESH_TOKEN"] = data["refresh_token"]
                guardado_hace = (datetime.now() - datetime.fromisoformat(data.get("guardado_en", "2000-01-01"))).total_seconds()
                if guardado_hace < 20000:  # menos de 5.5 horas
                    log(f"🔑 Token cargado desde disco (guardado hace {int(guardado_hace/3600)}h {int((guardado_hace%3600)/60)}m)")
                    return data.get("access_token")
        except:
            pass
        return None

    def _guardar_token(self):
        """Guarda el token actual en disco para persistir entre reinicios."""
        try:
            with open(TOKEN_FILE, "w") as f:
                json.dump({
                    "access_token":  self.token,
                    "refresh_token": self.cfg.get("ML_REFRESH_TOKEN", ""),
                    "guardado_en":   datetime.now().isoformat(),
                }, f)
        except Exception as e:
            log(f"⚠️ No se pudo guardar token: {e}")

    def headers(self):
        # Refrescar proactivamente si el token tiene más de 5 horas
        if (datetime.now() - self._ultimo_refresh).total_seconds() > 18000:
            self.refrescar_token()
        return {"Authorization": f"Bearer {self.token}"}

    def refrescar_token(self):
        """Renueva el access token usando el refresh token y lo guarda en disco."""
        refresh = self.cfg.get("ML_REFRESH_TOKEN", "")
        if not refresh:
            log("⚠️ No hay refresh_token configurado")
            return
        r = requests.post(f"{self.BASE}/oauth/token", data={
            "grant_type":    "refresh_token",
            "client_id":     self.cfg["ML_CLIENT_ID"],
            "client_secret": self.cfg["ML_CLIENT_SECRET"],
            "refresh_token": refresh,
        })
        if r.status_code == 200:
            data = r.json()
            self.token = data["access_token"]
            self.cfg["ML_REFRESH_TOKEN"] = data.get("refresh_token", refresh)
            self._ultimo_refresh = datetime.now()
            self._guardar_token()  # Persistir en disco
            log("🔑 Token ML refrescado y guardado automáticamente")
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

    def put(self, endpoint, body):
        """Actualiza un recurso existente en ML."""
        r = requests.put(f"{self.BASE}{endpoint}", headers=self.headers(), json=body)
        if r.status_code == 401:
            self.refrescar_token()
            r = requests.put(f"{self.BASE}{endpoint}", headers=self.headers(), json=body)
        return r.json()

    def post_file(self, endpoint, files):
        """Sube un archivo (imagen) a la API de ML."""
        headers = {"Authorization": f"Bearer {self.token}"}
        r = requests.post(f"{self.BASE}{endpoint}", headers=headers, files=files)
        if r.status_code == 401:
            self.refrescar_token()
            headers = {"Authorization": f"Bearer {self.token}"}
            r = requests.post(f"{self.BASE}{endpoint}", headers=headers, files=files)
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
            model="claude-sonnet-4-5",
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
            model="claude-sonnet-4-5",
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
            model="claude-sonnet-4-5",
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
<title>Simple's — Panel de Ventas</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',sans-serif;background:#F7F6F3;color:#1a1a1a;min-height:100vh}
header{background:#fff;border-bottom:0.5px solid #e5e3de;padding:0 32px;height:56px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:10}
.brand{display:flex;align-items:center;gap:8px}
.brand-dot{width:9px;height:9px;background:#639922;border-radius:50%;animation:pulse 2.5s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
.brand-name{font-size:16px;font-weight:600;color:#1a1a1a;letter-spacing:-0.3px}
.brand-apos{color:#639922}
.hdr-right{display:flex;align-items:center;gap:8px}
.pill{font-size:11px;font-weight:500;padding:4px 12px;border-radius:20px;text-decoration:none;display:inline-flex;align-items:center;gap:5px}
.pill-green{background:#EAF3DE;color:#3B6D11;border:0.5px solid #C0DD97}
.pill-blue{background:#E6F1FB;color:#185FA5;border:0.5px solid #B5D4F4;cursor:pointer}
.pill-time{background:#F7F6F3;color:#888;border:0.5px solid #e5e3de;font-size:10px;font-family:'JetBrains Mono',monospace}
main{max-width:1120px;margin:0 auto;padding:28px 24px}
.sec-label{font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:1px;color:#999;margin-bottom:10px;display:flex;align-items:center;gap:6px}
.g4{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:20px}
.g2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-bottom:20px}
.g3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-bottom:20px}
.mc{background:#fff;border:0.5px solid #e5e3de;border-radius:10px;padding:14px 16px}
.mc-label{font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.6px;color:#999;margin-bottom:8px}
.mc-val{font-size:22px;font-weight:600;letter-spacing:-0.8px;color:#1a1a1a}
.mc-sub{font-size:11px;color:#999;margin-top:3px}
.green{color:#3B6D11}.blue{color:#185FA5}.amber{color:#854F0B}.red{color:#A32D2D}
.panel{background:#fff;border:0.5px solid #e5e3de;border-radius:10px;padding:16px 18px}
.panel-hdr{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}
.panel-title{font-size:12px;font-weight:600;color:#1a1a1a;text-transform:uppercase;letter-spacing:.5px}
.mini-btn{font-size:11px;padding:4px 10px;border-radius:8px;border:0.5px solid #e5e3de;background:#F7F6F3;color:#666;cursor:pointer;font-family:'Inter',sans-serif;font-weight:500}
.mini-btn:hover{background:#eee}
.sale-row{display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:0.5px solid #f0ede8}
.sale-row:last-child{border-bottom:none}
.sale-thumb{width:38px;height:38px;border-radius:7px;background:#F7F6F3;border:0.5px solid #e5e3de;overflow:hidden;flex-shrink:0;display:flex;align-items:center;justify-content:center;color:#ccc;font-size:16px}
.sale-name{font-size:12px;font-weight:500;color:#1a1a1a;margin-bottom:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:180px}
.sale-meta{font-size:11px;color:#999}
.sale-gain{text-align:right;flex-shrink:0}
.sale-gain-val{font-size:12px;font-weight:600;color:#3B6D11}
.sale-pct{font-size:10px;color:#999}
.loading{font-size:12px;color:#bbb;font-style:italic;padding:8px 0}
.alert-row{display:flex;align-items:flex-start;gap:10px;padding:9px 0;border-bottom:0.5px solid #f0ede8}
.alert-row:last-child{border-bottom:none}
.alert-dot{width:7px;height:7px;border-radius:50%;margin-top:4px;flex-shrink:0}
.dot-red{background:#E24B4A}.dot-amber{background:#EF9F27}.dot-green{background:#639922}
.alert-txt{font-size:12px;font-weight:500;color:#1a1a1a;margin-bottom:2px}
.alert-sub{font-size:11px;color:#999}
.resolve-btn{font-size:10px;padding:3px 8px;border-radius:6px;border:0.5px solid #B5D4F4;background:#E6F1FB;color:#185FA5;cursor:pointer;white-space:nowrap;flex-shrink:0;font-family:'Inter',sans-serif}
.promo-row{display:flex;align-items:center;gap:8px;padding:7px 0;border-bottom:0.5px solid #f0ede8}
.promo-row:last-child{border-bottom:none}
.badge-off{background:#FCEBEB;color:#A32D2D;font-size:10px;font-weight:600;padding:2px 7px;border-radius:5px;flex-shrink:0}
.badge-ok{background:#EAF3DE;color:#3B6D11;font-size:10px;font-weight:600;padding:2px 7px;border-radius:5px;flex-shrink:0}
.pending-card{background:#FAEEDA;border:0.5px solid #FAC775;border-radius:10px;padding:14px 16px;margin-bottom:10px}
.pending-title{font-size:12px;font-weight:600;color:#633806;margin-bottom:4px}
.pending-meta{font-size:11px;color:#854F0B;margin-bottom:10px;line-height:1.5}
.btn-approve{background:#3B6D11;color:#EAF3DE;border:none;padding:6px 14px;border-radius:8px;font-size:11px;font-weight:600;cursor:pointer;font-family:'Inter',sans-serif}
.btn-approve:hover{background:#2d5209}
.btn-ignore{background:transparent;color:#854F0B;border:0.5px solid #FAC775;padding:6px 10px;border-radius:8px;font-size:11px;cursor:pointer;font-family:'Inter',sans-serif}
.log-item{display:flex;align-items:flex-start;gap:8px;padding:7px 0;border-bottom:0.5px solid #f0ede8;font-size:11px}
.log-item:last-child{border-bottom:none}
.log-time{font-family:'JetBrains Mono',monospace;font-size:10px;color:#bbb;min-width:38px;margin-top:1px}
.log-dot-sm{width:5px;height:5px;border-radius:50%;background:#185FA5;margin-top:4px;flex-shrink:0}
.sug-item{background:#F7F6F3;border-radius:8px;padding:12px 14px;margin-bottom:8px}
.sug-title{font-size:12px;font-weight:600;color:#1a1a1a;margin-bottom:3px}
.sug-desc{font-size:11px;color:#666;line-height:1.5;margin-bottom:7px}
.tag{font-size:10px;padding:2px 7px;border-radius:5px;font-weight:500}
.tag-alto{background:#FCEBEB;color:#A32D2D}.tag-medio{background:#FAEEDA;color:#854F0B}.tag-bajo{background:#F7F6F3;color:#888;border:0.5px solid #e5e3de}
.cycle-btn{background:#1a1a1a;color:#fff;border:none;padding:10px 24px;border-radius:10px;font-size:12px;font-weight:500;cursor:pointer;font-family:'Inter',sans-serif}
.cycle-btn:hover{background:#333}
@media(max-width:700px){.g4{grid-template-columns:1fr 1fr}.g2,.g3{grid-template-columns:1fr}}
</style>
</head>
<body>
<header>
  <div class="brand">
    <div class="brand-dot"></div>
    <span class="brand-name">Simple<span class="brand-apos">'</span>s</span>
  </div>
  <div class="hdr-right">
    <span class="pill pill-green">● Bot activo</span>
    <span id="token-estado" class="pill" style="background:#EAF3DE;color:#3B6D11;border:0.5px solid #C0DD97;cursor:pointer" onclick="verEstadoToken()" title="Estado del token ML">🔑 Token OK</span>
    <a href="#" onclick="toggleReportePub()" class="pill pill-blue">📊 Mis publicaciones</a>
    <a href="#" onclick="togglePublicar()" class="pill pill-blue">📦 Publicar productos</a>
    <span class="pill pill-time" id="last-update">Cargando...</span>
  </div>
</header>

<main>
  <div class="sec-label">💰 Ingresos</div>
  <div class="g4">
    <div class="mc"><p class="mc-label">Hoy</p><p class="mc-val green" id="m-hoy">—</p><p class="mc-sub" id="m-hoy-v">— ventas</p></div>
    <div class="mc"><p class="mc-label">Ayer</p><p class="mc-val" id="m-ayer">—</p><p class="mc-sub" id="m-ayer-v">— ventas</p></div>
    <div class="mc"><p class="mc-label">Últimos 30 días</p><p class="mc-val blue" id="m-30d">—</p><p class="mc-sub" id="m-30d-v">— órdenes</p></div>
    <div class="mc"><p class="mc-label">Ticket promedio</p><p class="mc-val amber" id="m-ticket">—</p><p class="mc-sub">por venta</p></div>
  </div>

  <div class="sec-label">💚 Ganancia neta real (después de impuestos y comisiones)</div>
  <div class="g4">
    <div class="mc"><p class="mc-label">Ganancia hoy</p><p class="mc-val green" id="m-gan-hoy">—</p><p class="mc-sub">neto</p></div>
    <div class="mc"><p class="mc-label">Ganancia ayer</p><p class="mc-val" id="m-gan-ayer">—</p><p class="mc-sub">neto</p></div>
    <div class="mc"><p class="mc-label">Ganancia 30 días</p><p class="mc-val blue" id="m-gan-30d">—</p><p class="mc-sub">neto</p></div>
    <div class="mc"><p class="mc-label">Margen promedio</p><p class="mc-val amber" id="m-margen">—</p><p class="mc-sub">% estimado</p></div>
  </div>

  <div class="g2">
    <div class="panel">
      <div class="panel-hdr"><span class="panel-title">Ventas recientes</span><span style="font-size:10px;color:#bbb">actualiza cada 30s</span></div>
      <div id="feed-ventas"><p class="loading">Sin ventas aún. Aparecen acá en tiempo real.</p></div>
    </div>
    <div>
      <div class="panel" style="margin-bottom:10px">
        <div class="panel-hdr">
          <span class="panel-title">Alertas — requieren atención</span>
        </div>
        <div id="alertas"><p class="loading">Sin alertas pendientes ✓</p></div>
      </div>
      <div class="panel">
        <div class="panel-hdr">
          <span class="panel-title">Promociones activas</span>
          <button class="mini-btn" onclick="analizarPromociones()">Analizar</button>
        </div>
        <div id="promociones"><p class="loading">Presioná "Analizar" para ver sugerencias.</p></div>
      </div>
    </div>
  </div>

  <div class="g2">
    <div class="panel">
      <div class="panel-hdr">
        <span class="panel-title">Actividad del bot</span>
        <button class="mini-btn" onclick="procesarPreguntas()">🔄 Procesar preguntas</button>
      </div>
      <div id="actividad"><p class="loading">Sin actividad aún.</p></div>
    </div>
    <div class="panel">
      <div class="panel-hdr">
        <span class="panel-title">Sugerencias de la IA</span>
        <button class="mini-btn" onclick="obtenerSugerencias()">✨ Analizar</button>
      </div>
      <div id="sugerencias"><p class="loading">Presioná "Analizar" para recomendaciones de negocio.</p></div>
    </div>
  </div>

  <div id="seccion-pendientes" style="display:none;margin-bottom:20px">
    <div class="sec-label">⏳ Ventas pendientes — aprobá para pedir en Droppers</div>
    <div id="lista-pendientes"></div>
  </div>

  <!-- REPORTE DE PUBLICACIONES Y STOCK -->
  <div id="panel-reporte-pub" style="display:none;margin-bottom:28px">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px">
      <div class="sec-label" style="margin-bottom:0">📊 Reporte de publicaciones activas</div>
      <button class="mini-btn" onclick="toggleReportePub()">✕ Cerrar</button>
    </div>
    <div class="panel">
      <div id="reporte-pub-loading" style="text-align:center;padding:20px">
        <p style="font-size:12px;color:#999">Cargando publicaciones...</p>
      </div>
      <div id="reporte-pub-contenido" style="display:none">
        <!-- Alertas de stock -->
        <div id="alerta-stock-banner" style="display:none;background:#FCEBEB;border:0.5px solid #F5AAAA;border-radius:8px;padding:12px 14px;margin-bottom:14px">
          <p style="font-size:12px;font-weight:600;color:#A32D2D;margin-bottom:8px">⚠️ Productos con stock bajo (2 o menos unidades)</p>
          <div id="lista-stock-bajo"></div>
        </div>
        <!-- Filtros -->
        <div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap">
          <button onclick="filtrarReporte('todos')" id="fil-todos" class="mini-btn" style="background:#1a1a1a;color:white">Todos</button>
          <button onclick="filtrarReporte('rojo')" id="fil-rojo" class="mini-btn" style="color:#A32D2D">🔴 Baja calidad</button>
          <button onclick="filtrarReporte('amarillo')" id="fil-amarillo" class="mini-btn" style="color:#854F0B">🟡 Calidad media</button>
          <button onclick="filtrarReporte('verde')" id="fil-verde" class="mini-btn" style="color:#3B6D11">🟢 Buena calidad</button>
          <button onclick="filtrarReporte('sin_promo')" id="fil-sin-promo" class="mini-btn">Sin promoción</button>
        </div>
        <div id="tabla-publicaciones"></div>
      </div>
    </div>
  </div>

  <!-- Modal promoción -->
  <div id="modal-promo" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:300;align-items:center;justify-content:center">
    <div style="background:white;border-radius:12px;padding:24px;width:480px;max-width:90vw">
      <p style="font-size:14px;font-weight:600;margin-bottom:4px" id="modal-promo-titulo">Generar promoción</p>
      <p style="font-size:12px;color:#666;margin-bottom:14px">Precio actual: <strong id="modal-promo-precio"></strong></p>
      <div id="modal-promo-opciones" style="display:flex;flex-direction:column;gap:8px;margin-bottom:14px"></div>
      <div id="modal-promo-confirmacion" style="display:none;background:#EAF3DE;border-radius:8px;padding:12px;margin-bottom:12px;font-size:12px;color:#3B6D11"></div>
      <div style="display:flex;gap:8px">
        <button onclick="cerrarModalPromo()" style="flex:1;background:#F7F6F3;border:0.5px solid #e5e3de;color:#666;padding:9px;border-radius:8px;font-size:12px;cursor:pointer;font-family:'Inter',sans-serif">Cancelar</button>
        <button id="btn-confirmar-promo" onclick="confirmarPromo()" disabled style="flex:2;background:#3B6D11;color:#fff;border:none;padding:9px;border-radius:8px;font-size:12px;font-weight:500;cursor:pointer;font-family:'Inter',sans-serif;opacity:.4">Aplicar promoción</button>
      </div>
    </div>
  </div>

  <!-- Modal stock -->
  <div id="modal-stock" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:300;align-items:center;justify-content:center">
    <div style="background:white;border-radius:12px;padding:24px;width:380px;max-width:90vw">
      <p style="font-size:14px;font-weight:600;margin-bottom:4px">📦 Actualizar stock</p>
      <p style="font-size:12px;color:#666;margin-bottom:12px" id="modal-stock-titulo"></p>
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px">
        <button onclick="cambiarStock(-1)" style="width:36px;height:36px;border-radius:8px;border:0.5px solid #e5e3de;background:#F7F6F3;font-size:18px;cursor:pointer">−</button>
        <input type="number" id="modal-stock-valor" value="10" min="1" max="999" style="flex:1;text-align:center;background:#F7F6F3;border:0.5px solid #e5e3de;border-radius:8px;padding:9px;font-size:16px;font-weight:600;font-family:'Inter',sans-serif">
        <button onclick="cambiarStock(1)" style="width:36px;height:36px;border-radius:8px;border:0.5px solid #e5e3de;background:#F7F6F3;font-size:18px;cursor:pointer">+</button>
      </div>
      <div style="display:flex;gap:8px">
        <button onclick="cerrarModalStock()" style="flex:1;background:#F7F6F3;border:0.5px solid #e5e3de;color:#666;padding:9px;border-radius:8px;font-size:12px;cursor:pointer;font-family:'Inter',sans-serif">Cancelar</button>
        <button onclick="guardarStock()" style="flex:2;background:#185FA5;color:#fff;border:none;padding:9px;border-radius:8px;font-size:12px;font-weight:500;cursor:pointer;font-family:'Inter',sans-serif">Guardar stock</button>
      </div>
    </div>
  </div>
  <div id="panel-publicar" style="display:none;margin-bottom:28px">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px">
      <div class="sec-label" style="margin-bottom:0">📦 Publicar productos en ML</div>
      <button class="mini-btn" onclick="togglePublicar()">✕ Cerrar</button>
    </div>
    <div class="panel">

      <!-- PASO 1: Categoría Droppers -->
      <p style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.6px;color:#999;margin-bottom:12px">Paso 1 — Elegí la categoría de Droppers</p>
      <div class="g2" style="margin-bottom:14px">
        <div>
          <label style="font-size:12px;font-weight:500;display:block;margin-bottom:6px">Categoría de Droppers</label>
          <select id="pub-cat-droppers" style="width:100%;background:#F7F6F3;border:0.5px solid #e5e3de;border-radius:8px;padding:9px 12px;color:#1a1a1a;font-size:13px;font-family:'Inter',sans-serif">
            <option value="">Cargando...</option>
          </select>
        </div>
        <div style="display:flex;align-items:flex-end">
          <button onclick="iniciarScrape()" id="btn-scrape" style="width:100%;background:#185FA5;color:#fff;border:none;padding:9px;border-radius:8px;font-size:12px;font-weight:500;cursor:pointer;font-family:'Inter',sans-serif">🔍 Traer catálogo de Droppers</button>
        </div>
      </div>
      <div id="scrape-estado" style="display:none;background:#E6F1FB;border:0.5px solid #B5D4F4;border-radius:8px;padding:12px;margin-bottom:14px">
        <p style="font-size:12px;font-weight:600;color:#185FA5;margin-bottom:6px" id="scrape-titulo">Obteniendo catálogo...</p>
        <div style="height:5px;background:#B5D4F4;border-radius:3px;overflow:hidden;margin-bottom:6px"><div id="scrape-barra" style="height:100%;background:#185FA5;border-radius:3px;transition:width .5s;width:10%"></div></div>
        <p style="font-size:11px;color:#185FA5" id="scrape-cant">Buscando productos...</p>
      </div>

      <!-- PASO 2: Lista de productos con selección de competidor -->
      <div id="prod-preview" style="display:none;margin-bottom:16px">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
          <p style="font-size:11px;font-weight:600;color:#999;text-transform:uppercase;letter-spacing:.6px">Paso 2 — Revisá y configurá cada producto</p>
          <div style="display:flex;gap:6px">
            <button onclick="seleccionarTodos(true)" class="mini-btn">☑ Todos</button>
            <button onclick="seleccionarTodos(false)" class="mini-btn">☐ Ninguno</button>
            <button onclick="asignarCompetidorMasivo()" id="btn-comp-masivo" class="mini-btn" style="display:none">🎯 Asignar competidor a seleccionados</button>
          </div>
        </div>
        <div id="prod-lista" style="max-height:400px;overflow-y:auto;background:#F7F6F3;border-radius:8px;padding:10px;font-size:12px"></div>
      </div>

      <!-- PASO 3: Configuración global -->
      <div id="config-global" style="display:none">
        <p style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.6px;color:#999;margin-bottom:12px">Paso 3 — Configuración global</p>
        <div class="g2" style="margin-bottom:10px">
          <div>
            <label style="font-size:12px;font-weight:500;display:block;margin-bottom:6px">Margen mínimo (%)</label>
            <input type="number" id="pub-margen-min" value="15" min="5" max="50" oninput="actualizarMargenLabel()" style="width:100%;background:#F7F6F3;border:0.5px solid #e5e3de;border-radius:8px;padding:9px 12px;color:#1a1a1a;font-size:13px;font-family:'Inter',sans-serif">
            <p style="font-size:10px;color:#999;margin-top:3px">No publicar por debajo de este margen</p>
          </div>
          <div>
            <label style="font-size:12px;font-weight:500;display:block;margin-bottom:6px">Margen máximo (%)</label>
            <input type="number" id="pub-margen-max" value="35" min="10" max="80" oninput="actualizarMargenLabel()" style="width:100%;background:#F7F6F3;border:0.5px solid #e5e3de;border-radius:8px;padding:9px 12px;color:#1a1a1a;font-size:13px;font-family:'Inter',sans-serif">
            <p style="font-size:10px;color:#999;margin-top:3px">Límite superior de ganancia</p>
          </div>
        </div>
        <div id="margen-info" style="background:#F7F6F3;border-radius:8px;padding:10px 12px;margin-bottom:14px;font-size:11px;color:#666;line-height:1.5">
          La IA analizará la competencia y elegirá el precio óptimo entre <strong id="margen-label">15% y 35%</strong> para maximizar ventas.
        </div>
        <div class="g2" style="margin-bottom:14px">
          <div>
            <label style="font-size:12px;font-weight:500;display:block;margin-bottom:6px">Categoría en ML</label>
            <select id="pub-categoria" style="width:100%;background:#F7F6F3;border:0.5px solid #e5e3de;border-radius:8px;padding:9px 12px;color:#1a1a1a;font-size:13px;font-family:'Inter',sans-serif">
              <option value="">Seleccioná...</option>
            </select>
          </div>
          <div>
            <label style="font-size:12px;font-weight:500;display:block;margin-bottom:6px">Estrategia de precio</label>
            <select id="pub-estrategia" style="width:100%;background:#F7F6F3;border:0.5px solid #e5e3de;border-radius:8px;padding:9px 12px;color:#1a1a1a;font-size:13px;font-family:'Inter',sans-serif">
              <option value="competitivo">Competitivo (3% bajo competencia)</option>
              <option value="volumen">Volumen (máximo 5% bajo competencia)</option>
              <option value="margen">Margen máximo (ignorar competencia)</option>
            </select>
          </div>
        </div>
        <div style="margin-bottom:14px">
          <label style="font-size:12px;font-weight:500;display:block;margin-bottom:8px">Cuotas sin interés — costo financiero</label>
          <div style="background:#FAEEDA;border-radius:8px;padding:10px 12px;font-size:11px;color:#854F0B;margin-bottom:8px;line-height:1.5">
            ⚠️ Las cuotas sin interés se activan desde <strong>Mercado Pago → Tu negocio → Costos → Cuota Simple</strong>. Seleccioná cuántas cuotas ofrecés para que el costo se sume a tu margen.
          </div>
          <div id="cuotas-opciones" style="display:flex;gap:8px;flex-wrap:wrap"></div>
          <div id="cuotas-info" style="margin-top:8px;background:#F7F6F3;border-radius:8px;padding:10px 12px;font-size:11px;color:#666"></div>
        </div>
        <div style="display:flex;align-items:center;justify-content:space-between;padding:12px 14px;background:#F7F6F3;border-radius:8px;margin-bottom:16px;cursor:pointer" onclick="clickEnvio()">
          <div>
            <p style="font-size:12px;font-weight:500;color:#1a1a1a">🚚 Envío gratis</p>
            <p style="font-size:11px;color:#999;margin-top:2px">Aumenta el CTR. El costo se suma al precio automáticamente.</p>
          </div>
          <div style="position:relative;width:44px;height:24px;flex-shrink:0">
            <input type="checkbox" id="pub-envio" style="opacity:0;position:absolute;width:0;height:0">
            <div id="pub-envio-track" style="position:absolute;inset:0;background:#d1d5db;border-radius:24px;transition:background .2s;cursor:pointer">
              <div id="pub-envio-thumb" style="position:absolute;top:3px;left:3px;width:18px;height:18px;background:white;border-radius:50%;transition:transform .2s;box-shadow:0 1px 3px rgba(0,0,0,.2)"></div>
            </div>
          </div>
        </div>
        <button id="btn-pub" onclick="iniciarPublicacion()" disabled style="width:100%;background:#1a1a1a;color:#fff;border:none;padding:11px;border-radius:9px;font-size:13px;font-weight:500;cursor:not-allowed;font-family:'Inter',sans-serif;opacity:.4;transition:opacity .2s">
          🚀 Publicar catálogo completo con IA
        </button>
        <p id="btn-pub-hint" style="font-size:11px;color:#999;text-align:center;margin-top:6px">Primero traé el catálogo de Droppers</p>
      </div>

      <!-- Modal asignación masiva de competidor -->
      <div id="modal-comp-masivo" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:100;display:flex;align-items:center;justify-content:center">
        <div style="background:white;border-radius:12px;padding:24px;width:480px;max-width:90vw">
          <p style="font-size:14px;font-weight:600;margin-bottom:12px">🎯 Asignar competidor a productos seleccionados</p>
          <p style="font-size:12px;color:#666;margin-bottom:12px">Ingresá el nickname del vendedor en ML. La IA va a fijar precios para competir contra él en los productos seleccionados.</p>
          <div style="display:flex;gap:8px;margin-bottom:12px">
            <input type="text" id="modal-vendedor-input" placeholder="Nickname del vendedor (ej: MAXSTORE_AR)" style="flex:1;background:#F7F6F3;border:0.5px solid #e5e3de;border-radius:8px;padding:8px 12px;color:#1a1a1a;font-size:12px;font-family:'Inter',sans-serif">
            <button onclick="buscarVendedorModal()" style="background:#185FA5;color:#fff;border:none;padding:8px 14px;border-radius:8px;font-size:12px;font-weight:500;cursor:pointer;font-family:'Inter',sans-serif">Buscar</button>
          </div>
          <div id="modal-vendedor-resultado" style="margin-bottom:12px;font-size:12px;color:#666"></div>
          <div style="display:flex;gap:8px">
            <button onclick="cerrarModalComp()" style="flex:1;background:#F7F6F3;border:0.5px solid #e5e3de;color:#666;padding:8px;border-radius:8px;font-size:12px;cursor:pointer;font-family:'Inter',sans-serif">Cancelar</button>
            <button onclick="confirmarCompetidorMasivo()" id="btn-confirmar-comp" disabled style="flex:1;background:#1a1a1a;color:#fff;border:none;padding:8px;border-radius:8px;font-size:12px;font-weight:500;cursor:pointer;font-family:'Inter',sans-serif;opacity:.4">Asignar a seleccionados</button>
          </div>
        </div>
      </div>

      <div id="pub-progreso" style="display:none;margin-top:16px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
          <p style="font-size:12px;font-weight:500">Publicando... <span id="pub-prog-txt">0/0</span></p>
          <p style="font-size:11px;color:#999" id="pub-prog-eta"></p>
        </div>
        <div style="height:6px;background:#e5e3de;border-radius:3px;overflow:hidden;margin-bottom:14px"><div id="pub-prog-barra" style="height:100%;background:#3B6D11;border-radius:3px;transition:width .3s;width:0%"></div></div>
        <div id="pub-reporte" style="display:none;margin-bottom:12px">
          <div style="display:flex;gap:8px;margin-bottom:10px">
            <div style="background:#EAF3DE;border-radius:8px;padding:8px 12px;flex:1;text-align:center">
              <p style="font-size:18px;font-weight:600;color:#3B6D11" id="rep-ok">0</p>
              <p style="font-size:10px;color:#3B6D11;font-weight:500">Publicados</p>
            </div>
            <div style="background:#FCEBEB;border-radius:8px;padding:8px 12px;flex:1;text-align:center">
              <p style="font-size:18px;font-weight:600;color:#A32D2D" id="rep-err">0</p>
              <p style="font-size:10px;color:#A32D2D;font-weight:500">Errores</p>
            </div>
            <div style="background:#F7F6F3;border-radius:8px;padding:8px 12px;flex:1;text-align:center">
              <p style="font-size:18px;font-weight:600;color:#185FA5" id="rep-margin">0%</p>
              <p style="font-size:10px;color:#185FA5;font-weight:500">Margen prom.</p>
            </div>
          </div>
          <div id="pub-errores-lista" style="max-height:500px;overflow-y:auto"></div>
        </div>
        <div id="pub-resultados" style="max-height:200px;overflow-y:auto"></div>
      </div>
    </div>
  </div>

  <div style="text-align:center;padding-bottom:32px;display:flex;gap:10px;justify-content:center">
    <button class="cycle-btn" onclick="cicloCompleto()">Ejecutar ciclo completo</button>
    <button id="btn-mejorar-calidad" class="cycle-btn" style="background:#185FA5" onclick="mejorarCalidad()">✨ Mejorar calidad publicaciones</button>
    <button class="cycle-btn" style="background:#3B6D11" onclick="verHistorial()">📋 Historial de reportes</button>
  </div>
</main>

<script>
let pubCategorias = [];
let productosDroppers = [];
let pubEnvioActivo = false;
let competidoresPorProducto = {};
let vendedorModalTemp = null;

function clickEnvio() {
  pubEnvioActivo = !pubEnvioActivo;
  document.getElementById('pub-envio').checked = pubEnvioActivo;
  document.getElementById('pub-envio-track').style.background = pubEnvioActivo ? '#639922' : '#d1d5db';
  document.getElementById('pub-envio-thumb').style.transform = pubEnvioActivo ? 'translateX(20px)' : 'translateX(0)';
}

function toggleEnvio() {
  pubEnvioActivo = document.getElementById('pub-envio').checked;
  document.getElementById('pub-envio-track').style.background = pubEnvioActivo ? '#639922' : '#d1d5db';
  document.getElementById('pub-envio-thumb').style.transform = pubEnvioActivo ? 'translateX(20px)' : 'translateX(0)';
}

// Cuotas
const CUOTAS_INFO = {
  1:  {costo: 0,    label: '1 cuota',  color: '#3B6D11', bg: '#EAF3DE'},
  3:  {costo: 7.5,  label: '3 cuotas', color: '#185FA5', bg: '#E6F1FB'},
  6:  {costo: 14.5, label: '6 cuotas', color: '#854F0B', bg: '#FAEEDA'},
  9:  {costo: 19.0, label: '9 cuotas', color: '#A32D2D', bg: '#FCEBEB'},
  12: {costo: 23.0, label: '12 cuotas',color: '#A32D2D', bg: '#FCEBEB'},
};
let pubCuotasSeleccionadas = 1;

function inicializarCuotas() {
  const cont = document.getElementById('cuotas-opciones');
  if (!cont) return;
  cont.innerHTML = Object.entries(CUOTAS_INFO).map(([n, info]) => `
    <button onclick="seleccionarCuotas(${n})" id="btn-cuota-${n}"
      style="padding:6px 14px;border-radius:8px;border:0.5px solid #e5e3de;background:#F7F6F3;
             color:#666;font-size:12px;font-weight:500;cursor:pointer;font-family:'Inter',sans-serif;transition:.2s">
      ${info.label}
    </button>`).join('');
  seleccionarCuotas(1);
}

function seleccionarCuotas(n) {
  pubCuotasSeleccionadas = n;
  Object.keys(CUOTAS_INFO).forEach(k => {
    const btn = document.getElementById(`btn-cuota-${k}`);
    if (!btn) return;
    const info = CUOTAS_INFO[k];
    if (parseInt(k) === n) {
      btn.style.background = info.bg;
      btn.style.color = info.color;
      btn.style.border = `0.5px solid ${info.color}`;
      btn.style.fontWeight = '600';
    } else {
      btn.style.background = '#F7F6F3';
      btn.style.color = '#666';
      btn.style.border = '0.5px solid #e5e3de';
      btn.style.fontWeight = '500';
    }
  });
  const info = CUOTAS_INFO[n];
  const infoEl = document.getElementById('cuotas-info');
  if (infoEl) {
    infoEl.innerHTML = info.costo === 0
      ? `<span style="color:#3B6D11">✅ Sin costo extra — el comprador paga todo de una vez</span>`
      : `<span style="color:#854F0B">⚠️ ML te descuenta el <strong>${info.costo}%</strong> del precio de venta por ofrecer ${n} cuotas sin interés. Esto se suma a los costos del precio final.</span>`;
  }
}

function actualizarMargenLabel() {
  const min = document.getElementById('pub-margen-min').value || 15;
  const max = document.getElementById('pub-margen-max').value || 35;
  document.getElementById('margen-label').textContent = `${min}% y ${max}%`;
}

let vendedorObjetivo = null;

function toggleBuscadorVendedor() {
  const panel = document.getElementById('panel-vendedor');
  const btn = document.getElementById('btn-toggle-vendedor');
  if (panel.style.display === 'none') {
    panel.style.display = 'block';
    btn.textContent = 'Cancelar';
    btn.style.color = '#A32D2D';
  } else {
    panel.style.display = 'none';
    btn.textContent = 'Usar';
    btn.style.color = '';
    vendedorObjetivo = null;
    document.getElementById('vendedor-resultado').style.display = 'none';
  }
}

async function buscarVendedor() {
  const nombre = document.getElementById('buscar-vendedor-input').value.trim();
  if (!nombre) return;
  const res = document.getElementById('vendedor-resultado');
  res.style.display = 'block';
  res.innerHTML = 'Buscando...';
  try {
    const r = await fetch('/api/buscar-vendedor?nickname=' + encodeURIComponent(nombre));
    const d = await r.json();
    if (d.error || !d.id) {
      res.innerHTML = '<span style="color:#A32D2D">No se encontró el vendedor</span>';
      return;
    }
    vendedorObjetivo = d;
    res.innerHTML = `
      <div style="display:flex;align-items:center;gap:10px">
        <div>
          <p style="font-weight:600;color:#185FA5">${d.nickname}</p>
          <p style="color:#666;font-size:11px">${d.ventas||0} ventas · Reputación: ${d.reputacion||'N/A'}</p>
          <p style="color:#3B6D11;font-size:11px;margin-top:3px">✅ La IA competirá contra este vendedor</p>
        </div>
      </div>`;
  } catch(e) {
    res.innerHTML = '<span style="color:#A32D2D">Error al buscar</span>';
  }
}

function togglePublicar() {
  const p = document.getElementById('panel-publicar');
  p.style.display = p.style.display === 'none' ? 'block' : 'none';
  if (p.style.display === 'block') {
    p.scrollIntoView({behavior:'smooth'});
    cargarPubCategorias();
    inicializarCuotas();
  }
}

async function cargarPubCategorias() {
  try {
    const r = await fetch('/api/categorias-droppers');
    const cats = await r.json();
    const sel = document.getElementById('pub-cat-droppers');
    sel.innerHTML = '<option value="">Seleccioná una categoría</option>' + cats.map(c=>`<option value="${c.nombre}">${c.nombre}</option>`).join('');
  } catch(e) {}
  try {
    const r = await fetch('/api/categorias-ml');
    pubCategorias = await r.json();
    const sel = document.getElementById('pub-categoria');
    sel.innerHTML = '<option value="">Seleccioná...</option>' + pubCategorias.map(c=>`<option value="${c.nombre}">${c.nombre}</option>`).join('');
  } catch(e) {}
  try {
    const r = await fetch('/api/estado-scrape');
    const d = await r.json();
    if (d.productos > 0) {
      const r2 = await fetch('/api/productos-scrapeados');
      productosDroppers = await r2.json();
      mostrarPreviewProductos();
      habilitarBotonPublicar();
    }
  } catch(e) {}
}

function mostrarListaProductos() {
  document.getElementById('prod-preview').style.display = 'block';
  document.getElementById('scrape-estado').style.display = 'block';
  document.getElementById('scrape-titulo').textContent = `✅ ${productosDroppers.length} productos listos`;
  document.getElementById('scrape-barra').style.width = '100%';
  document.getElementById('scrape-barra').style.background = '#639922';
  document.getElementById('scrape-cant').textContent = `${productosDroppers.filter(p=>p.costo>0).length} con precio · ${productosDroppers.filter(p=>!p.costo).length} sin precio`;
  const lista = document.getElementById('prod-lista');
  lista.innerHTML = productosDroppers.map((p, i) => {
    const comp = competidoresPorProducto[i];
    return `<div style="display:flex;align-items:center;gap:8px;padding:8px;background:white;border-radius:8px;margin-bottom:6px;border:0.5px solid #e5e3de">
      <input type="checkbox" id="chk-${i}" checked onchange="actualizarSeleccion()" style="width:16px;height:16px;flex-shrink:0;cursor:pointer">
      ${p.imagenes?.[0]?`<img src="${p.imagenes[0]}" style="width:36px;height:36px;object-fit:cover;border-radius:5px;flex-shrink:0" onerror="this.style.display='none'">`:'<div style="width:36px;height:36px;background:#F7F6F3;border-radius:5px;flex-shrink:0"></div>'}
      <div style="flex:1;min-width:0">
        <p style="font-size:12px;font-weight:500;color:#1a1a1a;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${p.titulo}</p>
        <p style="font-size:11px;color:${p.costo>0?'#3B6D11':'#A32D2D'}">${p.costo>0?'$'+p.costo.toLocaleString('es-AR'):'⚠️ sin precio'}</p>
      </div>
      <div style="flex-shrink:0">
        ${comp?`<div style="background:#EAF3DE;border-radius:6px;padding:3px 7px;font-size:10px;color:#3B6D11;text-align:center">🎯 ${comp.nombre}<br><button onclick="quitarCompetidor(${i})" style="background:none;border:none;color:#A32D2D;font-size:10px;cursor:pointer;padding:0;font-family:Inter,sans-serif">✕</button></div>`
        :`<button onclick="asignarCompetidorProducto(${i})" style="background:#F7F6F3;border:0.5px solid #e5e3de;color:#666;padding:4px 8px;border-radius:6px;font-size:10px;cursor:pointer;font-family:Inter,sans-serif">🎯 Competidor</button>`}
      </div>
    </div>`;
  }).join('');
  actualizarSeleccion();
}

function mostrarPreviewProductos() { mostrarListaProductos(); }

function actualizarSeleccion() {
  const n = productosDroppers.filter((_, i) => document.getElementById(`chk-${i}`)?.checked).length;
  const btn = document.getElementById('btn-comp-masivo');
  if (btn) btn.style.display = n > 1 ? 'inline-block' : 'none';
}

function seleccionarTodos(v) {
  productosDroppers.forEach((_, i) => { const c = document.getElementById(`chk-${i}`); if(c) c.checked = v; });
  actualizarSeleccion();
}

let productoModalIndex = -1;
function asignarCompetidorProducto(i) {
  productoModalIndex = i;
  abrirModalComp();
}

function asignarCompetidorMasivo() {
  productoModalIndex = -1;
  abrirModalComp();
}

function abrirModalComp() {
  document.getElementById('modal-comp-masivo').style.display = 'flex';
  document.getElementById('modal-vendedor-input').value = '';
  document.getElementById('modal-vendedor-resultado').textContent = '';
  document.getElementById('btn-confirmar-comp').disabled = true;
  document.getElementById('btn-confirmar-comp').style.opacity = '.4';
  vendedorModalTemp = null;
}

function cerrarModalComp() {
  document.getElementById('modal-comp-masivo').style.display = 'none';
}

async function buscarVendedorModal() {
  const nick = document.getElementById('modal-vendedor-input').value.trim();
  if (!nick) return;
  document.getElementById('modal-vendedor-resultado').textContent = 'Buscando...';
  try {
    const r = await fetch('/api/buscar-vendedor?nickname=' + encodeURIComponent(nick));
    const d = await r.json();
    if (d.error || !d.id) { document.getElementById('modal-vendedor-resultado').innerHTML = '<span style="color:#A32D2D">No encontrado</span>'; return; }
    vendedorModalTemp = d;
    document.getElementById('modal-vendedor-resultado').innerHTML = `<span style="color:#3B6D11">✅ ${d.nickname} — ${d.ventas||0} ventas</span>`;
    document.getElementById('btn-confirmar-comp').disabled = false;
    document.getElementById('btn-confirmar-comp').style.opacity = '1';
  } catch(e) { document.getElementById('modal-vendedor-resultado').innerHTML = '<span style="color:#A32D2D">Error</span>'; }
}

function confirmarCompetidorMasivo() {
  if (!vendedorModalTemp) return;
  if (productoModalIndex === -1) {
    productosDroppers.forEach((_, i) => { if (document.getElementById(`chk-${i}`)?.checked) competidoresPorProducto[i] = {id: vendedorModalTemp.id, nombre: vendedorModalTemp.nickname}; });
  } else {
    competidoresPorProducto[productoModalIndex] = {id: vendedorModalTemp.id, nombre: vendedorModalTemp.nickname};
  }
  cerrarModalComp();
  mostrarListaProductos();
}

function quitarCompetidor(i) { delete competidoresPorProducto[i]; mostrarListaProductos(); }

function habilitarBotonPublicar() {
  const btn = document.getElementById('btn-pub');
  btn.disabled = false;
  btn.style.opacity = '1';
  btn.style.cursor = 'pointer';
  document.getElementById('btn-pub-hint').style.display = 'none';
}

async function iniciarScrape() {
  const cat = document.getElementById('pub-cat-droppers').value;
  if (!cat) { alert('Seleccioná una categoría de Droppers primero'); return; }
  document.getElementById('scrape-estado').style.display = 'block';
  document.getElementById('scrape-titulo').textContent = `Obteniendo catálogo de "${cat}"...`;
  document.getElementById('scrape-cant').textContent = 'Esto puede tardar 1-2 minutos...';
  document.getElementById('scrape-barra').style.width = '20%';
  document.getElementById('scrape-barra').style.background = '#185FA5';
  document.getElementById('prod-preview').style.display = 'none';
  document.getElementById('btn-pub').disabled = true;
  document.getElementById('btn-pub').style.opacity = '.4';
  await fetch('/api/scrape-droppers', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({categoria: cat})});
  const iv = setInterval(async () => {
    const r = await fetch('/api/estado-scrape');
    const d = await r.json();
    document.getElementById('scrape-barra').style.width = d.corriendo ? '60%' : '100%';
    document.getElementById('scrape-cant').textContent = `${d.productos} productos encontrados`;
    if (!d.corriendo && d.productos > 0) {
      clearInterval(iv);
      const r2 = await fetch('/api/productos-scrapeados');
      productosDroppers = await r2.json();
      competidoresPorProducto = {};
      mostrarListaProductos();
      document.getElementById('config-global').style.display = 'block';
      inicializarCuotas();
      habilitarBotonPublicar();
    }
    if (!d.corriendo && d.productos === 0) {
      clearInterval(iv);
      document.getElementById('scrape-titulo').textContent = '❌ No se encontraron productos';
    }
  }, 3000);
}

async function iniciarPublicacion() {
  const seleccionados = productosDroppers.filter((_, i) => document.getElementById(`chk-${i}`)?.checked);
  if (!seleccionados.length) { alert('Seleccioná al menos un producto'); return; }
  const cat = document.getElementById('pub-categoria').value;
  const catData = pubCategorias.find(c=>c.nombre===cat);
  if (!cat||!catData) { alert('Seleccioná la categoría de ML'); return; }
  const margenMin = parseFloat(document.getElementById('pub-margen-min').value)||15;
  const margenMax = parseFloat(document.getElementById('pub-margen-max').value)||35;
  const estrategia = document.getElementById('pub-estrategia').value;
  const envio = pubEnvioActivo;
  const productosConConfig = seleccionados.map(p => {
    const i = productosDroppers.indexOf(p);
    return {...p, vendedor_objetivo: competidoresPorProducto[i]?.id || null};
  });
  const config = {
    categoria_nombre: cat,
    categoria_id: catData.id,
    margen_pct: margenMin,
    margen_min: margenMin,
    margen_max: margenMax,
    estrategia: estrategia,
    envio_gratis: envio,
    cuotas: pubCuotasSeleccionadas,
    costo_droppers: 0
  };
  const btn = document.getElementById('btn-pub');
  btn.disabled = true;
  btn.textContent = '⏳ Publicando...';
  document.getElementById('pub-progreso').style.display = 'block';
  document.getElementById('pub-reporte').style.display = 'none';
  const inicio = Date.now();
  await fetch('/api/publicar-masivo', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({productos:productosConConfig, config})});
  const iv = setInterval(async()=>{
    const r = await fetch('/api/progreso-publicacion');
    const p = await r.json();
    const pct = p.total>0?(p.actual/p.total*100):0;
    document.getElementById('pub-prog-txt').textContent = `${p.actual}/${p.total}`;
    document.getElementById('pub-prog-barra').style.width = pct+'%';
    // ETA
    if (p.actual > 0) {
      const elapsed = (Date.now()-inicio)/1000;
      const eta = Math.round((elapsed/p.actual)*(p.total-p.actual));
      document.getElementById('pub-prog-eta').textContent = eta > 0 ? `~${eta}s restantes` : '';
    }
    // Live feed
    document.getElementById('pub-resultados').innerHTML = p.resultados.slice(-8).reverse().map(r=>
      `<div style="display:flex;gap:8px;align-items:center;padding:5px 0;border-bottom:0.5px solid #f0ede8;font-size:11px">
        <span style="background:${r.ok?'#EAF3DE':'#FCEBEB'};color:${r.ok?'#3B6D11':'#A32D2D'};padding:1px 6px;border-radius:4px;font-size:10px;font-weight:600;flex-shrink:0">${r.ok?'OK':'ERR'}</span>
        <span style="flex:1;color:#1a1a1a">${r.titulo||r.error||'...'}</span>
        ${r.ok?`<span style="color:#3B6D11;font-size:10px;flex-shrink:0">$${r.precio?.toLocaleString('es-AR')} · ${r.margen_pct?.toFixed(1)}%</span>`:''}
      </div>`
    ).join('');
    if (!p.corriendo && p.actual >= p.total && p.total > 0) {
      clearInterval(iv);
      btn.disabled = false;
      btn.textContent = '🚀 Publicar catálogo completo con IA';
      // Reporte final
      const ok = p.resultados.filter(r=>r.ok);
      const err = p.resultados.filter(r=>!r.ok);
      const margenProm = ok.length > 0 ? (ok.reduce((s,r)=>s+(r.margen_pct||0),0)/ok.length).toFixed(1) : 0;
      document.getElementById('pub-reporte').style.display = 'block';
      document.getElementById('rep-ok').textContent = ok.length;
      document.getElementById('rep-err').textContent = err.length;
      document.getElementById('rep-margin').textContent = margenProm+'%';
      document.getElementById('pub-errores-lista').innerHTML = err.map(r=>
        `<div style="padding:6px 0;border-bottom:0.5px solid #f0ede8;font-size:11px;color:#A32D2D">⚠️ ${r.titulo||''} — ${r.error||''}</div>`
      ).join('');
      // Reporte detallado por producto
      const detalleHtml = ok.map(r => `
        <div style="background:#F7F6F3;border-radius:8px;padding:12px;margin-bottom:8px">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px">
            <p style="font-size:12px;font-weight:600;color:#1a1a1a;flex:1">${r.titulo||''}</p>
            <span style="background:#EAF3DE;color:#3B6D11;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;flex-shrink:0;margin-left:8px">${r.margen_pct?.toFixed(1)}% margen</span>
          </div>
          <div style="display:flex;gap:12px;font-size:11px;color:#666;margin-bottom:8px">
            <span>💰 Precio: <strong style="color:#1a1a1a">$${r.precio?.toLocaleString('es-AR')}</strong></span>
            ${r.precio_comp ? `<span>📊 Competencia: <strong style="color:#185FA5">$${r.precio_comp?.toLocaleString('es-AR')}</strong></span>` : '<span style="color:#999">Sin competencia directa</span>'}
            <span>📦 ${r.cant_competidores||0} vendedores</span>
          </div>
          ${r.desglose ? `<div style="font-size:10px;color:#999;margin-bottom:8px">
            Costo Droppers $${r.desglose.costo_droppers?.toLocaleString('es-AR')} · Comisión ML $${r.desglose.comision_ml?.toLocaleString('es-AR')} · IVA+IIBB $${r.desglose.iva_iibb?.toLocaleString('es-AR')} · ${r.desglose.razon_margen||''}
          </div>` : ''}
          ${r.marketing ? `<div style="font-size:11px;color:#854F0B;margin-bottom:8px">📣 ${r.marketing}</div>` : ''}
          ${r.competidores && r.competidores.length > 0 ? `
            <div style="border-top:0.5px solid #e5e3de;padding-top:8px">
              <p style="font-size:10px;font-weight:600;color:#999;margin-bottom:6px;text-transform:uppercase;letter-spacing:.5px">Competidores encontrados</p>
              <div style="display:flex;gap:6px;overflow-x:auto;padding-bottom:4px">
                ${r.competidores.map(c => `
                  <a href="${c.permalink}" target="_blank" style="flex-shrink:0;width:100px;text-decoration:none">
                    <div style="background:white;border:0.5px solid #e5e3de;border-radius:6px;padding:6px;text-align:center">
                      <img src="${c.imagen}" style="width:60px;height:60px;object-fit:cover;border-radius:4px;margin-bottom:4px" onerror="this.style.display='none'">
                      <p style="font-size:10px;color:#1a1a1a;line-height:1.3;margin-bottom:3px;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical">${c.titulo}</p>
                      <p style="font-size:11px;font-weight:600;color:#185FA5">$${c.precio?.toLocaleString('es-AR')}</p>
                      ${c.envio_gratis ? '<p style="font-size:9px;color:#3B6D11">Envío gratis</p>' : ''}
                    </div>
                  </a>`).join('')}
              </div>
            </div>` : ''}
        </div>`).join('');
      document.getElementById('pub-errores-lista').innerHTML += detalleHtml;
      document.getElementById('pub-prog-eta').textContent = '✅ Finalizado';
    }
  }, 2000);
}
async function cargarPendientes(){
  const r=await fetch('/api/ventas-pendientes');
  const v=await r.json();
  const s=document.getElementById('seccion-pendientes');
  const l=document.getElementById('lista-pendientes');
  if(!v.length){s.style.display='none';return;}
  s.style.display='block';
  l.innerHTML=v.map(x=>`
    <div class="pending-card">
      <p class="pending-title">Nueva venta · ${x.hora}</p>
      <p class="pending-meta">${x.producto}<br>👤 ${x.comprador} · 📍 ${x.ciudad}, ${x.provincia}<br>🏠 ${x.direccion} (CP: ${x.cp}) · 📦 x${x.cantidad} · <strong>$${x.total_ml?.toLocaleString('es-AR')}</strong></p>
      <div style="display:flex;gap:8px">
        <button class="btn-approve" onclick="aprobarVenta('${x.order_id}',this)">Aprobar y pedir en Droppers</button>
        <button class="btn-ignore" onclick="rechazarVenta('${x.order_id}')">Ignorar</button>
      </div>
    </div>`).join('');
}

async function aprobarVenta(id,btn){btn.textContent='Procesando...';btn.disabled=true;await fetch('/api/aprobar-venta/'+id,{method:'POST'});setTimeout(cargarPendientes,3000);}
async function rechazarVenta(id){await fetch('/api/rechazar-venta/'+id,{method:'POST'});cargarPendientes();}

async function cargarMetricas(){
  const r=await fetch('/api/metricas');
  const d=await r.json();
  if(d.total_ventas_30d===undefined)return;
  document.getElementById('m-hoy').textContent='$'+(d.total_hoy||0).toLocaleString('es-AR');
  document.getElementById('m-hoy-v').textContent=(d.ventas_hoy||0)+' ventas';
  document.getElementById('m-ayer').textContent='$'+(d.total_ayer||0).toLocaleString('es-AR');
  document.getElementById('m-ayer-v').textContent=(d.ventas_ayer||0)+' ventas';
  document.getElementById('m-30d').textContent='$'+d.total_ventas_30d.toLocaleString('es-AR');
  document.getElementById('m-30d-v').textContent=d.cantidad_ventas_30d+' órdenes';
  document.getElementById('m-ticket').textContent='$'+d.ticket_promedio.toLocaleString('es-AR');
  document.getElementById('m-gan-hoy').textContent='$'+(d.ganancia_neta_hoy||0).toLocaleString('es-AR');
  document.getElementById('m-gan-ayer').textContent='$'+(d.ganancia_neta_ayer||0).toLocaleString('es-AR');
  document.getElementById('m-gan-30d').textContent='$'+(d.ganancia_neta_30d||0).toLocaleString('es-AR');
  const mg=d.total_ventas_30d>0?((d.ganancia_neta_30d/d.total_ventas_30d)*100).toFixed(1):0;
  document.getElementById('m-margen').textContent=mg+'%';
  const feed=d.feed_ventas||[];
  const fe=document.getElementById('feed-ventas');
  if(!feed.length){fe.innerHTML='<p class="loading">Sin ventas aún.</p>';}
  else{fe.innerHTML=feed.map(v=>`
    <div class="sale-row">
      <div class="sale-thumb">${v.imagen?`<img src="${v.imagen}" style="width:100%;height:100%;object-fit:cover" onerror="this.parentElement.innerHTML='📦'">`:'📦'}</div>
      <div style="flex:1;min-width:0">
        <p class="sale-name">${v.titulo}</p>
        <p class="sale-meta">${v.hace} · $${v.precio?.toLocaleString('es-AR')}</p>
      </div>
      <div class="sale-gain"><p class="sale-gain-val">+$${v.ganancia_neta?.toLocaleString('es-AR')}</p><p class="sale-pct">${v.margen_pct}% margen</p></div>
    </div>`).join('');}
  document.getElementById('last-update').textContent=d.ultima_actualizacion||'—';
}

async function cargarActividad(){
  const r=await fetch('/api/actividad');
  const d=await r.json();
  const el=document.getElementById('actividad');
  if(!d.length){el.innerHTML='<p class="loading">Sin actividad reciente.</p>';return;}
  el.innerHTML=d.slice(-8).reverse().map(a=>`<div class="log-item"><span class="log-time">${a.hora}</span><div class="log-dot-sm"></div><div><strong>${a.tipo}</strong> — ${a.detalle}<br><span style="color:#999">${a.accion}</span></div></div>`).join('');
}

async function obtenerSugerencias(){
  document.getElementById('sugerencias').innerHTML='<p class="loading">Analizando...</p>';
  const r=await fetch('/api/sugerencias');
  const d=await r.json();
  if(d.error){document.getElementById('sugerencias').innerHTML=`<p class="loading">${d.error}</p>`;return;}
  const col={alto:'tag-alto',medio:'tag-medio',bajo:'tag-bajo'};
  let h=`<p style="font-size:11px;color:#666;margin-bottom:10px;line-height:1.6">${d.resumen}</p>`;
  (d.sugerencias||[]).forEach(s=>{h+=`<div class="sug-item"><p class="sug-title">${s.titulo}</p><p class="sug-desc">${s.descripcion}</p><div style="display:flex;gap:5px"><span class="tag ${col[s.impacto]||'tag-bajo'}">impacto ${s.impacto}</span><span class="tag ${col[s.esfuerzo]||'tag-bajo'}">esfuerzo ${s.esfuerzo}</span></div></div>`;});
  document.getElementById('sugerencias').innerHTML=h;
}

async function analizarPromociones(){
  document.getElementById('promociones').innerHTML='<p class="loading">Analizando productos...</p>';
  const r=await fetch('/api/promociones/resumen');
  const d=await r.json();
  const el=document.getElementById('promociones');
  if(!d.detalle_activas?.length){el.innerHTML='<p class="loading">Sin promociones activas.</p>';return;}
  el.innerHTML=d.detalle_activas.map(p=>`<div class="promo-row"><span class="badge-off">-${p.descuento_pct}%</span><span style="font-size:12px;color:#1a1a1a;flex:1">${p.item_id}</span><span style="font-size:10px;color:#999">vence en ${p.vence_en}</span></div>`).join('');
}

async function procesarPreguntas(){document.getElementById('actividad').innerHTML='<p class="loading">Procesando...</p>';await fetch('/api/procesar-preguntas',{method:'POST'});setTimeout(()=>{cargarMetricas();cargarActividad();},3000);}
async function cicloCompleto(){await fetch('/api/ciclo',{method:'POST'});setTimeout(()=>{cargarMetricas();cargarActividad();},5000);}
async function mejorarCalidad(){
  const btn = document.getElementById('btn-mejorar-calidad');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Iniciando...'; }

  const panel = document.getElementById('modal-mejora');
  panel.style.display = 'block';
  document.getElementById('mejora-barra').style.width = '0%';
  document.getElementById('mejora-barra').style.background = '#185FA5';
  document.getElementById('mejora-txt').textContent = 'Iniciando...';
  document.getElementById('mejora-producto').textContent = '';
  document.getElementById('mejora-resultado').textContent = '';
  document.getElementById('btn-descargar-reporte').style.display = 'none';
  document.getElementById('btn-ver-historial').style.display = 'none';

  try {
    const resp = await fetch('/api/mejorar-calidad', {method:'POST'});
    const d = await resp.json();
    if (!d.ok) {
      document.getElementById('mejora-txt').textContent = 'Error: ' + (d.error || 'desconocido');
      if (btn) { btn.disabled = false; btn.textContent = '✨ Mejorar calidad publicaciones'; }
      return;
    }
  } catch(e) {
    document.getElementById('mejora-txt').textContent = 'Error de conexión';
    if (btn) { btn.disabled = false; btn.textContent = '✨ Mejorar calidad publicaciones'; }
    return;
  }

  const iv = setInterval(async () => {
    try {
      const r = await fetch('/api/progreso-mejora');
      const p = await r.json();
      const pct = p.total > 0 ? Math.round(p.actual / p.total * 100) : 0;
      document.getElementById('mejora-barra').style.width = pct + '%';
      document.getElementById('mejora-txt').textContent = `${p.actual}/${p.total} revisadas — ${p.mejorados} mejoradas`;
      document.getElementById('mejora-producto').textContent = p.producto_actual || '';
      if (!p.corriendo && p.actual >= p.total && p.total > 0) {
        clearInterval(iv);
        document.getElementById('mejora-barra').style.background = '#3B6D11';
        document.getElementById('mejora-resultado').textContent = `✅ ${p.mejorados} mejoradas a 75%+`;
        document.getElementById('btn-descargar-reporte').style.display = 'block';
        document.getElementById('btn-ver-historial').style.display = 'block';
        if (btn) { btn.disabled = false; btn.textContent = '✨ Mejorar calidad publicaciones'; }
      }
    } catch(e) {}
  }, 2000);
}

function cerrarModalMejora() {
  document.getElementById('modal-mejora').style.display = 'none';
}

let historialTodos = [];

async function verHistorial() {
  document.getElementById('modal-historial').style.display = 'flex';
  document.getElementById('historial-lista').innerHTML = '<p style="font-size:12px;color:#999">Cargando...</p>';
  const r = await fetch('/api/historial-reportes');
  historialTodos = await r.json();
  renderHistorial(historialTodos);
}

function renderHistorial(lista) {
  const el = document.getElementById('historial-lista');
  if (!lista.length) {
    el.innerHTML = '<p style="font-size:12px;color:#999;text-align:center;padding:20px 0">No hay reportes para el período seleccionado.</p>';
    return;
  }
  el.innerHTML = lista.map(rep => `
    <div style="display:flex;align-items:center;justify-content:space-between;padding:10px 0;border-bottom:0.5px solid #f0ede8">
      <div>
        <p style="font-size:12px;font-weight:500;color:#1a1a1a">${rep.fecha}</p>
        <p style="font-size:11px;color:#666">${rep.total} revisadas · <strong style="color:#3B6D11">${rep.mejorados} mejoradas</strong></p>
      </div>
      <a href="/api/reporte-calidad-pdf/${rep.id}" target="_blank"
         style="background:#1a1a1a;color:#fff;padding:6px 14px;border-radius:8px;font-size:11px;font-weight:500;text-decoration:none;flex-shrink:0">
        📄 PDF
      </a>
    </div>`).join('');
}

function filtrarHistorial() {
  const desde = document.getElementById('hist-fecha-desde').value;
  const hasta = document.getElementById('hist-fecha-hasta').value;
  let filtrados = historialTodos;
  if (desde || hasta) {
    filtrados = historialTodos.filter(rep => {
      // El id tiene formato reporte_YYYYMMDD_HHMMSS
      const partes = rep.id.split('_');
      if (partes.length < 2) return true;
      const fechaRep = partes[1]; // YYYYMMDD
      if (desde && fechaRep < desde.replace(/-/g, '')) return false;
      if (hasta && fechaRep > hasta.replace(/-/g, '')) return false;
      return true;
    });
  }
  renderHistorial(filtrados);
}

function limpiarFiltros() {
  document.getElementById('hist-fecha-desde').value = '';
  document.getElementById('hist-fecha-hasta').value = '';
  renderHistorial(historialTodos);
}

function cerrarHistorial() {
  document.getElementById('modal-historial').style.display = 'none';
}

// ===== REPORTE DE PUBLICACIONES =====
let reportePubDatos = [];
let promoItemActual = null;
let promoOpcionActual = null;
let stockItemActual = null;

async function toggleReportePub() {
  const panel = document.getElementById('panel-reporte-pub');
  if (panel.style.display === 'none') {
    panel.style.display = 'block';
    panel.scrollIntoView({behavior:'smooth'});
    await cargarReportePub();
  } else {
    panel.style.display = 'none';
  }
}

async function cargarReportePub() {
  document.getElementById('reporte-pub-loading').style.display = 'block';
  document.getElementById('reporte-pub-contenido').style.display = 'none';
  const r = await fetch('/api/reporte-publicaciones');
  const d = await r.json();
  if (!d.ok) { document.getElementById('reporte-pub-loading').innerHTML = `<p style="color:#A32D2D">Error: ${d.error}</p>`; return; }
  reportePubDatos = d.publicaciones;
  document.getElementById('reporte-pub-loading').style.display = 'none';
  document.getElementById('reporte-pub-contenido').style.display = 'block';

  // Alertas stock
  const stockBajos = d.publicaciones.filter(p => p.stock <= 2 && p.stock > 0);
  if (stockBajos.length > 0) {
    document.getElementById('alerta-stock-banner').style.display = 'block';
    document.getElementById('lista-stock-bajo').innerHTML = stockBajos.map(p => `
      <div style="display:flex;align-items:center;justify-content:space-between;padding:6px 0;border-bottom:0.5px solid #F5AAAA">
        <div>
          <p style="font-size:12px;font-weight:500">${p.titulo}</p>
          <p style="font-size:11px;color:#A32D2D">⚠️ Solo quedan <strong>${p.stock} unidades</strong></p>
        </div>
        <button onclick="abrirModalStock('${p.item_id}','${p.titulo.replace(/'/g,"\\'")}',${p.stock})"
          style="background:#185FA5;color:#fff;border:none;padding:5px 10px;border-radius:6px;font-size:11px;cursor:pointer;font-family:'Inter',sans-serif;flex-shrink:0">
          📦 Reponer
        </button>
      </div>`).join('');
  }

  renderTablaPublicaciones(d.publicaciones);
}

function renderTablaPublicaciones(pubs) {
  const el = document.getElementById('tabla-publicaciones');
  if (!pubs.length) { el.innerHTML = '<p style="font-size:12px;color:#999;text-align:center;padding:20px">No hay publicaciones activas.</p>'; return; }

  const colBg = {verde:'#EAF3DE', amarillo:'#FAEEDA', rojo:'#FCEBEB', gris:'#F7F6F3'};
  const colTxt = {verde:'#3B6D11', amarillo:'#854F0B', rojo:'#A32D2D', gris:'#999'};

  el.innerHTML = pubs.map(p => {
    const d = p.desglose || {};
    const tieneCosto = p.costo > 0 && d.costo_droppers;
    const precio = p.precio || 0;

    // Desglose detallado
    let desgloseHtml = '';
    if (tieneCosto) {
      const envio = d.costo_envio || 0;
      const subtotalGastos = (d.costo_droppers||0) + (d.comision_ml||0) + (d.iva_iibb||0) + envio;
      const ganancia = precio - subtotalGastos;
      desgloseHtml = `
      <div style="background:#F7F6F3;border-radius:8px;padding:10px 14px;margin-bottom:10px;font-size:11px">
        <p style="font-weight:600;color:#1a1a1a;margin-bottom:8px;font-size:12px">💰 Precio de venta: $${precio.toLocaleString('es-AR')}</p>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px 16px;margin-bottom:8px">
          <div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:0.5px solid #e5e3de">
            <span style="color:#666">🏭 Costo Droppers</span>
            <span><strong>$${(d.costo_droppers||0).toLocaleString('es-AR')}</strong> <span style="color:#999">(${d.costo_droppers_pct||0}%)</span></span>
          </div>
          <div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:0.5px solid #e5e3de">
            <span style="color:#666">📋 Comisión ML</span>
            <span><strong>$${(d.comision_ml||0).toLocaleString('es-AR')}</strong> <span style="color:#999">(${d.comision_ml_pct||0}%)</span></span>
          </div>
          <div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:0.5px solid #e5e3de">
            <span style="color:#666">🏛️ IVA + IIBB</span>
            <span><strong>$${(d.iva_iibb||0).toLocaleString('es-AR')}</strong> <span style="color:#999">(${d.iva_iibb_pct||0}%)</span></span>
          </div>
          ${envio > 0 ? `<div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:0.5px solid #e5e3de">
            <span style="color:#666">🚚 Envío gratis</span>
            <span><strong>$${envio.toLocaleString('es-AR')}</strong></span>
          </div>` : ''}
        </div>
        <div style="display:flex;justify-content:space-between;padding:4px 0;border-top:1px solid #e5e3de;margin-top:4px">
          <span style="color:#666;font-weight:500">Subtotal gastos</span>
          <span style="font-weight:600;color:#A32D2D">− $${subtotalGastos.toLocaleString('es-AR')}</span>
        </div>
        <div style="display:flex;justify-content:space-between;padding:6px 0;border-top:2px solid #1a1a1a;margin-top:4px">
          <span style="font-weight:700;font-size:12px">GANANCIA NETA</span>
          <span style="font-weight:700;font-size:13px;color:${ganancia>0?'#3B6D11':'#A32D2D'}">$${ganancia.toLocaleString('es-AR')} <span style="font-size:11px">(${d.margen_pct||0}%)</span></span>
        </div>
      </div>`;
    } else {
      desgloseHtml = `<div style="background:#F7F6F3;border-radius:8px;padding:8px 12px;margin-bottom:10px;font-size:11px;color:#999">
        💰 Precio: <strong style="color:#1a1a1a">$${precio.toLocaleString('es-AR')}</strong> · Sin costo de Droppers cargado
      </div>`;
    }

    return `
    <div style="background:white;border:0.5px solid #e5e3de;border-radius:10px;padding:14px;margin-bottom:10px">
      <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:10px">
        <div style="flex:1;min-width:0">
          <a href="${p.permalink}" target="_blank" style="font-size:12px;font-weight:600;color:#1a1a1a;text-decoration:none">${p.titulo}</a>
          <p style="font-size:11px;color:#666;margin-top:2px">${p.item_id} · ${p.listing_type}</p>
        </div>
        <div style="display:flex;gap:6px;flex-shrink:0;flex-wrap:wrap;justify-content:flex-end">
          <span style="background:${colBg[p.calidad_color]};color:${colTxt[p.calidad_color]};padding:3px 8px;border-radius:6px;font-size:11px;font-weight:600">${p.calidad_label}</span>
          <span style="background:${p.stock<=2?'#FCEBEB':'#F7F6F3'};color:${p.stock<=2?'#A32D2D':'#666'};padding:3px 8px;border-radius:6px;font-size:11px;font-weight:600">📦 ${p.stock} u.</span>
          ${p.promo_activa ? '<span style="background:#EAF3DE;color:#3B6D11;padding:3px 8px;border-radius:6px;font-size:11px;font-weight:600">🏷️ En oferta</span>' : ''}
        </div>
      </div>

      ${desgloseHtml}

      <div style="display:flex;gap:6px;flex-wrap:wrap">
        ${p.calidad_score < 75 ? `<button onclick="mejorarPublicacionIndividual('${p.item_id}', this)"
          style="background:#185FA5;color:#fff;border:none;padding:5px 12px;border-radius:6px;font-size:11px;font-weight:500;cursor:pointer;font-family:'Inter',sans-serif">
          ✨ Mejorar calidad
        </button>` : '<span style="font-size:11px;color:#3B6D11;padding:5px 0">✅ Calidad OK</span>'}
        ${!p.promo_activa ? `<button onclick="abrirModalPromo('${p.item_id}','${p.titulo.replace(/'/g,"\\'")}',${p.precio})"
          style="background:#639922;color:#fff;border:none;padding:5px 12px;border-radius:6px;font-size:11px;font-weight:500;cursor:pointer;font-family:'Inter',sans-serif">
          🏷️ Generar promoción
        </button>` : ''}
        <button onclick="verEstrategiaIA('${p.item_id}', this)"
          style="background:#854F0B;color:#fff;border:none;padding:5px 12px;border-radius:6px;font-size:11px;font-weight:500;cursor:pointer;font-family:'Inter',sans-serif">
          🧠 Estrategia IA
        </button>
        <button onclick="abrirModalStock('${p.item_id}','${p.titulo.replace(/'/g,"\\'")}',${p.stock})"
          style="background:#F7F6F3;border:0.5px solid #e5e3de;color:#666;padding:5px 12px;border-radius:6px;font-size:11px;font-weight:500;cursor:pointer;font-family:'Inter',sans-serif">
          📦 Actualizar stock
        </button>
      </div>
      <div id="estrategia-${p.item_id}" style="display:none;margin-top:10px"></div>
    </div>`;
  }).join('');
}

async function verEstrategiaIA(itemId, btn) {
  const panel = document.getElementById(`estrategia-${itemId}`);
  if (panel.style.display === 'block') {
    panel.style.display = 'none';
    btn.textContent = '🧠 Estrategia IA';
    return;
  }
  btn.textContent = '⏳ Analizando...';
  btn.disabled = true;
  panel.style.display = 'block';
  panel.innerHTML = '<p style="font-size:11px;color:#999;padding:8px 0">Analizando mercado y competencia...</p>';

  try {
    const r = await fetch(`/api/estrategia-marketing/${itemId}`);
    const d = await r.json();
    btn.textContent = '🧠 Estrategia IA';
    btn.disabled = false;

    if (!d.ok) { panel.innerHTML = `<p style="color:#A32D2D;font-size:11px">${d.error}</p>`; return; }

    const e = d.estrategia;
    const urgColores = {alta:'#FCEBEB', media:'#FAEEDA', baja:'#EAF3DE'};
    const urgTextos = {alta:'#A32D2D', media:'#854F0B', baja:'#3B6D11'};

    panel.innerHTML = `
      <div style="background:#F7F6F3;border-radius:8px;padding:14px;border:0.5px solid #e5e3de">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
          <p style="font-size:12px;font-weight:600;color:#1a1a1a">🧠 Estrategia de marketing — Hoy</p>
          <span style="background:${urgColores[e.urgencia]};color:${urgTextos[e.urgencia]};padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600">
            Urgencia: ${e.urgencia}
          </span>
        </div>

        <p style="font-size:11px;color:#666;margin-bottom:10px;line-height:1.5">${e.situacion}</p>

        <div style="background:white;border-radius:6px;padding:10px 12px;margin-bottom:10px;border:0.5px solid #e5e3de">
          <p style="font-size:11px;font-weight:600;color:#185FA5;margin-bottom:4px">📌 Recomendación principal</p>
          <p style="font-size:12px;color:#1a1a1a">${e.recomendacion_principal}</p>
        </div>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px">
          <div style="background:white;border-radius:6px;padding:8px 10px;border:0.5px solid #e5e3de">
            <p style="font-size:10px;color:#999;margin-bottom:2px">Precio sugerido</p>
            <p style="font-size:14px;font-weight:700;color:#3B6D11">$${e.precio_sugerido?.toLocaleString('es-AR')}</p>
            <p style="font-size:10px;color:#666">${e.precio_sugerido_razon}</p>
          </div>
          <div style="background:white;border-radius:6px;padding:8px 10px;border:0.5px solid #e5e3de">
            <p style="font-size:10px;color:#999;margin-bottom:2px">Herramienta recomendada</p>
            <p style="font-size:12px;font-weight:600;color:#1a1a1a">${e.herramienta_recomendada}</p>
            <p style="font-size:10px;color:#666">${e.herramienta_razon}</p>
          </div>
        </div>

        ${d.competidores?.length > 0 ? `
        <div style="margin-bottom:10px">
          <p style="font-size:11px;font-weight:600;color:#1a1a1a;margin-bottom:6px">📊 Competencia analizada</p>
          <div style="display:flex;gap:6px;overflow-x:auto;padding-bottom:4px">
            ${d.competidores.slice(0,4).map(c => `
              <div style="flex-shrink:0;background:white;border:0.5px solid #e5e3de;border-radius:6px;padding:6px 10px;min-width:120px">
                <p style="font-size:10px;color:#1a1a1a;margin-bottom:3px;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical">${c.titulo}</p>
                <p style="font-size:12px;font-weight:600;color:#185FA5">$${c.precio?.toLocaleString('es-AR')}</p>
                <p style="font-size:10px;color:${c.envio_gratis?'#3B6D11':'#999'}">${c.envio_gratis?'✅ Envío gratis':'Sin envío'}</p>
              </div>`).join('')}
          </div>
        </div>` : ''}

        <div style="margin-bottom:10px">
          <p style="font-size:11px;font-weight:600;color:#1a1a1a;margin-bottom:6px">✅ Acciones recomendadas</p>
          ${(e.acciones_adicionales||[]).map(a => `<p style="font-size:11px;color:#666;padding:3px 0;border-bottom:0.5px solid #f0ede8">→ ${a}</p>`).join('')}
        </div>

        <div style="display:flex;justify-content:space-between;align-items:center">
          <p style="font-size:11px;color:#666">📈 Potencial: <strong>${e.potencial_ventas}</strong></p>
          ${e.descuento_sugerido_pct > 0 ? `
          <button onclick="abrirModalPromoConDescuento('${itemId}', ${e.descuento_sugerido_pct})"
            style="background:#639922;color:#fff;border:none;padding:5px 12px;border-radius:6px;font-size:11px;font-weight:500;cursor:pointer;font-family:'Inter',sans-serif">
            🏷️ Aplicar descuento sugerido (${e.descuento_sugerido_pct}%)
          </button>` : ''}
        </div>
      </div>`;
  } catch(e) {
    panel.innerHTML = '<p style="color:#A32D2D;font-size:11px">Error al analizar</p>';
    btn.textContent = '🧠 Estrategia IA';
    btn.disabled = false;
  }
}

async function abrirModalPromoConDescuento(itemId, pct) {
  // Abre el modal de promo con el descuento sugerido preseleccionado
  const item = reportePubDatos.find(p => p.item_id === itemId);
  if (!item) return;
  await abrirModalPromo(itemId, item.titulo, item.precio);
}
  btn.textContent = '⏳ Mejorando...';
  btn.disabled = true;
  btn.style.opacity = '.6';
  try {
    const r = await fetch('/api/mejorar-publicacion-individual', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({item_id: itemId})
    });
    const d = await r.json();
    if (d.ok) {
      btn.textContent = `✅ Mejorado (${d.score_estimado}% est.)`;
      btn.style.background = '#3B6D11';
      setTimeout(() => cargarReportePub(), 3000);
    } else {
      btn.textContent = '❌ Error';
      btn.style.background = '#A32D2D';
      btn.disabled = false;
      btn.style.opacity = '1';
    }
  } catch(e) {
    btn.textContent = '❌ Error';
    btn.disabled = false;
    btn.style.opacity = '1';
  }
}
  document.querySelectorAll('[id^="fil-"]').forEach(b => {
    b.style.background = ''; b.style.color = '';
  });
  document.getElementById('fil-' + filtro)?.style && (document.getElementById('fil-' + filtro).style.background = '#1a1a1a', document.getElementById('fil-' + filtro).style.color = 'white');

  let filtrados = reportePubDatos;
  if (filtro === 'rojo') filtrados = reportePubDatos.filter(p => p.calidad_color === 'rojo');
  else if (filtro === 'amarillo') filtrados = reportePubDatos.filter(p => p.calidad_color === 'amarillo');
  else if (filtro === 'verde') filtrados = reportePubDatos.filter(p => p.calidad_color === 'verde');
  else if (filtro === 'sin_promo') filtrados = reportePubDatos.filter(p => !p.promo_activa);
  renderTablaPublicaciones(filtrados);
}

// Modal Promoción
async function abrirModalPromo(itemId, titulo, precio) {
  promoItemActual = itemId;
  promoOpcionActual = null;
  document.getElementById('modal-promo-titulo').textContent = titulo.substring(0, 50);
  document.getElementById('modal-promo-precio').textContent = '$' + precio.toLocaleString('es-AR');
  document.getElementById('modal-promo-opciones').innerHTML = '<p style="font-size:12px;color:#999">Cargando opciones...</p>';
  document.getElementById('modal-promo-confirmacion').style.display = 'none';
  document.getElementById('btn-confirmar-promo').disabled = true;
  document.getElementById('btn-confirmar-promo').style.opacity = '.4';
  document.getElementById('modal-promo').style.display = 'flex';

  const r = await fetch(`/api/opciones-promocion/${itemId}`);
  const d = await r.json();
  if (!d.ok) { document.getElementById('modal-promo-opciones').innerHTML = `<p style="color:#A32D2D">${d.error}</p>`; return; }

  document.getElementById('modal-promo-opciones').innerHTML = d.opciones.map((op, i) => `
    <div onclick="seleccionarPromo(${i}, ${JSON.stringify(op).replace(/"/g,"&quot;")})"
      id="promo-op-${i}"
      style="border:0.5px solid #e5e3de;border-radius:8px;padding:12px;cursor:pointer;transition:.2s;margin-bottom:6px">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px">
        <p style="font-size:12px;font-weight:600;color:#1a1a1a">${op.label}</p>
        <div style="text-align:right;flex-shrink:0;margin-left:10px">
          <p style="font-size:13px;font-weight:700;color:#3B6D11">$${op.precio_nuevo.toLocaleString('es-AR')}</p>
          <p style="font-size:10px;color:#A32D2D">−${op.descuento_pct}% de descuento</p>
        </div>
      </div>
      <p style="font-size:11px;color:#666;margin-bottom:6px">${op.descripcion}</p>
      <div style="display:flex;gap:10px;font-size:10px;flex-wrap:wrap">
        <span style="color:#666">Precio actual: <strong>$${op.precio_actual.toLocaleString('es-AR')}</strong></span>
        <span style="color:#666">Precio nuevo: <strong style="color:#3B6D11">$${op.precio_nuevo.toLocaleString('es-AR')}</strong></span>
        ${op.meli_aporta_pct > 0 ? `<span style="background:#E6F1FB;color:#185FA5;padding:1px 6px;border-radius:4px">ML aporta ${op.meli_aporta_pct}%</span>` : ''}
        ${op.seller_aporta_pct > 0 ? `<span style="background:#FAEEDA;color:#854F0B;padding:1px 6px;border-radius:4px">Vos aportás ${op.seller_aporta_pct}%</span>` : ''}
        ${op.status === 'candidate' ? '<span style="background:#EAF3DE;color:#3B6D11;padding:1px 6px;border-radius:4px">✅ Disponible en ML</span>' : ''}
        ${op.status === 'manual' ? '<span style="background:#F7F6F3;color:#999;padding:1px 6px;border-radius:4px">Descuento manual</span>' : ''}
      </div>
    </div>`).join('');
}

function seleccionarPromo(idx, opcionJson) {
  let opcion;
  if (typeof opcionJson === 'string') {
    try { opcion = JSON.parse(opcionJson.replace(/&quot;/g, '"')); } catch(e) { return; }
  } else {
    opcion = opcionJson;
  }
  promoOpcionActual = opcion;
  document.querySelectorAll('[id^="promo-op-"]').forEach(el => {
    el.style.background = ''; el.style.borderColor = '#e5e3de';
  });
  const sel = document.getElementById(`promo-op-${idx}`);
  sel.style.background = '#EAF3DE'; sel.style.borderColor = '#639922';
  document.getElementById('modal-promo-confirmacion').style.display = 'block';
  document.getElementById('modal-promo-confirmacion').textContent = `✅ Se cambiará el precio a $${opcion.precio_nuevo.toLocaleString('es-AR')} — ${opcion.label}`;
  document.getElementById('btn-confirmar-promo').disabled = false;
  document.getElementById('btn-confirmar-promo').style.opacity = '1';
}

async function confirmarPromo() {
  if (!promoItemActual || !promoOpcionActual) return;
  const btn = document.getElementById('btn-confirmar-promo');
  btn.textContent = 'Aplicando...'; btn.disabled = true;
  const r = await fetch('/api/aplicar-promocion-item', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({item_id: promoItemActual, precio_nuevo: promoOpcionActual.precio_nuevo})
  });
  const d = await r.json();
  if (d.ok) {
    cerrarModalPromo();
    await cargarReportePub();
  } else {
    document.getElementById('modal-promo-confirmacion').textContent = `❌ Error: ${d.error}`;
    document.getElementById('modal-promo-confirmacion').style.color = '#A32D2D';
    btn.textContent = 'Aplicar promoción'; btn.disabled = false;
  }
}

function cerrarModalPromo() { document.getElementById('modal-promo').style.display = 'none'; }

// Modal Stock
function abrirModalStock(itemId, titulo, stockActual) {
  stockItemActual = itemId;
  document.getElementById('modal-stock-titulo').textContent = titulo.substring(0, 60);
  document.getElementById('modal-stock-valor').value = stockActual;
  document.getElementById('modal-stock').style.display = 'flex';
}

function cambiarStock(delta) {
  const input = document.getElementById('modal-stock-valor');
  input.value = Math.max(1, parseInt(input.value || 0) + delta);
}

async function guardarStock() {
  if (!stockItemActual) return;
  const stock = parseInt(document.getElementById('modal-stock-valor').value);
  const r = await fetch(`/api/actualizar-stock/${stockItemActual}`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({stock})
  });
  const d = await r.json();
  if (d.ok) {
    cerrarModalStock();
    await cargarReportePub();
  } else {
    alert('Error: ' + d.error);
  }
}

function cerrarModalStock() { document.getElementById('modal-stock').style.display = 'none'; }
async function verificarToken() {
  try {
    const r = await fetch('/api/estado-token');
    const d = await r.json();
    const el = document.getElementById('token-estado');
    if (!el) return;
    if (d.estado === 'expirado' || d.expira_en_horas <= 0) {
      el.textContent = '⚠️ Token expirado';
      el.style.background = '#FCEBEB'; el.style.color = '#A32D2D'; el.style.borderColor = '#F5AAAA';
    } else if (d.expira_en_horas <= 1) {
      el.textContent = `⏰ Expira en ${d.expira_en_horas}h`;
      el.style.background = '#FAEEDA'; el.style.color = '#854F0B'; el.style.borderColor = '#FAC775';
    } else {
      el.textContent = `🔑 Token OK`;
      el.style.background = '#EAF3DE'; el.style.color = '#3B6D11'; el.style.borderColor = '#C0DD97';
    }
  } catch(e) {}
}

function verEstadoToken() { document.getElementById('modal-token').style.display='flex'; }
function cerrarModalToken() { document.getElementById('modal-token').style.display='none'; }

async function actualizarTokenManual() {
  const code = document.getElementById('token-code-input').value.trim();
  if (!code) { alert('Pegá el código TG-...'); return; }
  const btn = document.getElementById('btn-actualizar-token');
  btn.textContent = 'Procesando...'; btn.disabled = true;
  try {
    const r = await fetch('/api/intercambiar-codigo', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({code})});
    const d = await r.json();
    if (d.ok) {
      document.getElementById('token-result').innerHTML = '<span style="color:#3B6D11">✅ Token actualizado</span>';
      setTimeout(() => { cerrarModalToken(); verificarToken(); }, 2000);
    } else {
      document.getElementById('token-result').innerHTML = `<span style="color:#A32D2D">❌ ${d.error}</span>`;
    }
  } catch(e) { document.getElementById('token-result').innerHTML = '<span style="color:#A32D2D">❌ Error</span>'; }
  btn.textContent = 'Actualizar token'; btn.disabled = false;
}

cargarMetricas();cargarActividad();cargarPendientes();verificarToken();
setInterval(()=>{cargarMetricas();cargarActividad();cargarPendientes();},30000);
setInterval(verificarToken, 300000);
</script>

<!-- Modal historial reportes -->
<div id="modal-historial" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:300;align-items:center;justify-content:center">
  <div style="background:white;border-radius:12px;padding:24px;width:560px;max-width:90vw;max-height:85vh;display:flex;flex-direction:column">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px">
      <p style="font-size:14px;font-weight:600;color:#1a1a1a">📋 Historial de reportes de calidad</p>
      <button onclick="cerrarHistorial()" style="background:none;border:none;color:#999;font-size:18px;cursor:pointer">✕</button>
    </div>
    <div style="display:flex;gap:8px;margin-bottom:12px">
      <input type="date" id="hist-fecha-desde" onchange="filtrarHistorial()"
        style="flex:1;background:#F7F6F3;border:0.5px solid #e5e3de;border-radius:8px;padding:7px 10px;font-size:12px;font-family:'Inter',sans-serif;color:#1a1a1a">
      <input type="date" id="hist-fecha-hasta" onchange="filtrarHistorial()"
        style="flex:1;background:#F7F6F3;border:0.5px solid #e5e3de;border-radius:8px;padding:7px 10px;font-size:12px;font-family:'Inter',sans-serif;color:#1a1a1a">
      <button onclick="limpiarFiltros()" class="mini-btn">Limpiar</button>
    </div>
    <div id="historial-lista" style="overflow-y:auto;flex:1"><p style="font-size:12px;color:#999">Cargando...</p></div>
  </div>
</div>

<!-- Panel lateral mejora calidad -->
<div id="modal-mejora" style="display:none;position:fixed;bottom:24px;right:24px;width:380px;background:white;border-radius:12px;padding:20px;z-index:200;box-shadow:0 8px 32px rgba(0,0,0,.15);border:0.5px solid #e5e3de">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px">
    <p style="font-size:13px;font-weight:600;color:#1a1a1a">✨ Mejorando calidad</p>
    <button onclick="cerrarModalMejora()" style="background:none;border:none;color:#999;font-size:16px;cursor:pointer;padding:0;line-height:1">✕</button>
  </div>
  <div style="height:6px;background:#e5e3de;border-radius:3px;overflow:hidden;margin-bottom:8px">
    <div id="mejora-barra" style="height:100%;background:#185FA5;border-radius:3px;transition:width .5s;width:0%"></div>
  </div>
  <p id="mejora-txt" style="font-size:11px;color:#666;margin-bottom:4px">Iniciando...</p>
  <p id="mejora-producto" style="font-size:11px;color:#185FA5;font-weight:500;margin-bottom:8px;min-height:16px;line-height:1.4"></p>
  <p id="mejora-resultado" style="font-size:12px;font-weight:600;color:#3B6D11;min-height:18px"></p>
  <div style="display:flex;gap:8px;margin-top:12px">
    <button onclick="cerrarModalMejora()" style="flex:1;background:#F7F6F3;border:0.5px solid #e5e3de;color:#666;padding:7px;border-radius:8px;font-size:11px;cursor:pointer;font-family:'Inter',sans-serif">Minimizar</button>
    <a id="btn-descargar-reporte" href="/api/reporte-calidad-pdf" target="_blank" style="flex:1;background:#1a1a1a;color:#fff;padding:7px;border-radius:8px;font-size:11px;font-weight:500;cursor:pointer;font-family:'Inter',sans-serif;text-align:center;text-decoration:none;display:none">📄 Descargar PDF</a>
    <button onclick="verHistorial()" style="flex:1;background:#185FA5;color:#fff;border:none;padding:7px;border-radius:8px;font-size:11px;font-weight:500;cursor:pointer;font-family:'Inter',sans-serif;display:none" id="btn-ver-historial">📋 Historial</button>
  </div>
</div>

<!-- Modal token -->
<div id="modal-token" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:200;align-items:center;justify-content:center">
  <div style="background:white;border-radius:12px;padding:24px;width:460px;max-width:90vw">
    <p style="font-size:14px;font-weight:600;margin-bottom:8px">🔑 Actualizar token de Mercado Libre</p>
    <p style="font-size:12px;color:#666;margin-bottom:12px">El token expira cada 6 horas. Para renovarlo:</p>
    <ol style="font-size:12px;color:#666;margin-bottom:12px;padding-left:16px;line-height:1.8">
      <li>Abrí este link: <a href="https://auth.mercadolibre.com.ar/authorization?response_type=code&client_id=7554500472334410&redirect_uri=https://httpbin.org/get" target="_blank" style="color:#185FA5">Autorizar app ML</a></li>
      <li>Iniciá sesión con tu cuenta</li>
      <li>Copiá el código <strong>TG-...</strong> de la URL</li>
      <li>Pegalo acá abajo</li>
    </ol>
    <input type="text" id="token-code-input" placeholder="TG-xxxxxxxxxxxxxxxx-211711561" style="width:100%;background:#F7F6F3;border:0.5px solid #e5e3de;border-radius:8px;padding:9px 12px;color:#1a1a1a;font-size:12px;font-family:'Inter',sans-serif;margin-bottom:8px;box-sizing:border-box">
    <div id="token-result" style="min-height:20px;margin-bottom:12px;font-size:12px"></div>
    <div style="display:flex;gap:8px">
      <button onclick="cerrarModalToken()" style="flex:1;background:#F7F6F3;border:0.5px solid #e5e3de;color:#666;padding:9px;border-radius:8px;font-size:12px;cursor:pointer;font-family:'Inter',sans-serif">Cancelar</button>
      <button id="btn-actualizar-token" onclick="actualizarTokenManual()" style="flex:2;background:#1a1a1a;color:#fff;border:none;padding:9px;border-radius:8px;font-size:12px;font-weight:500;cursor:pointer;font-family:'Inter',sans-serif">Actualizar token</button>
    </div>
  </div>
</div>
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


@app.route("/api/precio-ml")
def api_precio_ml():
    try:
        titulo = request.args.get("titulo", "")
        categoria_nombre = request.args.get("categoria", "")
        from publicador import CATEGORIAS_ML
        cat_id = CATEGORIAS_ML.get(categoria_nombre, "")
        resultados = sistema.ml.get("/sites/MLA/search", params={
            "q": titulo[:40],
            "category": cat_id,
            "limit": 10,
            "sort": "relevance",
        })
        precios = [i["price"] for i in resultados.get("results", []) if i.get("price")]
        if not precios:
            return jsonify({"precio_mediano": None})
        precios_sorted = sorted(precios)
        mediana = precios_sorted[len(precios_sorted) // 2]
        return jsonify({
            "precio_mediano": round(mediana, 2),
            "precio_minimo":  round(precios_sorted[0], 2),
            "precio_maximo":  round(precios_sorted[-1], 2),
            "cantidad":       len(precios),
        })
    except Exception as e:
        return jsonify({"precio_mediano": None, "error": str(e)})


@app.route("/api/mis-publicaciones")
def api_mis_publicaciones():
    """Diagnóstico: lista las publicaciones activas del usuario."""
    try:
        user_id = CONFIG.get("ML_USER_ID", "")
        r = sistema.ml.get(f"/users/{user_id}/items/search", params={"status": "active", "limit": 10})
        return jsonify({"user_id": user_id, "resultado": r})
    except Exception as e:
        return jsonify({"error": str(e)})


MEJORA_FILE = "/tmp/ml_mejora_resultados.json"
HISTORIAL_DIR = "/tmp/ml_reportes"

# Crear directorio de historial si no existe
os.makedirs(HISTORIAL_DIR, exist_ok=True)

# Variable global de progreso de mejora
mejora_progreso = {"corriendo": False, "actual": 0, "total": 0, "producto_actual": "", "mejorados": 0, "resultados": []}

def guardar_mejora_progreso():
    try:
        with open(MEJORA_FILE, "w") as f:
            json.dump(mejora_progreso, f)
    except:
        pass

def cargar_mejora_progreso():
    global mejora_progreso
    try:
        if os.path.exists(MEJORA_FILE):
            with open(MEJORA_FILE, "r") as f:
                mejora_progreso = json.load(f)
    except:
        pass

def guardar_reporte_github(datos_reporte):
    """Guarda el reporte en GitHub para persistencia permanente."""
    try:
        token = CONFIG.get("GITHUB_TOKEN", "")
        repo = CONFIG.get("GITHUB_REPO", "dcsworld392-glitch/-ml-bot")
        if not token:
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        nombre = f"reporte_{timestamp}"
        contenido = json.dumps({
            "fecha": datetime.now().isoformat(),
            "fecha_display": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "total": datos_reporte.get("total", 0),
            "mejorados": datos_reporte.get("mejorados", 0),
            "resultados": datos_reporte.get("resultados", []),
            "archivo": nombre,
        }, ensure_ascii=False, indent=2)

        import base64
        contenido_b64 = base64.b64encode(contenido.encode('utf-8')).decode('ascii')

        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
        }
        url = f"https://api.github.com/repos/{repo}/contents/reportes/{nombre}.json"
        payload = {
            "message": f"Reporte calidad {datetime.now().strftime('%d/%m/%Y %H:%M')}",
            "content": contenido_b64,
        }
        r = requests.put(url, headers=headers, json=payload)
        if r.status_code in (200, 201):
            log(f"✅ Reporte guardado en GitHub: {nombre}")
            return nombre
        else:
            log(f"⚠️ Error guardando en GitHub: {r.status_code} {r.text[:200]}")
            return None
    except Exception as e:
        log(f"⚠️ Error GitHub: {e}")
        return None


def listar_reportes_github():
    """Lista los reportes guardados en GitHub."""
    try:
        token = CONFIG.get("GITHUB_TOKEN", "")
        repo = CONFIG.get("GITHUB_REPO", "dcsworld392-glitch/-ml-bot")
        if not token:
            return []

        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }
        url = f"https://api.github.com/repos/{repo}/contents/reportes"
        r = requests.get(url, headers=headers)
        if r.status_code != 200:
            return []

        archivos = r.json()
        reportes = []
        for arch in sorted(archivos, key=lambda x: x["name"], reverse=True):
            if arch["name"].endswith(".json"):
                nombre = arch["name"].replace(".json", "")
                # Extraer fecha del nombre (reporte_YYYYMMDD_HHMMSS)
                partes = nombre.split("_")
                if len(partes) >= 3:
                    fecha_str = partes[1]
                    hora_str = partes[2]
                    try:
                        fecha_display = f"{fecha_str[6:8]}/{fecha_str[4:6]}/{fecha_str[:4]} {hora_str[:2]}:{hora_str[2:4]}"
                    except:
                        fecha_display = nombre
                else:
                    fecha_display = nombre
                reportes.append({
                    "id": nombre,
                    "fecha": fecha_display,
                    "sha": arch.get("sha", ""),
                    "download_url": arch.get("download_url", ""),
                })
        return reportes
    except Exception as e:
        log(f"⚠️ Error listando GitHub: {e}")
        return []


def cargar_reporte_github(nombre):
    """Carga un reporte específico desde GitHub."""
    try:
        token = CONFIG.get("GITHUB_TOKEN", "")
        repo = CONFIG.get("GITHUB_REPO", "dcsworld392-glitch/-ml-bot")
        if not token:
            return None

        import base64
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }
        url = f"https://api.github.com/repos/{repo}/contents/reportes/{nombre}.json"
        r = requests.get(url, headers=headers)
        if r.status_code != 200:
            return None

        data = r.json()
        contenido = base64.b64decode(data["content"]).decode('utf-8')
        return json.loads(contenido)
    except Exception as e:
        log(f"⚠️ Error cargando reporte GitHub: {e}")
        return None

@app.route("/api/mejorar-publicacion-individual", methods=["POST"])
def api_mejorar_publicacion_individual():
    """Mejora la calidad de una publicación individual."""
    try:
        from publicador import PublicadorML
        item_id = request.json.get("item_id")
        if not item_id:
            return jsonify({"ok": False, "error": "item_id requerido"})
        pub = PublicadorML(sistema.ml, CONFIG.get("ANTHROPIC_API_KEY", ""))
        perf = sistema.ml.get(f"/item/{item_id}/performance")
        score = perf.get("score", 100)
        item_data = sistema.ml.get(f"/items/{item_id}")
        health_compat = {
            "overall": {"points": score},
            "sections": [
                {
                    "section_id": b.get("key", ""),
                    "points": b.get("score", 0),
                    "total_points": 100,
                    "tips": [{"tip": v.get("title", "")} for v in b.get("variables", []) if v.get("status") == "PENDING"]
                }
                for b in perf.get("buckets", [])
            ]
        }
        resultado = pub.mejorar_calidad_publicacion(item_id, item_data, health_compat)
        return jsonify(resultado)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/reporte-publicaciones")
def api_reporte_publicaciones():
    """Reporte completo de publicaciones activas con costos, calidad y stock."""
    try:
        user_id = CONFIG.get("ML_USER_ID", "211711561")
        items_data = sistema.ml.get(f"/users/{user_id}/items/search",
                                    params={"status": "active", "limit": 50})
        item_ids = items_data.get("results", [])

        # Cargar productos de Droppers para cruzar costos
        productos_droppers = scraper_estado.get("productos", [])
        costos_map = {}
        for p in productos_droppers:
            titulo = p.get("titulo", "").lower()
            costo = p.get("costo", 0)
            if costo > 0 and titulo:
                costos_map[titulo[:30]] = costo

        from costos import CalculadoraCostos
        calc = CalculadoraCostos()

        reporte = []
        alertas_stock = []

        for item_id in item_ids:
            try:
                item = sistema.ml.get(f"/items/{item_id}")
                titulo = item.get("title", "")
                precio = item.get("price", 0)
                stock = item.get("available_quantity", 0)
                cat_id = item.get("category_id", "")
                listing_type = item.get("listing_type_id", "")

                # Color de calidad
                try:
                    perf = sistema.ml.get(f"/item/{item_id}/performance")
                    score = perf.get("score", 0)
                    level = perf.get("level", "")
                    if score >= 75:
                        calidad_color = "verde"
                        calidad_label = f"{score}% — Buena"
                    elif score >= 50:
                        calidad_color = "amarillo"
                        calidad_label = f"{score}% — Regular"
                    else:
                        calidad_color = "rojo"
                        calidad_label = f"{score}% — Baja"
                except:
                    calidad_color = "gris"
                    calidad_label = "Sin datos"
                    score = 0

                # Costo Droppers (cruzar por título)
                costo = 0
                titulo_lower = titulo.lower()[:30]
                for key, val in costos_map.items():
                    if key[:20] in titulo_lower or titulo_lower[:20] in key:
                        costo = val
                        break

                # Desglose de costos
                desglose = {}
                if costo > 0 and precio > 0:
                    calculo = calc.calcular(precio, costo, "default", False)
                    desglose = {
                        "costo_droppers": costo,
                        "costo_droppers_pct": round(costo / precio * 100, 1),
                        "comision_ml": calculo["comision_ml"],
                        "comision_ml_pct": calculo["tasa_comision_pct"],
                        "iva_iibb": round(calculo["iva_comision"] + calculo["iibb"], 2),
                        "iva_iibb_pct": round((calculo["iva_comision"] + calculo["iibb"]) / precio * 100, 1),
                        "ganancia_neta": calculo["ganancia_neta"],
                        "margen_pct": calculo["margen_neto_pct"],
                    }

                # Promociones activas
                promo_activa = False
                promo_detalle = ""
                try:
                    promos = sistema.ml.get(f"/items/{item_id}/promotions")
                    if promos and isinstance(promos, list) and len(promos) > 0:
                        promo_activa = True
                        promo_detalle = promos[0].get("type", "Promoción activa")
                except:
                    pass

                pub = {
                    "item_id": item_id,
                    "titulo": titulo,
                    "precio": precio,
                    "stock": stock,
                    "listing_type": listing_type,
                    "categoria_id": cat_id,
                    "calidad_score": score,
                    "calidad_color": calidad_color,
                    "calidad_label": calidad_label,
                    "costo": costo,
                    "desglose": desglose,
                    "promo_activa": promo_activa,
                    "promo_detalle": promo_detalle,
                    "permalink": item.get("permalink", ""),
                }
                reporte.append(pub)

                # Alerta de stock bajo
                if 0 < stock <= 2:
                    alertas_stock.append({
                        "item_id": item_id,
                        "titulo": titulo,
                        "stock": stock,
                    })

            except Exception as e:
                log(f"Error en {item_id}: {e}")

        return jsonify({
            "ok": True,
            "publicaciones": reporte,
            "alertas_stock": alertas_stock,
            "total": len(reporte),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/actualizar-stock/<item_id>", methods=["POST"])
def api_actualizar_stock(item_id):
    """Actualiza el stock de una publicación."""
    try:
        datos = request.json
        nuevo_stock = int(datos.get("stock", 10))
        resultado = sistema.ml.put(f"/items/{item_id}", {"available_quantity": nuevo_stock})
        if resultado.get("id"):
            return jsonify({"ok": True, "stock": nuevo_stock})
        return jsonify({"ok": False, "error": resultado.get("message", "Error")})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/opciones-promocion/<item_id>")
def api_opciones_promocion(item_id):
    """Devuelve las opciones de promoción reales de ML para un item."""
    try:
        item = sistema.ml.get(f"/items/{item_id}")
        precio = item.get("price", 0)

        # Consultar promociones disponibles reales de ML
        promos_ml = []
        try:
            r = sistema.ml.get(f"/seller-promotions/items/{item_id}", params={"app_version": "v2"})
            if isinstance(r, list):
                promos_ml = r
            elif isinstance(r, dict) and r.get("results"):
                promos_ml = r["results"]
        except:
            pass

        opciones = []

        # Procesar promociones reales de ML
        tipos_label = {
            "PRICE_DISCOUNT":        "🏷️ Descuento de precio",
            "LIGHTNING":             "⚡ Oferta relámpago",
            "DOD":                   "🌟 Oferta del día",
            "DEAL":                  "🎯 Campaña tradicional ML",
            "SELLER_CAMPAIGN":       "📢 Campaña del vendedor",
            "MARKETPLACE_CAMPAIGN":  "🤝 Campaña co-financiada ML",
            "VOLUME":                "📦 Descuento por volumen",
            "SMART":                 "🤖 Campaña inteligente",
            "PRE_NEGOTIATED":        "💼 Descuento pre-negociado",
        }
        tipos_desc = {
            "PRICE_DISCOUNT":       "ML muestra un tachado del precio original. Aumenta el CTR.",
            "LIGHTNING":            "Aparece destacada por tiempo limitado. Alta visibilidad.",
            "DOD":                  "Destacada en la sección de ofertas del día de ML.",
            "DEAL":                 "Campaña organizada por ML. Máxima visibilidad.",
            "SELLER_CAMPAIGN":      "Campaña propia del vendedor con descuento configurable.",
            "MARKETPLACE_CAMPAIGN": "ML co-financia parte del descuento. Menor costo para vos.",
            "VOLUME":               "Descuento automático al comprar más de X unidades.",
            "SMART":                "ML elige automáticamente el mejor momento para mostrarla.",
            "PRE_NEGOTIATED":       "Descuento fijo pre-negociado con ML.",
        }

        for promo in promos_ml:
            tipo = promo.get("type", "")
            status = promo.get("status", "")
            if status not in ["candidate", "started", "pending", ""]:
                continue

            precio_min = promo.get("min_discounted_price", precio * 0.7)
            precio_sugerido = promo.get("suggested_discounted_price") or promo.get("price")
            precio_nuevo = precio_sugerido or round(precio * 0.9, 2)
            descuento_pct = round((1 - precio_nuevo / precio) * 100, 1) if precio > 0 else 0
            meli_pct = promo.get("benefits", {}).get("meli_percent", 0)
            seller_pct = promo.get("benefits", {}).get("seller_percent", 0)

            opciones.append({
                "tipo":             tipo,
                "label":            tipos_label.get(tipo, f"Promoción {tipo}"),
                "descripcion":      tipos_desc.get(tipo, "Promoción de ML"),
                "precio_actual":    precio,
                "precio_nuevo":     precio_nuevo,
                "precio_minimo":    precio_min,
                "descuento_pct":    descuento_pct,
                "meli_aporta_pct":  meli_pct,
                "seller_aporta_pct": seller_pct,
                "status":           status,
                "promo_id":         promo.get("id", ""),
            })

        # Si ML no devolvió opciones reales, ofrecer descuentos manuales
        if not opciones:
            for pct, label, desc in [
                (5,  "🏷️ Descuento 5%",  "Pequeño descuento para aumentar clics y CTR"),
                (10, "🏷️ Descuento 10%", "Descuento moderado, buen balance ventas/margen"),
                (15, "🏷️ Descuento 15%", "Descuento agresivo para liquidar stock"),
                (3,  "👁️ Precio llamativo", "3% de descuento, aparece como oferta en ML"),
            ]:
                precio_nuevo = round(precio * (1 - pct/100), 2)
                opciones.append({
                    "tipo":            "PRICE_DISCOUNT",
                    "label":           label,
                    "descripcion":     desc,
                    "precio_actual":   precio,
                    "precio_nuevo":    precio_nuevo,
                    "precio_minimo":   precio * 0.5,
                    "descuento_pct":   pct,
                    "meli_aporta_pct": 0,
                    "seller_aporta_pct": pct,
                    "status":          "manual",
                    "promo_id":        "",
                })

        return jsonify({"ok": True, "item_id": item_id, "precio_actual": precio, "opciones": opciones})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/estrategia-marketing/<item_id>")
def api_estrategia_marketing(item_id):
    """Analiza el mercado y genera la mejor estrategia de marketing para el producto."""
    try:
        import anthropic as _ant

        # 1. Datos del item
        item = sistema.ml.get(f"/items/{item_id}")
        titulo = item.get("title", "")
        precio = item.get("price", 0)
        stock = item.get("available_quantity", 0)
        visitas = item.get("visits", 0)
        vendidos = item.get("sold_quantity", 0)
        cat_id = item.get("category_id", "")

        # 2. Performance/calidad
        score = 0
        try:
            perf = sistema.ml.get(f"/item/{item_id}/performance")
            score = perf.get("score", 0)
        except:
            pass

        # 3. Competencia real de ML
        competidores = []
        try:
            r = sistema.ml.get("/sites/MLA/search", params={
                "q": titulo[:40], "category": cat_id, "limit": 8, "sort": "relevance"
            })
            for c in r.get("results", [])[:5]:
                competidores.append({
                    "titulo": c.get("title", "")[:60],
                    "precio": c.get("price", 0),
                    "vendidos": c.get("sold_quantity", 0),
                    "envio_gratis": c.get("shipping", {}).get("free_shipping", False),
                    "reputacion": c.get("seller", {}).get("reputation", {}).get("level_id", ""),
                })
        except:
            pass

        # 4. Promociones disponibles para este item
        promos_disponibles = []
        try:
            r = sistema.ml.get(f"/seller-promotions/items/{item_id}", params={"app_version": "v2"})
            if isinstance(r, list):
                promos_disponibles = [p.get("type") for p in r if p.get("status") in ["candidate", "started"]]
        except:
            pass

        # 5. Análisis con Claude
        comp_txt = "\n".join([
            f"- {c['titulo']}: ${c['precio']:,.0f} ({'envío gratis' if c['envio_gratis'] else 'sin envío'}) — {c['vendidos']} vendidos"
            for c in competidores
        ]) or "Sin datos de competencia"

        precios_comp = [c["precio"] for c in competidores if c["precio"] > 0]
        precio_min_comp = min(precios_comp) if precios_comp else None
        precio_max_comp = max(precios_comp) if precios_comp else None
        precio_mediano_comp = sorted(precios_comp)[len(precios_comp)//2] if precios_comp else None

        prompt = f"""Sos un experto en estrategia de marketing para Mercado Libre Argentina.
Analizá este producto y generá la MEJOR estrategia de marketing para HOY.

PRODUCTO:
- Título: {titulo}
- Precio actual: ${precio:,.0f}
- Stock: {stock} unidades
- Visitas: {visitas}
- Vendidos: {vendidos}
- Calidad publicación: {score}%
- Categoría: {cat_id}

ANÁLISIS DE COMPETENCIA:
{comp_txt}

PRECIOS DE COMPETENCIA:
- Mínimo: ${precio_min_comp:,.0f if precio_min_comp else 'N/A'}
- Mediano: ${precio_mediano_comp:,.0f if precio_mediano_comp else 'N/A'}
- Máximo: ${precio_max_comp:,.0f if precio_max_comp else 'N/A'}

HERRAMIENTAS DISPONIBLES EN ML: {', '.join(promos_disponibles) if promos_disponibles else 'Descuentos manuales'}

Considerando todo esto, generá una estrategia completa. Devolvé SOLO JSON:
{{
  "situacion": "análisis en 2 líneas de la situación actual del producto",
  "recomendacion_principal": "la acción más importante a tomar HOY",
  "precio_sugerido": {precio},
  "precio_sugerido_razon": "por qué este precio",
  "herramienta_recomendada": "PRICE_DISCOUNT|LIGHTNING|ninguna|etc",
  "herramienta_razon": "por qué esta herramienta",
  "descuento_sugerido_pct": 0,
  "acciones_adicionales": ["acción 1", "acción 2", "acción 3"],
  "urgencia": "alta|media|baja",
  "potencial_ventas": "estimación de ventas si se aplica la estrategia"
}}"""

        client = _ant.Anthropic(api_key=CONFIG.get("ANTHROPIC_API_KEY", ""))
        msg = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}]
        )
        texto = msg.content[0].text.strip()
        estrategia = json.loads(texto[texto.find("{"):texto.rfind("}")+1])

        return jsonify({
            "ok": True,
            "item_id": item_id,
            "titulo": titulo,
            "precio_actual": precio,
            "competidores": competidores,
            "precio_min_comp": precio_min_comp,
            "precio_mediano_comp": precio_mediano_comp,
            "estrategia": estrategia,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/aplicar-promocion-item", methods=["POST"])
def api_aplicar_promocion_item():
    """Aplica una promoción (descuento de precio) a un item."""
    try:
        datos = request.json
        item_id = datos.get("item_id")
        precio_nuevo = float(datos.get("precio_nuevo", 0))
        if not item_id or precio_nuevo <= 0:
            return jsonify({"ok": False, "error": "Datos inválidos"})
        resultado = sistema.ml.put(f"/items/{item_id}", {"price": precio_nuevo})
        if resultado.get("id"):
            return jsonify({"ok": True, "precio_nuevo": precio_nuevo})
        return jsonify({"ok": False, "error": resultado.get("message", "Error")})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/alertas-stock")
def api_alertas_stock():
    """Retorna publicaciones con stock bajo (2 o menos unidades)."""
    try:
        user_id = CONFIG.get("ML_USER_ID", "211711561")
        items_data = sistema.ml.get(f"/users/{user_id}/items/search",
                                    params={"status": "active", "limit": 50})
        item_ids = items_data.get("results", [])
        alertas = []
        for item_id in item_ids:
            try:
                item = sistema.ml.get(f"/items/{item_id}")
                stock = item.get("available_quantity", 0)
                if 0 < stock <= 2:
                    alertas.append({
                        "item_id": item_id,
                        "titulo": item.get("title", ""),
                        "stock": stock,
                        "precio": item.get("price", 0),
                    })
            except:
                pass
        return jsonify({"ok": True, "alertas": alertas})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/historial-reportes")
def api_historial_reportes():
    """Lista todos los reportes guardados en GitHub."""
    try:
        reportes = listar_reportes_github()
        # Si GitHub no tiene nada, buscar en /tmp como fallback
        if not reportes and os.path.exists(HISTORIAL_DIR):
            for archivo in sorted(os.listdir(HISTORIAL_DIR), reverse=True):
                if archivo.endswith(".json"):
                    try:
                        with open(os.path.join(HISTORIAL_DIR, archivo)) as f:
                            datos = json.load(f)
                        reportes.append({
                            "id": datos.get("archivo", archivo.replace(".json", "")),
                            "fecha": datos.get("fecha_display", ""),
                            "total": datos.get("total", 0),
                            "mejorados": datos.get("mejorados", 0),
                        })
                    except:
                        pass
        return jsonify(reportes)
    except Exception as e:
        return jsonify([])


@app.route("/api/reporte-calidad-pdf/<reporte_id>")
@app.route("/api/reporte-calidad-pdf")
def api_reporte_calidad_pdf(reporte_id=None):
    """Genera reporte como HTML (imprimible como PDF desde el browser)."""
    try:
        global mejora_progreso
        if reporte_id:
            datos = cargar_reporte_github(reporte_id)
            if not datos:
                archivo = os.path.join(HISTORIAL_DIR, f"{reporte_id}.json")
                datos = json.load(open(archivo)) if os.path.exists(archivo) else mejora_progreso
        else:
            datos = mejora_progreso

        total = datos.get("total", 0)
        mejorados = datos.get("mejorados", 0)
        resultados = datos.get("resultados", [])
        ok_list = [r for r in resultados if r.get("ok") and not r.get("ya_ok")]
        ya_ok_list = [r for r in resultados if r.get("ya_ok")]
        fecha = datetime.now().strftime("%d/%m/%Y %H:%M")

        filas = ""
        for i, r in enumerate(ok_list, 1):
            titulo = r.get("titulo", r.get("item_id", ""))
            score_ant = r.get("score_anterior", "?")
            score_est = r.get("score_estimado", 82)
            mejoras = ", ".join(r.get("mejoras_aplicadas", []))
            filas += f"<tr><td>{i}</td><td>{titulo}</td><td style=\'color:#c0392b\'>{score_ant}%</td><td style=\'color:#27ae60\'>{score_est}%</td><td>{mejoras}</td></tr>"

        html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>Reporte Calidad Simple\'s</title>
<style>
body{{font-family:Arial,sans-serif;margin:40px;color:#1a1a1a;font-size:13px}}
h1{{color:#185FA5;font-size:22px}}h2{{color:#185FA5;border-bottom:1px solid #ddd;padding-bottom:6px}}
.cards{{display:flex;gap:16px;margin:20px 0}}.card{{background:#f5f5f5;border-radius:8px;padding:14px 20px;text-align:center;min-width:100px}}
.num{{font-size:28px;font-weight:bold}}.lbl{{font-size:11px;color:#666}}
table{{width:100%;border-collapse:collapse;margin-top:12px}}
th{{background:#185FA5;color:white;padding:8px 10px;text-align:left;font-size:12px}}
td{{padding:7px 10px;border-bottom:1px solid #f0ede8;font-size:12px}}
tr:nth-child(even){{background:#f9f9f9}}
ul li{{margin-bottom:8px}}.footer{{margin-top:40px;color:#999;font-size:11px;border-top:1px solid #ddd;padding-top:10px}}
@media print{{.no-print{{display:none}}}}
</style></head><body>
<div class="no-print" style="background:#185FA5;color:white;padding:10px 20px;border-radius:8px;margin-bottom:20px;cursor:pointer" onclick="window.print()">
  🖨️ Imprimir / Guardar como PDF (Ctrl+P)
</div>
<h1>Simple\'s - Reporte de Calidad de Publicaciones</h1>
<p style="color:#666;font-size:12px">Generado el {fecha}</p>
<div class="cards">
  <div class="card"><div class="num" style="color:#185FA5">{total}</div><div class="lbl">Revisadas</div></div>
  <div class="card"><div class="num" style="color:#27ae60">{mejorados}</div><div class="lbl">Mejoradas</div></div>
  <div class="card"><div class="num">{len(ya_ok_list)}</div><div class="lbl">Ya OK</div></div>
</div>
<h2>Publicaciones mejoradas ({len(ok_list)})</h2>
<table><tr><th>#</th><th>Producto</th><th>Score anterior</th><th>Score estimado</th><th>Mejoras</th></tr>
{filas}</table>
<h2>Recomendaciones</h2><ul>
<li>Agregar codigo universal (GTIN/EAN) a cada producto.</li>
<li>Subir al menos 4 fotos por publicacion en fondo blanco.</li>
<li>Completar caracteristicas secundarias: peso, dimensiones, material.</li>
<li>Activar Mercado Envios para mayor visibilidad.</li>
<li>Responder preguntas en menos de 1 hora.</li>
<li>Ofrecer devoluciones para aumentar la confianza.</li>
</ul>
<div class="footer">Simple\'s - Sistema de automatizacion Mercado Libre Argentina</div>
</body></html>"""

        from flask import Response
        return Response(html, mimetype="text/html")
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()[-500:]})


@app.route("/api/progreso-mejora")
def api_progreso_mejora():
    global mejora_progreso
    return jsonify(mejora_progreso)


@app.route("/api/mejorar-calidad", methods=["POST"])
def api_mejorar_calidad():
    """Mejora todas las publicaciones con puntaje bajo a 75%+."""
    global mejora_progreso
    if mejora_progreso.get("corriendo"):
        return jsonify({"ok": False, "error": "Ya hay una mejora en curso"})
    
    def correr_mejora():
        global mejora_progreso
        try:
            from publicador import PublicadorML
            pub = PublicadorML(sistema.ml, CONFIG.get("ANTHROPIC_API_KEY", ""))
            user_id = CONFIG.get("ML_USER_ID", "211711561")
            items_data = sistema.ml.get(f"/users/{user_id}/items/search",
                                         params={"status": "active", "limit": 50})
            item_ids = items_data.get("results", [])
            mejora_progreso = {"corriendo": True, "actual": 0, "total": len(item_ids), 
                               "producto_actual": "", "mejorados": 0, "resultados": []}
            log(f"🔍 Revisando calidad de {len(item_ids)} publicaciones...")
            for i, item_id in enumerate(item_ids):
                try:
                    mejora_progreso["actual"] = i + 1
                    mejora_progreso["producto_actual"] = f"Verificando {item_id}..."
                    perf = sistema.ml.get(f"/item/{item_id}/performance")
                    score = perf.get("score", 100)
                    if score < 75:
                        item_data = sistema.ml.get(f"/items/{item_id}")
                        titulo = item_data.get("title", item_id)
                        mejora_progreso["producto_actual"] = f"Mejorando: {titulo[:50]}"
                        health_compat = {
                            "overall": {"points": score},
                            "sections": [
                                {
                                    "section_id": b.get("key", ""),
                                    "points": b.get("score", 0),
                                    "total_points": 100,
                                    "tips": [{"tip": v.get("title", "")} for v in b.get("variables", []) if v.get("status") == "PENDING"]
                                }
                                for b in perf.get("buckets", [])
                            ]
                        }
                        resultado = pub.mejorar_calidad_publicacion(item_id, item_data, health_compat)
                        if resultado.get("ok") and resultado.get("accion") != "ya_ok":
                            mejora_progreso["mejorados"] += 1
                            mejora_progreso["resultados"].append({
                                "item_id": item_id,
                                "titulo": item_data.get("title", "")[:50],
                                "score_anterior": score,
                                "mejoras_aplicadas": resultado.get("mejoras_aplicadas", []),
                                "score_estimado": resultado.get("score_estimado", 80),
                                "ok": True
                            })
                            log(f"✅ {item_id}: {score}% → mejorado")
                            guardar_mejora_progreso()
                    else:
                        mejora_progreso["resultados"].append({
                            "item_id": item_id,
                            "titulo": "",
                            "score": score,
                            "ok": True,
                            "ya_ok": True
                        })
                except Exception as e:
                    mejora_progreso["resultados"].append({"item_id": item_id, "error": str(e), "ok": False})
                    log(f"❌ Error en {item_id}: {e}")
            mejora_progreso["corriendo"] = False
            mejora_progreso["producto_actual"] = f"✅ Listo — {mejora_progreso['mejorados']} publicaciones mejoradas"
            guardar_mejora_progreso()
            # Guardar en GitHub (persistente) y en /tmp como backup
            archivo_id = guardar_reporte_github(mejora_progreso)
            if not archivo_id:
                # Fallback a /tmp si GitHub falla
                archivo_id = f"reporte_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                try:
                    with open(os.path.join(HISTORIAL_DIR, f"{archivo_id}.json"), "w") as f:
                        json.dump(mejora_progreso, f)
                except:
                    pass
            mejora_progreso["ultimo_reporte"] = archivo_id
            guardar_mejora_progreso()
            log(f"✅ Mejora completada: {mejora_progreso['mejorados']}/{len(item_ids)} mejoradas")
        except Exception as e:
            mejora_progreso["corriendo"] = False
            mejora_progreso["producto_actual"] = f"❌ Error: {e}"
            log(f"❌ Error en mejora: {e}")

    import threading
    threading.Thread(target=correr_mejora, daemon=True).start()
    return jsonify({"ok": True, "iniciado": True})


@app.route("/api/intercambiar-codigo", methods=["POST"])
def api_intercambiar_codigo():
    """Intercambia un código TG- por un access_token y lo guarda automáticamente."""
    try:
        code = request.json.get("code", "").strip()
        if not code:
            return jsonify({"ok": False, "error": "Código vacío"})
        r = requests.post("https://api.mercadolibre.com/oauth/token", data={
            "grant_type":    "authorization_code",
            "client_id":     CONFIG["ML_CLIENT_ID"],
            "client_secret": CONFIG["ML_CLIENT_SECRET"],
            "code":          code,
            "redirect_uri":  "https://httpbin.org/get",
        })
        if r.status_code != 200:
            return jsonify({"ok": False, "error": r.json().get("message", "Error al intercambiar código")})
        data = r.json()
        sistema.ml.token = data["access_token"]
        CONFIG["ML_ACCESS_TOKEN"] = data["access_token"]
        if data.get("refresh_token"):
            CONFIG["ML_REFRESH_TOKEN"] = data["refresh_token"]
            sistema.ml.cfg["ML_REFRESH_TOKEN"] = data["refresh_token"]
        sistema.ml._ultimo_refresh = datetime.now()
        sistema.ml._guardar_token()
        log("🔑 Token actualizado desde dashboard")
        return jsonify({"ok": True, "mensaje": "Token actualizado y guardado"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/actualizar-token", methods=["POST"])
def api_actualizar_token():
    """Actualiza el access token y refresh token manualmente."""
    datos = request.json
    access = datos.get("access_token", "").strip()
    refresh = datos.get("refresh_token", "").strip()
    if access:
        sistema.ml.token = access
        CONFIG["ML_ACCESS_TOKEN"] = access
    if refresh:
        CONFIG["ML_REFRESH_TOKEN"] = refresh
        sistema.ml.cfg["ML_REFRESH_TOKEN"] = refresh
    sistema.ml._ultimo_refresh = datetime.now()
    sistema.ml._guardar_token()
    log("🔑 Token actualizado manualmente desde dashboard")
    return jsonify({"ok": True, "mensaje": "Token actualizado y guardado"})


@app.route("/api/estado-token")
def api_estado_token():
    """Devuelve el estado del token actual."""
    segundos = (datetime.now() - sistema.ml._ultimo_refresh).total_seconds()
    horas = int(segundos / 3600)
    minutos = int((segundos % 3600) / 60)
    expira_en = max(0, 6 - horas)
    return jsonify({
        "ultimo_refresh": f"hace {horas}h {minutos}m",
        "expira_en_horas": expira_en,
        "estado": "ok" if expira_en > 0 else "expirado",
        "tiene_refresh_token": bool(CONFIG.get("ML_REFRESH_TOKEN")),
    })


@app.route("/api/buscar-vendedor")
def api_buscar_vendedor():
    try:
        nickname = request.args.get("nickname", "").strip()
        if not nickname:
            return jsonify({"error": "nickname requerido"})
        r = sistema.ml.get("/sites/MLA/search", params={"nickname": nickname, "limit": 1})
        seller_info = r.get("seller", {})
        if not seller_info:
            # Buscar por búsqueda de usuarios
            r2 = sistema.ml.get(f"/users/search", params={"nickname": nickname})
            resultados = r2.get("results", [])
            if not resultados:
                return jsonify({"error": "Vendedor no encontrado"})
            seller_info = resultados[0]
        return jsonify({
            "id":         seller_info.get("id"),
            "nickname":   seller_info.get("nickname", nickname),
            "ventas":     seller_info.get("seller_reputation", {}).get("transactions", {}).get("completed", 0),
            "reputacion": seller_info.get("seller_reputation", {}).get("level_id", "N/A"),
        })
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/api/categorias-ml")
def api_categorias():
    from publicador import CATEGORIAS_ML
    return jsonify([{"nombre": k, "id": v} for k, v in CATEGORIAS_ML.items()])


@app.route("/api/categorias-droppers")
def api_categorias_droppers():
    try:
        from scraper_droppers import ScraperDroppers
        s = ScraperDroppers()
        return jsonify(s.obtener_categorias())
    except Exception as e:
        return jsonify({"error": str(e)})


scraper_estado = {"corriendo": False, "progreso": 0, "total": 0, "productos": [], "categoria": ""}


@app.route("/api/cargar-productos", methods=["POST"])
def api_cargar_productos():
    global scraper_estado
    datos = request.json
    productos = datos.get("productos", [])
    scraper_estado["productos"] = productos
    scraper_estado["total"] = len(productos)
    scraper_estado["progreso"] = len(productos)
    scraper_estado["corriendo"] = False
    log(f"✅ {len(productos)} productos cargados externamente")
    return jsonify({"ok": True, "productos": len(productos)})


@app.route("/api/scrape-droppers", methods=["POST"])
def api_scrape_droppers():
    global scraper_estado
    if scraper_estado["corriendo"]:
        return jsonify({"error": "Ya hay un scrape en curso"})

    datos = request.json
    categoria = datos.get("categoria", "")

    def correr_scrape():
        global scraper_estado
        try:
            import os
            scraper_estado = {"corriendo": True, "progreso": 0, "total": 0, "productos": [], "categoria": categoria}
            
            # Intentar leer desde archivo JSON primero
            json_path = os.path.join(os.path.dirname(__file__), "productos_droppers.json")
            if os.path.exists(json_path):
                with open(json_path, "r", encoding="utf-8") as f:
                    todos = json.load(f)
                from scraper_droppers import CATEGORIAS_DROPPERS, ScraperDroppers
                cat_info = CATEGORIAS_DROPPERS.get(categoria, {})
                cat_ml = cat_info.get("ml", "")
                cat_url = cat_info.get("url", "")

                # Filtrar productos que correspondan a esta categoría
                # Si el producto tiene campo categoria, filtramos; sino scrapeamos
                productos_cat = [p for p in todos if p.get("categoria") == categoria]

                if not productos_cat:
                    # No hay filtro por categoría — intentar scrape real
                    try:
                        scraper = ScraperDroppers()
                        productos_cat = scraper.scrape_categoria(categoria)
                        if not productos_cat:
                            # Fallback: usar todos con la categoría asignada
                            productos_cat = todos
                    except:
                        productos_cat = todos

                for p in productos_cat:
                    p["categoria_ml"] = cat_ml
                    p["categoria"] = categoria

                scraper_estado["productos"] = productos_cat
                scraper_estado["total"] = len(productos_cat)
                scraper_estado["progreso"] = len(productos_cat)
                scraper_estado["corriendo"] = False
                log(f"✅ {len(productos_cat)} productos cargados para categoria '{categoria}'")
                return

            # Si no hay archivo, intentar scrape online
            from scraper_droppers import ScraperDroppers
            s = ScraperDroppers()
            productos = s.scrape_categoria(categoria)
            scraper_estado["productos"] = productos
            scraper_estado["total"] = len(productos)
            scraper_estado["progreso"] = len(productos)
            scraper_estado["corriendo"] = False
            log(f"✅ Scrape completado: {len(productos)} productos de {categoria}")
        except Exception as e:
            scraper_estado["corriendo"] = False
            log(f"❌ Error scrape: {e}")

    threading.Thread(target=correr_scrape, daemon=True).start()
    return jsonify({"status": "scrapeando", "categoria": categoria})


@app.route("/api/estado-scrape")
def api_estado_scrape():
    return jsonify({
        "corriendo":  scraper_estado["corriendo"],
        "progreso":   scraper_estado["progreso"],
        "total":      scraper_estado["total"],
        "categoria":  scraper_estado["categoria"],
        "productos":  len(scraper_estado["productos"]),
    })


@app.route("/api/productos-scrapeados")
def api_productos_scrapeados():
    return jsonify(scraper_estado["productos"][:100])


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
    """Corre el ciclo automático cada hora y refresca el token cada 5 horas."""
    schedule.every(1).hours.do(sistema.ciclo_completo)
    schedule.every(6).hours.do(sistema.actualizar_metricas)
    schedule.every(5).hours.do(sistema.ml.refrescar_token)
    # Mejora de calidad automática cada 2 horas
    def mejorar_calidad_auto():
        try:
            from publicador import PublicadorML
            pub = PublicadorML(sistema.ml, CONFIG.get("ANTHROPIC_API_KEY", ""))
            resultados = pub.ciclo_mejora_calidad(meta_score=75)
            if resultados:
                log(f"✅ Auto-mejora calidad: {len(resultados)} publicaciones mejoradas")
        except Exception as e:
            log(f"❌ Error auto-mejora: {e}")
    schedule.every(2).hours.do(mejorar_calidad_auto)
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

    # Cargar resultados previos de mejora de calidad
    cargar_mejora_progreso()

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


@app.route("/publicar")
def pagina_publicar():
    return PUBLICAR_HTML
