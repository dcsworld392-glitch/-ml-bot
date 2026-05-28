"""
=============================================================
  MÓDULO: AUTOMATIZACIÓN DE PEDIDOS EN DROPPERS
  Se integra con bot.py para completar el flujo de dropshipping
=============================================================

Este módulo hace lo siguiente automáticamente:
  1. Cuando llega una venta en ML, extrae los datos del comprador
  2. Entra a Droppers con tu cuenta
  3. Busca el producto vendido
  4. Carga el pedido con los datos del cliente de ML
  5. Confirma el pedido (descuenta de tu saldo en Droppers)
  6. Notifica al comprador de ML con el número de seguimiento

INSTALACIÓN (agregar a las librerías existentes):
  pip install playwright
  playwright install chromium

=============================================================
"""

import os
import json
import time
import logging
from datetime import datetime

# Playwright para automatización web
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    PLAYWRIGHT_OK = True
except ImportError:
    PLAYWRIGHT_OK = False
    print("⚠️  Playwright no instalado. Corré: pip install playwright && playwright install chromium")

# =============================================================
#  CONFIGURACIÓN DE DROPPERS
# =============================================================

DROPPERS_CONFIG = {
    "url":      "https://droppers.com.ar",
    "usuario":  os.environ.get("DROPPERS_USER", "dcsworld392@gmail.com"),
    "password": os.environ.get("DROPPERS_PASS", ""),  # se carga desde variable de entorno
}

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("droppers")


# =============================================================
#  ROBOT DE DROPPERS
# =============================================================

