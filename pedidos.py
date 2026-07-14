"""
pedidos.py — Lógica de toma de pedidos para el bot de Huella.

Se integra al webhook existente de app.py. No reemplaza la lógica
conversacional que ya tenés: corre EN PARALELO sobre cada mensaje
entrante para ir armando el pedido en segundo plano.

Requiere: la misma ANTHROPIC_API_KEY que ya usás en app.py.
"""

import os
import json
import re
from datetime import datetime
from anthropic import Anthropic

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Estado de pedidos en curso por número de teléfono.
# Mismo patrón que tu dict CONVERSACIONES.
PEDIDOS = {}

# Campos obligatorios para poder confirmar un pedido.
# Ajustá esta lista si tu catálogo/negocio necesita otra cosa.
CAMPOS_OBLIGATORIOS = ["producto", "color", "cantidad", "nombre_mascota", "color_nombre", "telefono_grabado", "direccion_envio", "tipo_envio", "forma_pago"]

ARCHIVO_PEDIDOS_CONFIRMADOS = "pedidos_confirmados.json"


def _pedido_vacio():
    return {
        "producto": None,
        "color": None,
        "cantidad": None,
        "nombre_mascota": None,
        "color_nombre": None,
        "telefono_grabado": None,
        "direccion_envio": None,
        "tipo_envio": None,
        "forma_pago": None,
        "estado": "en_curso",  # en_curso | esperando_confirmacion | confirmado
    }


def extraer_info_pedido(mensaje: str, historial_reciente: list, catalogo: dict) -> dict:
    """
    Le pide a Claude que extraiga info de pedido del mensaje actual,
    usando el historial reciente como contexto (para no perder datos
    ya dados en mensajes anteriores).

    Devuelve un dict con los campos que pudo detectar en ESTE mensaje
    (puede venir parcial o vacío si el mensaje no aporta info de pedido).
    """
    contexto_historial = "\n".join(
        f"{m['role']}: {m['content']}" for m in historial_reciente[-6:]
    )

    system_prompt = f"""Extraés datos de pedidos de una conversación de WhatsApp de Huella
(venta de placas/tags para mascotas).

Catálogo disponible (para validar que producto/color existan):
{json.dumps(catalogo, ensure_ascii=False)}

Analizá el ÚLTIMO mensaje del cliente, usando el historial solo como contexto.
Devolvé SOLO un JSON (nada de texto antes ni después, sin markdown) con esta forma exacta:

{{
  "producto": string o null,
  "color": string o null,
  "cantidad": number o null,
  "nombre_mascota": string o null,
  "color_nombre": string o null,
  "telefono_grabado": string o null,
  "direccion_envio": string o null,
  "tipo_envio": "local" o "dac" o null,
  "forma_pago": string o null,
  "confirma_pedido": true/false,
  "cancela_pedido": true/false
}}

IMPORTANTE: "color_nombre" es el color en que va grabado el TEXTO del nombre en la
placa (puede ser distinto del color de la placa misma). "telefono_grabado" es el
número de teléfono que el cliente quiere que se grabe atrás de la placa (puede ser
distinto del número desde el que escribe por WhatsApp — no asumas que son el mismo
a menos que el cliente lo confirme).

IMPORTANTE: "nombre_mascota" es el nombre de LA MASCOTA que va grabado en la placa
(ej: "Ataulfo", "Eltobino"), NO el nombre del cliente que está pidiendo. Si el
mensaje menciona ambos nombres, no los confundas.

REGLA PARA tipo_envio — USÁ TU CONOCIMIENTO DE GEOGRAFÍA URUGUAYA:
Analizá la ciudad, pueblo, barrio o zona que mencione "direccion_envio" (o el mensaje)
y decidí:
- "local": si la entrega es dentro de la ciudad de Salto o sus alrededores inmediatos
  (cualquier barrio, calle o zona de Salto capital).
- "dac": si la entrega es en cualquier otra ciudad, pueblo o localidad del Uruguay
  que no sea Salto (Montevideo, Paysandú, Young, Artigas, Bella Unión, cualquier
  localidad del interior, etc. — usá tu conocimiento real de las ciudades y pueblos
  del país, no una lista fija).
- null: si todavía no hay suficiente información para saber la ciudad de destino.

REGLA MÁS IMPORTANTE — PROHIBIDO INVENTAR O ASUMIR DATOS:
Solo llená un campo si el cliente lo dijo EXPLÍCITAMENTE, con esas palabras o el equivalente
directo, en este mensaje o en el historial. Nunca asumas un valor "típico" o "por default".
Ejemplo prohibido: si el cliente no mencionó cómo va a pagar, "forma_pago" DEBE quedar null.
No asumas "efectivo" ni ningún otro método porque sea lo más común.

REGLA PARA direccion_envio — CIUDAD NO ES DIRECCIÓN:
Si el cliente solo menciona una ciudad o localidad (ej: "soy de Salto", "vivo en Montevideo")
pero no da calle, número, barrio o un punto de referencia concreto, NO es una dirección de
envío válida. Dejá "direccion_envio" en null en ese caso — vas a necesitar pedirle la
dirección exacta aparte, la ciudad sola no alcanza para coordinar una entrega.

Otras reglas:
- "confirma_pedido": true si el cliente está respondiendo de forma CLARAMENTE
  afirmativa a un resumen de pedido que ya se le mostró — no solo "sí" literal.
  Contá como confirmación cualquier cierre afirmativo natural: "sí", "dale",
  "confirmado", "genial", "listo", "perfecto", "okey", "buenísimo", "todo bien",
  combinaciones de esas ("dale perfecto"), etc.
  Solo dejalo en false si el mensaje es una pregunta, un pedido de cambio, o
  algo ambiguo que no cierra el tema (ej: "mmm", "no sé", "cuánto era").- "cancela_pedido": true si el cliente dice que quiere cancelar o cambiar de idea.
- Si no hay info de pedido en el mensaje, devolvé todos los campos en null y ambos booleanos en false.
"""

    respuesta = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=400,
        system=system_prompt,
        messages=[
            {"role": "user", "content": f"Historial:\n{contexto_historial}\n\nÚltimo mensaje del cliente: {mensaje}"}
        ],
    )

    texto = respuesta.content[0].text.strip()
    # Por si Claude devuelve el JSON envuelto en ```json ... ```
    texto = re.sub(r"^```json|```$", "", texto, flags=re.MULTILINE).strip()

    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        # Si falla el parseo, no rompemos el flujo conversacional normal.
        return {
            "producto": None, "color": None, "cantidad": None,
            "nombre_mascota": None, "color_nombre": None, "telefono_grabado": None,
            "direccion_envio": None, "tipo_envio": None, "forma_pago": None,
            "confirma_pedido": False, "cancela_pedido": False,
        }


