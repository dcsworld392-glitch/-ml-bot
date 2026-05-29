"""
=============================================================
  MÓDULO: MOTOR DE PROMOCIONES AUTOMÁTICAS
  Analiza margen disponible y genera promociones en ML
  cuando conviene para aumentar ventas y reseñas
=============================================================
"""

import os
import json
import requests
from datetime import datetime, timedelta
from costos import CalculadoraCostos, registro_costos

calculadora = CalculadoraCostos()


# =============================================================
#  REGLAS DE PROMOCIONES
# =============================================================

# Umbrales para activar promociones automáticas
REGLAS = {
    # Si el margen neto es mayor a este %, se puede activar descuento
    "margen_minimo_para_descuento": 20,

    # Descuento máximo a aplicar automáticamente (%)
    "descuento_maximo_auto": 15,

    # Si un producto tuvo más de X visitas sin venta en 7 días → descuento
    "visitas_sin_venta_umbral": 50,

    # Si tiene menos de X reseñas → priorizar descuentos para conseguir primeras ventas
    "resenas_para_priorizar": 10,

    # Días sin ventas para considerar producto "estancado"
    "dias_sin_venta_estancado": 7,
}


# =============================================================
#  MOTOR DE PROMOCIONES
# =============================================================

class MotorPromociones:
    def __init__(self, ml_client, anthropic_key):
        self.ml = ml_client
        self.anthropic_key = anthropic_key
        self.promociones_activas = {}  # {item_id: datos_promocion}
        self.historial = []

    # --- Análisis de productos ---

    def analizar_productos(self):
        """
        Analiza todos los productos activos y decide cuáles
        necesitan una promoción para activar ventas.
        """
        import anthropic
        resultados = []

        try:
            items_data = self.ml.obtener_mis_publicaciones()
            item_ids = items_data.get("results", [])[:30]

            for item_id in item_ids:
                try:
                    analisis = self._analizar_item(item_id)
                    if analisis:
                        resultados.append(analisis)
                except Exception as e:
                    pass

        except Exception as e:
            pass

        return resultados

    def _analizar_item(self, item_id):
        """Analiza un item individual y sugiere acción."""
        item = self.ml.obtener_detalle_item(item_id)
        if not item or "title" not in item:
            return None

        precio_actual = item.get("price", 0)
        titulo = item.get("title", "")

        # Obtener visitas
        try:
            visitas_data = self.ml.obtener_visitas(item_id)
            visitas_7d = visitas_data.get("total_visits", 0)
        except:
            visitas_7d = 0

        # Obtener ventas recientes del item
        ventas_recientes = self._ventas_item_recientes(item_id, dias=7)
        cant_ventas_7d = len(ventas_recientes)

        # Obtener costo registrado
        datos_costo = registro_costos.obtener(item_id)
        costo = datos_costo.get("costo", precio_actual * 0.55)
        categoria = datos_costo.get("categoria", "default")
        envio_gratis = datos_costo.get("envio_gratis", False)

        # Calcular margen actual
        calculo = calculadora.calcular(precio_actual, costo, categoria, envio_gratis)
        margen_actual = calculo["margen_neto_pct"]

        # Decidir acción
        accion = self._decidir_accion(
            margen_actual, visitas_7d, cant_ventas_7d, precio_actual
        )

        return {
            "item_id":       item_id,
            "titulo":        titulo[:60],
            "precio_actual": precio_actual,
            "margen_actual": margen_actual,
            "visitas_7d":    visitas_7d,
            "ventas_7d":     cant_ventas_7d,
            "accion":        accion,
            "costo":         costo,
            "categoria":     categoria,
            "envio_gratis":  envio_gratis,
        }

    def _decidir_accion(self, margen, visitas, ventas, precio):
        """Decide qué acción tomar según los datos del producto."""

        # Producto sin visitas → problema de SEO, no de precio
        if visitas < 10:
            return {
                "tipo":        "seo",
                "descripcion": "Pocas visitas — reescribir título y descripción",
                "urgencia":    "alta",
                "descuento":   0,
            }

        # Muchas visitas pero sin ventas → problema de precio o descripción
        if visitas >= REGLAS["visitas_sin_venta_umbral"] and ventas == 0:
            if margen >= REGLAS["margen_minimo_para_descuento"]:
                descuento = min(10, margen - 15)  # bajar hasta dejar 15% de margen
                return {
                    "tipo":        "descuento",
                    "descripcion": f"Alto tráfico sin conversión → descuento de {descuento:.0f}%",
                    "urgencia":    "alta",
                    "descuento":   descuento,
                    "precio_nuevo": round(precio * (1 - descuento / 100), 2),
                }
            else:
                return {
                    "tipo":        "descripcion",
                    "descripcion": "Mejorar descripción y fotos — margen insuficiente para descuento",
                    "urgencia":    "media",
                    "descuento":   0,
                }

        # Producto con ventas y buen margen → potenciar con oferta
        if ventas >= 3 and margen >= 25:
            descuento = min(REGLAS["descuento_maximo_auto"], margen - 18)
            return {
                "tipo":        "oferta_del_dia",
                "descripcion": f"Producto con tracción → oferta del día ({descuento:.0f}% off)",
                "urgencia":    "baja",
                "descuento":   descuento,
                "precio_nuevo": round(precio * (1 - descuento / 100), 2),
            }

        # Producto nuevo sin ventas → pequeño descuento para conseguir primeras reseñas
        if ventas == 0 and visitas >= 10:
            if margen >= REGLAS["margen_minimo_para_descuento"]:
                return {
                    "tipo":        "primera_venta",
                    "descripcion": "Descuento para conseguir primeras reseñas",
                    "urgencia":    "media",
                    "descuento":   8,
                    "precio_nuevo": round(precio * 0.92, 2),
                }

        # Todo bien
        return {
            "tipo":        "ok",
            "descripcion": "Producto funcionando correctamente",
            "urgencia":    "ninguna",
            "descuento":   0,
        }

    def _ventas_item_recientes(self, item_id, dias=7):
        """Obtiene ventas recientes de un item específico."""
        try:
            uid = self.ml.cfg["ML_USER_ID"]
            desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%dT00:00:00.000-03:00")
            data = self.ml.get("/orders/search", params={
                "seller": uid,
                "order.status": "paid",
                "order.date_created.from": desde,
                "q": item_id,
            })
            return data.get("results", [])
        except:
            return []

    # --- Aplicar promociones ---

    def aplicar_descuento(self, item_id, descuento_pct, motivo="promocion_automatica"):
        """Aplica un descuento a un producto en ML."""
        try:
            item = self.ml.obtener_detalle_item(item_id)
            precio_original = item.get("price", 0)
            precio_nuevo = round(precio_original * (1 - descuento_pct / 100), 2)

            resultado = self.ml.actualizar_precio(item_id, precio_nuevo)

            if resultado.get("id") or resultado.get("price"):
                self.promociones_activas[item_id] = {
                    "precio_original": precio_original,
                    "precio_con_descuento": precio_nuevo,
                    "descuento_pct": descuento_pct,
                    "motivo": motivo,
                    "fecha_inicio": datetime.now().isoformat(),
                    "duracion_horas": 48,
                }
                self.historial.append({
                    "hora": datetime.now().strftime("%d/%m %H:%M"),
                    "item_id": item_id,
                    "titulo": item.get("title","")[:40],
                    "accion": f"Descuento {descuento_pct}% aplicado (${precio_original:,.0f} → ${precio_nuevo:,.0f})",
                })
                return {"ok": True, "precio_nuevo": precio_nuevo}

            return {"ok": False, "error": str(resultado)}

        except Exception as e:
            return {"ok": False, "error": str(e)}

    def revertir_descuento(self, item_id):
        """Vuelve el precio al original después de una promoción."""
        if item_id not in self.promociones_activas:
            return {"ok": False, "error": "No hay promoción activa para este producto"}

        promo = self.promociones_activas[item_id]
        resultado = self.ml.actualizar_precio(item_id, promo["precio_original"])

        if resultado.get("id") or resultado.get("price"):
            del self.promociones_activas[item_id]
            return {"ok": True}

        return {"ok": False, "error": str(resultado)}

    def ciclo_promociones(self):
        """
        Corre automáticamente cada 6 horas:
        1. Revierte promociones vencidas
        2. Analiza productos y aplica nuevas promociones si conviene
        """
        # 1. Revertir promociones vencidas
        for item_id, promo in list(self.promociones_activas.items()):
            inicio = datetime.fromisoformat(promo["fecha_inicio"])
            if (datetime.now() - inicio).total_seconds() > promo["duracion_horas"] * 3600:
                self.revertir_descuento(item_id)

        # 2. Analizar y aplicar nuevas
        analisis = self.analizar_productos()
        aplicadas = []

        for item in analisis:
            accion = item["accion"]
            if accion["tipo"] in ("descuento", "primera_venta") and accion["descuento"] > 0:
                if item["item_id"] not in self.promociones_activas:
                    resultado = self.aplicar_descuento(
                        item["item_id"],
                        accion["descuento"],
                        accion["tipo"]
                    )
                    if resultado["ok"]:
                        aplicadas.append(item)

        return {"analizados": len(analisis), "promociones_aplicadas": len(aplicadas)}

    def obtener_resumen(self):
        """Resumen para el dashboard."""
        return {
            "promociones_activas": len(self.promociones_activas),
            "detalle_activas": [
                {
                    "item_id": k,
                    "descuento_pct": v["descuento_pct"],
                    "precio_original": v["precio_original"],
                    "precio_actual": v["precio_con_descuento"],
                    "motivo": v["motivo"],
                    "vence_en": f"{max(0, v['duracion_horas'] - int((datetime.now() - datetime.fromisoformat(v['fecha_inicio'])).total_seconds() / 3600))}h",
                }
                for k, v in self.promociones_activas.items()
            ],
            "historial": self.historial[-10:],
        }