class DroppersBot:
    def __init__(self):
        self.cfg = DROPPERS_CONFIG
        self.logueado = False

    def hacer_pedido(self, datos_venta_ml):
        """
        Recibe los datos de una venta de ML y hace el pedido en Droppers.

        datos_venta_ml = {
            "order_id":        "123456789",
            "producto_titulo": "Auriculares Bluetooth",
            "sku_droppers":    "SKU-001",       # código del producto en Droppers
            "cantidad":        1,
            "comprador": {
                "nombre":    "Juan Pérez",
                "telefono":  "1155551234",
                "direccion": "Av. Corrientes 1234",
                "ciudad":    "Buenos Aires",
                "provincia": "Buenos Aires",
                "cp":        "1043"
            }
        }
        """
        if not PLAYWRIGHT_OK:
            log.error("Playwright no instalado. No se puede automatizar Droppers.")
            return {"ok": False, "error": "Playwright no instalado"}

        log.info(f"🛒 Iniciando pedido en Droppers para orden ML #{datos_venta_ml.get('order_id')}")

        try:
            with sync_playwright() as p:
                # Correr sin ventana visible (headless=True para servidor en la nube)
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = context.new_page()
                page.set_default_timeout(30000)

                # --- PASO 1: Login ---
                resultado = self._login(page)
                if not resultado["ok"]:
                    browser.close()
                    return resultado

                # --- PASO 2: Buscar el producto ---
                resultado = self._buscar_producto(page, datos_venta_ml)
                if not resultado["ok"]:
                    browser.close()
                    return resultado

                # --- PASO 3: Agregar al carrito ---
                resultado = self._agregar_al_carrito(page, datos_venta_ml)
                if not resultado["ok"]:
                    browser.close()
                    return resultado

                # --- PASO 4: Cargar datos del cliente ---
                resultado = self._cargar_datos_envio(page, datos_venta_ml["comprador"])
                if not resultado["ok"]:
                    browser.close()
                    return resultado

                # --- PASO 5: Confirmar pedido ---
                resultado = self._confirmar_pedido(page)
                browser.close()
                return resultado

        except Exception as e:
            log.error(f"❌ Error en Droppers: {e}")
            return {"ok": False, "error": str(e)}

    def _login(self, page):
        """Inicia sesión en Droppers."""
        try:
            log.info("🔑 Iniciando sesión en Droppers...")
            page.goto(f"{self.cfg['url']}/customer/account/login/")
            page.wait_for_load_state("networkidle")

            # Completar email
            page.fill("#email", self.cfg["usuario"])
            page.fill("#pass", self.cfg["password"])
            page.click("#send2")
            page.wait_for_load_state("networkidle")

            # Verificar que entró correctamente
            if "account" in page.url or "start" in page.url:
                log.info("✅ Login exitoso en Droppers")
                self.logueado = True
                return {"ok": True}
            else:
                log.error("❌ Login fallido en Droppers — verificá usuario/contraseña")
                return {"ok": False, "error": "Login fallido"}

        except PlaywrightTimeout:
            return {"ok": False, "error": "Timeout al hacer login"}

    def _buscar_producto(self, page, datos_venta):
        """Navega al producto correspondiente en Droppers."""
        try:
            titulo = datos_venta.get("producto_titulo", "")
            sku = datos_venta.get("sku_droppers", "")

            log.info(f"🔍 Buscando producto: {titulo[:50]}")

            if sku:
                # Si tenemos el SKU, buscamos directamente
                page.goto(f"{self.cfg['url']}/catalogsearch/result/?q={sku}")
            else:
                # Si no, buscamos por título
                palabras = " ".join(titulo.split()[:4])
                page.goto(f"{self.cfg['url']}/catalogsearch/result/?q={palabras}")

            page.wait_for_load_state("networkidle")

            # Hacer clic en el primer resultado
            primer_resultado = page.query_selector(".product-item-link")
            if not primer_resultado:
                return {"ok": False, "error": f"Producto no encontrado: {titulo}"}

            primer_resultado.click()
            page.wait_for_load_state("networkidle")
            log.info(f"✅ Producto encontrado: {page.title()}")
            return {"ok": True}

        except Exception as e:
            return {"ok": False, "error": f"Error buscando producto: {e}"}

    def _agregar_al_carrito(self, page, datos_venta):
        """Agrega el producto al carrito con la cantidad correcta."""
        try:
            cantidad = datos_venta.get("cantidad", 1)

            # Ajustar cantidad si es más de 1
            qty_input = page.query_selector("#qty")
            if qty_input and cantidad > 1:
                qty_input.fill(str(cantidad))

            # Agregar al carrito
            page.click("#product-addtocart-button")
            page.wait_for_load_state("networkidle")
            time.sleep(1)

            log.info(f"✅ Producto agregado al carrito (cantidad: {cantidad})")
            return {"ok": True}

        except Exception as e:
            return {"ok": False, "error": f"Error agregando al carrito: {e}"}

    def _cargar_datos_envio(self, page, comprador):
        """Carga los datos del comprador de ML en el checkout de Droppers."""
        try:
            log.info("📦 Cargando datos de envío del comprador...")

            # Ir al checkout
            page.goto(f"{self.cfg['url']}/checkout/")
            page.wait_for_load_state("networkidle")
            time.sleep(2)

            # Separar nombre y apellido
            nombre_completo = comprador.get("nombre", "").split()
            nombre = nombre_completo[0] if nombre_completo else ""
            apellido = " ".join(nombre_completo[1:]) if len(nombre_completo) > 1 else "."

            # Completar formulario de envío
            campos = {
                'input[name="firstname"]':  nombre,
                'input[name="lastname"]':   apellido,
                'input[name="telephone"]':  comprador.get("telefono", ""),
                'input[name="street[0]"]':  comprador.get("direccion", ""),
                'input[name="city"]':       comprador.get("ciudad", ""),
                'input[name="postcode"]':   comprador.get("cp", ""),
            }

            for selector, valor in campos.items():
                try:
                    campo = page.query_selector(selector)
                    if campo:
                        campo.fill(str(valor))
                except:
                    pass

            # Seleccionar provincia si hay dropdown
            try:
                provincia = comprador.get("provincia", "Buenos Aires")
                page.select_option('select[name="region_id"]', label=provincia)
            except:
                pass

            time.sleep(1)
            log.info("✅ Datos de envío cargados")
            return {"ok": True}

        except Exception as e:
            return {"ok": False, "error": f"Error cargando datos de envío: {e}"}

    def _confirmar_pedido(self, page):
        """Confirma el pedido en Droppers (usa el saldo de la cuenta)."""
        try:
            log.info("💳 Confirmando pedido...")

            # Buscar y hacer clic en el botón de continuar/siguiente
            botones_siguiente = [
                "button.continue",
                ".action.continue",
                "button[data-role='opc-continue']",
                ".btn-primary",
            ]

            for selector in botones_siguiente:
                btn = page.query_selector(selector)
                if btn:
                    btn.click()
                    time.sleep(2)
                    break

            # Buscar botón de confirmar pedido final
            page.wait_for_load_state("networkidle")
            time.sleep(2)

            btn_confirmar = page.query_selector("button.action.primary.checkout") or \
                           page.query_selector("#checkout-payment-method-load button.primary") or \
                           page.query_selector(".action.primary")

            if btn_confirmar:
                btn_confirmar.click()
                page.wait_for_load_state("networkidle")
                time.sleep(3)

            # Verificar si el pedido se confirmó
            url_actual = page.url
            contenido = page.content()

            if "success" in url_actual or "gracias" in contenido.lower() or "thank" in contenido.lower():
                # Intentar obtener número de pedido
                nro_pedido = ""
                try:
                    el = page.query_selector(".order-number strong") or page.query_selector(".order-number")
                    if el:
                        nro_pedido = el.inner_text()
                except:
                    pass

                log.info(f"✅ Pedido confirmado en Droppers! Nro: {nro_pedido}")
                return {"ok": True, "nro_pedido_droppers": nro_pedido}
            else:
                log.warning("⚠️  No se pudo confirmar si el pedido fue exitoso — revisá manualmente")
                return {"ok": True, "advertencia": "Verificar pedido manualmente en Droppers"}

        except Exception as e:
            return {"ok": False, "error": f"Error confirmando pedido: {e}"}