def actualizar_pedido(numero: str, nueva_info: dict) -> dict:
    """Mezcla la info nueva detectada con el pedido en curso de ese número."""
    if numero not in PEDIDOS:
        PEDIDOS[numero] = _pedido_vacio()

    pedido = PEDIDOS[numero]
    estado_anterior = pedido["estado"]

    if nueva_info.get("cancela_pedido"):
        PEDIDOS[numero] = _pedido_vacio()
        PEDIDOS[numero]["_transicion_a_confirmacion"] = False
        return PEDIDOS[numero]

    for campo in ["producto", "color", "cantidad", "nombre_mascota", "color_nombre",
                  "telefono_grabado", "direccion_envio", "tipo_envio", "forma_pago"]:
        if nueva_info.get(campo):
            pedido[campo] = nueva_info[campo]

    if esta_completo(pedido) and pedido["estado"] == "en_curso":
        pedido["estado"] = "esperando_confirmacion"

    if nueva_info.get("confirma_pedido") and pedido["estado"] == "esperando_confirmacion":
        pedido["estado"] = "confirmado"
        guardar_pedido_confirmado(numero, pedido)
        PEDIDOS[numero] = _pedido_vacio()  # listo para un pedido nuevo
        return PEDIDOS[numero]

    # Marca si el pedido RECIÉN llegó a esperando_confirmacion en este mensaje,
    # para que el resumen se muestre una sola vez y no se repita en cada
    # mensaje siguiente mientras el cliente pregunta otra cosa.
    pedido["_transicion_a_confirmacion"] = (
        pedido["estado"] == "esperando_confirmacion" and estado_anterior != "esperando_confirmacion"
    )

    return pedido


def esta_completo(pedido: dict) -> bool:
    return all(pedido.get(campo) for campo in CAMPOS_OBLIGATORIOS)


def generar_resumen_confirmacion(pedido: dict) -> str:
    tipo_envio_texto = "Retiro/entrega en Salto" if pedido["tipo_envio"] == "local" else "Envío por DAC (otra ciudad)"
    return (
        f"Entonces tu pedido sería:\n"
        f"• Producto: {pedido['producto']}\n"
        f"• Color: {pedido['color']}\n"
        f"• Cantidad: {pedido['cantidad']}\n"
        f"• Nombre de la mascota: {pedido['nombre_mascota']}\n"
        f"• Color del nombre grabado: {pedido['color_nombre']}\n"
        f"• Teléfono grabado en la placa: {pedido['telefono_grabado']}\n"
        f"• Dirección de envío: {pedido['direccion_envio']}\n"
        f"• Tipo de entrega: {tipo_envio_texto}\n"
        f"• Forma de pago: {pedido['forma_pago']}\n\n"
        f"¿Confirmás el pedido? (sí/no)"
    )