# =============================================================
#  INTEGRACIÓN CON EL BOT DE ML
# =============================================================

def procesar_venta_ml(orden_ml, ml_client):
    """
    Función principal: recibe una orden de ML y hace todo automáticamente.
    Se llama desde bot.py cuando se detecta una venta nueva.
    """
    bot = DroppersBot()

    # Extraer datos del comprador desde la orden de ML
    shipping = orden_ml.get("shipping", {})
    receiver = shipping.get("receiver_address", {})
    buyer = orden_ml.get("buyer", {})

    # Armar datos para Droppers
    datos_venta = {
        "order_id": str(orden_ml.get("id", "")),
        "cantidad": sum(i.get("quantity", 1) for i in orden_ml.get("order_items", [])),
        "producto_titulo": orden_ml.get("order_items", [{}])[0].get("item", {}).get("title", ""),
        "sku_droppers": "",  # se puede mapear si tenés una tabla de SKUs
        "comprador": {
            "nombre":    f"{buyer.get('first_name','')} {buyer.get('last_name','')}".strip(),
            "telefono":  receiver.get("phone", {}).get("number", ""),
            "direccion": f"{receiver.get('street_name','')} {receiver.get('street_number','')}".strip(),
            "ciudad":    receiver.get("city", {}).get("name", ""),
            "provincia": receiver.get("state", {}).get("name", "Buenos Aires"),
            "cp":        receiver.get("zip_code", ""),
        }
    }

    log.info(f"📦 Nueva venta ML: {datos_venta['producto_titulo'][:50]} → {datos_venta['comprador']['nombre']}")

    # Hacer el pedido en Droppers
    resultado = bot.hacer_pedido(datos_venta)

    if resultado["ok"]:
        # Notificar al comprador por mensaje de ML
        try:
            nro = resultado.get("nro_pedido_droppers", "")
            mensaje = f"¡Hola! Tu pedido fue confirmado y está siendo preparado para envío. "
            if nro:
                mensaje += f"Número de seguimiento interno: {nro}. "
            mensaje += "Te avisamos cuando tengamos el código de seguimiento de correo. ¡Gracias por tu compra!"

            # Enviar mensaje al comprador via API de ML
            ml_client.post(f"/messages/packs/{orden_ml.get('pack_id', '')}/sellers/{orden_ml.get('seller', {}).get('id', '')}", {
                "from": {"user_id": int(os.environ.get("ML_USER_ID", "0"))},
                "to": [{"user_id": buyer.get("id")}],
                "text": mensaje
            })
            log.info("✅ Comprador notificado por mensaje de ML")
        except Exception as e:
            log.warning(f"No se pudo notificar al comprador: {e}")

    return resultado


# =============================================================
#  MONITOR DE VENTAS NUEVAS
# =============================================================

class MonitorVentas:
    """Revisa cada 5 minutos si hay ventas nuevas y las pone en cola para aprobación."""

    def __init__(self, ml_client):
        self.ml = ml_client
        self.ventas_procesadas = set()   # IDs ya confirmados y pedidos en Droppers
        self.ventas_pendientes = {}      # IDs esperando tu aprobación: {order_id: datos}
        self.bot = DroppersBot()

    def verificar_ventas_nuevas(self):
        """Busca ventas recientes y las pone en cola de aprobación."""
        log.info("🔍 Verificando ventas nuevas...")
        try:
            data = self.ml.obtener_mis_ventas(dias=1)
            ordenes = data.get("results", [])

            ya_vistas = self.ventas_procesadas | set(self.ventas_pendientes.keys())
            nuevas = [o for o in ordenes if str(o.get("id")) not in ya_vistas]

            if not nuevas:
                log.info("✅ No hay ventas nuevas")
                return

            log.info(f"🎉 {len(nuevas)} venta(s) nueva(s) — esperando tu aprobación")

            for orden in nuevas:
                order_id = str(orden.get("id"))
                items = orden.get("order_items", [{}])
                buyer = orden.get("buyer", {})
                shipping = orden.get("shipping", {})
                receiver = shipping.get("receiver_address", {})

                # Guardar en cola de pendientes
                self.ventas_pendientes[order_id] = {
                    "order_id":    order_id,
                    "hora":        datetime.now().strftime("%d/%m %H:%M"),
                    "producto":    items[0].get("item", {}).get("title", "?")[:60],
                    "cantidad":    sum(i.get("quantity", 1) for i in items),
                    "total_ml":    orden.get("total_amount", 0),
                    "comprador":   f"{buyer.get('first_name','')} {buyer.get('last_name','')}".strip(),
                    "direccion":   f"{receiver.get('street_name','')} {receiver.get('street_number','')}".strip(),
                    "ciudad":      receiver.get("city", {}).get("name", ""),
                    "provincia":   receiver.get("state", {}).get("name", ""),
                    "cp":          receiver.get("zip_code", ""),
                    "telefono":    receiver.get("phone", {}).get("number", ""),
                    "orden_raw":   orden,  # datos completos para cuando se confirme
                }
                log.info(f"⏳ Venta {order_id} en espera de aprobación: {self.ventas_pendientes[order_id]['producto']}")

        except Exception as e:
            log.error(f"Error verificando ventas: {e}")

    def aprobar_venta(self, order_id):
        """Aprobás la venta desde el dashboard → el bot hace el pedido en Droppers."""
        if order_id not in self.ventas_pendientes:
            return {"ok": False, "error": "Venta no encontrada en pendientes"}

        datos = self.ventas_pendientes[order_id]
        log.info(f"✅ Venta {order_id} aprobada — procesando en Droppers...")

        resultado = procesar_venta_ml(datos["orden_raw"], self.ml)

        if resultado["ok"]:
            self.ventas_procesadas.add(order_id)
            del self.ventas_pendientes[order_id]
            log.info(f"🎉 Pedido hecho en Droppers para venta {order_id}")
        else:
            log.error(f"❌ Error al procesar en Droppers: {resultado.get('error')}")

        return resultado

    def rechazar_venta(self, order_id):
        """Rechazás la venta — se marca como vista pero no se procesa en Droppers."""
        if order_id in self.ventas_pendientes:
            del self.ventas_pendientes[order_id]
            self.ventas_procesadas.add(order_id)
            log.info(f"🚫 Venta {order_id} rechazada manualmente")
            return {"ok": True}
        return {"ok": False, "error": "Venta no encontrada"}

        except Exception as e:
            log.error(f"Error verificando ventas: {e}")


if __name__ == "__main__":
    print("Este módulo se importa desde bot.py")
    print("Para probarlo solo, asegurate de tener las variables de entorno configuradas.")