def guardar_pedido_confirmado(numero: str, pedido: dict):
    registro = {**pedido, "numero_cliente": numero, "fecha": datetime.now().isoformat()}

    pedidos_previos = []
    if os.path.exists(ARCHIVO_PEDIDOS_CONFIRMADOS):
        with open(ARCHIVO_PEDIDOS_CONFIRMADOS, "r", encoding="utf-8") as f:
            try:
                pedidos_previos = json.load(f)
            except json.JSONDecodeError:
                pedidos_previos = []

    pedidos_previos.append(registro)

    with open(ARCHIVO_PEDIDOS_CONFIRMADOS, "w", encoding="utf-8") as f:
        json.dump(pedidos_previos, f, ensure_ascii=False, indent=2)


def notificar_dueno(pedido: dict, numero_cliente: str, numero_dueno: str, funcion_enviar):
    """
    Le avisa al dueño del negocio (por WhatsApp, reusando la misma función
    que ya manda mensajes a los clientes) que se confirmó un pedido nuevo.

    numero_dueno: viene de la variable de entorno NUMERO_DUENIO_HUELLA en app.py.
    funcion_enviar: la función send_whatsapp_message que ya tenés en app.py
                     (se la pasás por parámetro para evitar import circular).
    """
    if not numero_dueno:
        print("⚠️  NUMERO_DUENIO_HUELLA no configurado — no se pudo notificar el pedido nuevo.")
        return

    resumen = (
        f"🔔 *Pedido nuevo confirmado*\n\n"
        f"• Producto: {pedido['producto']} ({pedido['color']})\n"
        f"• Cantidad: {pedido['cantidad']}\n"
        f"• Mascota: {pedido['nombre_mascota']} — nombre en {pedido['color_nombre']}\n"
        f"• Teléfono grabado: {pedido['telefono_grabado']}\n"
        f"• Cliente (WhatsApp): {numero_cliente}\n"
        f"• Envío: {pedido['direccion_envio']} ({pedido['tipo_envio']})\n"
        f"• Pago: {pedido['forma_pago']}"
    )
    funcion_enviar(numero_dueno, resumen)


def procesar_mensaje_para_pedido(numero: str, mensaje: str, historial_reciente: list, catalogo: dict,
                                   numero_dueno: str = None, funcion_enviar_whatsapp=None):
    """
    Función principal para llamar desde app.py.

    numero_dueno / funcion_enviar_whatsapp: opcionales — si los pasás, al
    confirmarse un pedido se le manda automáticamente un WhatsApp al dueño
    del negocio con el resumen. Si no los pasás, el pedido igual se guarda
    en pedidos_confirmados.json, solo que nadie recibe el aviso.

    Devuelve:
      - texto_extra: string para agregar/reemplazar la respuesta del bot
        (ej: el resumen de confirmación), o None si no hay nada especial.
      - pedido_actual: el estado actualizado del pedido de ese número.
    """
    nueva_info = extraer_info_pedido(mensaje, historial_reciente, catalogo)
    pedido = actualizar_pedido(numero, nueva_info)

    if pedido["estado"] == "esperando_confirmacion":
        if pedido.get("_transicion_a_confirmacion"):
            return generar_resumen_confirmacion(pedido), pedido
        # El cliente ya vio el resumen y ahora preguntó/dijo otra cosa que no
        # fue "sí"/"no": dejamos pasar la respuesta natural del LLM (que puede
        # contestar su pregunta) y solo le sumamos un recordatorio corto.
        return None, pedido

    if pedido["estado"] == "confirmado":
        if numero_dueno and funcion_enviar_whatsapp:
            notificar_dueno(pedido, numero, numero_dueno, funcion_enviar_whatsapp)

        if pedido.get("tipo_envio") == "dac":
            mensaje_final = (
                "¡Pedido confirmado! 🎉 Como el envío es por DAC, coordinamos el pago "
                "ahora antes de despachar. En breve te contactamos para eso."
            )
        else:
            mensaje_final = (
                "¡Pedido confirmado! 🎉 Lo dejamos en preparación. El pago se hace "
                "en el momento de la entrega/retiro en Salto."
            )
        return mensaje_final, pedido

    return None, pedido
