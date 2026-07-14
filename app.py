import os
import json
import time
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from anthropic import Anthropic
from pedidos import procesar_mensaje_para_pedido 


load_dotenv()

app = Flask(__name__)

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "huella-verify-2026")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
NUMERO_DUENIO_HUELLA = os.getenv("NUMERO_DUENIO_HUELLA")

client = Anthropic(api_key=ANTHROPIC_API_KEY)

with open("catalogo_huella.json", "r", encoding="utf-8") as f:
    CATALOGO = json.load(f)

SYSTEM_PROMPT = f"""Sos el asistente de WhatsApp de Huella, un negocio de placas
personalizadas para mascotas en Salto, Uruguay (@huella_saltouy).

Tu trabajo es responder consultas de clientes sobre el catálogo, precios,
colores, tiempos de entrega y formas de pago.

CÓMO HABLAR:
- Máximo 3-4 líneas por mensaje. Nunca párrafos largos ni listas formales:
  esto es WhatsApp, no un email.
- Usá "vos", tono uruguayo relajado pero no exagerado (dale, genial, bárbaro
  — sin forzarlo en cada frase).
- Variá cómo arrancás cada respuesta. No repitas siempre la misma muletilla.

Ejemplos del tono que buscamos (no copies el texto literal, es solo referencia
de estilo y extensión):
- Cliente: "hola cuanto sale una placa"
  Vos: "Hola! Depende de la línea, arrancan en $XXX. ¿Para qué mascota es?"
- Cliente: "tienen en rosa?"
  Vos: "Sí, tenemos rosa en varias líneas. ¿Cuál te gustó?"
- Cliente: "y cuanto tarda"
  Vos: "Entre 3 y 5 días hábiles una vez confirmado el pedido, dale."

Acá está el catálogo completo, en JSON, que es tu única fuente de verdad
sobre productos y precios. No inventes líneas, colores ni precios que no
estén acá:

{json.dumps(CATALOGO, ensure_ascii=False, indent=2)}

Si te preguntan algo que no está en este catálogo (por ejemplo, un producto
que no existe), decilo con honestidad y ofrecé las opciones más parecidas
que sí tenés.

REGLA CRÍTICA — NUNCA declares un pedido como confirmado vos mismo:
No digas "pedido confirmado", no preguntes vos mismo "¿confirmás el pedido?", y no
resumas el pedido como si ya estuviera cerrado. Esa parte la maneja otro sistema
aparte, automáticamente, una vez que tenga TODOS los datos exactos. Tu trabajo es
solo charlar de forma natural y asegurarte de conseguir estos datos explícitos del
cliente antes de que se sienta que "ya está todo":
- Nombre de la mascota
- Línea, color de la placa, color del nombre
- Cantidad exacta
- Dirección de envío EXACTA (calle y número — si el cliente solo dice la ciudad,
  como "soy de Salto", pedile la calle y altura, la ciudad sola no alcanza)
- Teléfono para grabar en la placa
- Forma de pago

Si el cliente ya te dio todo lo de arriba, decile algo como "¡genial, ya tengo
todo lo que necesito, dejame confirmarte los detalles!" — sin decir la palabra
"confirmado" ni preguntar vos si confirma. El resumen final y la confirmación
real los muestra el sistema automáticamente en el próximo mensaje.
"""

# Memoria de conversación por cliente. Vive en RAM: se pierde si reiniciás
# el servidor. Para producción real esto se reemplaza por una base de datos
# (ver nota al final del archivo).
# Formato: { "numero_cliente": [ {"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}, ... ] }
CONVERSACIONES = {}

# Cuántos mensajes (entre user y assistant) guardamos como máximo por cliente,
# para no mandar un historial infinito a la API en cada llamada.
MAX_HISTORIAL = 20

# Si un mensaje llega con más de esta antigüedad (en segundos), lo ignoramos.
# Esto pasa cuando Meta reintenta entregar mensajes que no pudo mandar en su
# momento (servidor caído, deploy fallando, etc.) — sin esto, el bot procesa
# esos mensajes viejos como si fueran de ahora y manda respuestas fuera de
# contexto, días después, confundiendo al cliente.
ANTIGUEDAD_MAXIMA_SEGUNDOS = 5 * 60  # 5 minutos

def send_whatsapp_message(to, text):
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }
    response = requests.post(url, headers=headers, json=payload)
    print("Respuesta de WhatsApp API:", response.status_code, response.text)


def get_llm_response(sender, user_message):
    """Le pasa a Claude el mensaje nuevo MÁS el historial de este cliente."""
    historial = CONVERSACIONES.get(sender, [])

    historial.append({"role": "user", "content": user_message})

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=historial,
    )

    respuesta = message.content[0].text
    historial.append({"role": "assistant", "content": respuesta})

    # Recortamos el historial si se pasa del límite, para no acumular
    # infinitamente ni gastar de más en cada llamada.
    CONVERSACIONES[sender] = historial[-MAX_HISTORIAL:]

    return respuesta


@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("Webhook verificado correctamente.")
        return challenge, 200
    else:
        print("Falló la verificación del webhook.")
        return "Token inválido", 403


@app.route("/webhook", methods=["POST"])
def receive_message():
    data = request.get_json()

    try:
        entry = data["entry"][0]
        change = entry["changes"][0]["value"]

        if "messages" in change:
            message = change["messages"][0]
            sender = message["from"]
            text = message.get("text", {}).get("body", "")

            # Meta manda el timestamp del mensaje en segundos (epoch, como string).
            timestamp_mensaje = int(message.get("timestamp", time.time()))
            antiguedad = time.time() - timestamp_mensaje

            if antiguedad > ANTIGUEDAD_MAXIMA_SEGUNDOS:
                print(
                    f"Ignorando mensaje viejo de {sender} "
                    f"(antigüedad: {int(antiguedad)}s): {text}"
                )
                return jsonify(status="ok"), 200

            print(f"De {sender}: {text}")

            if text:
                respuesta = get_llm_response(sender, text)

                texto_pedido, pedido_actual = procesar_mensaje_para_pedido(
                    numero=sender,
                    mensaje=text,
                    historial_reciente=CONVERSACIONES.get(sender, []),
                    catalogo=CATALOGO,
                    numero_dueno=NUMERO_DUENIO_HUELLA,
                    funcion_enviar_whatsapp=send_whatsapp_message,
                )

                if texto_pedido:
                    respuesta = texto_pedido

                print(f"Respondiendo: {respuesta}")
                send_whatsapp_message(sender, respuesta)

    except (KeyError, IndexError) as e:
        print("No era un mensaje de texto normal, o vino vacío:", e)

    return jsonify(status="ok"), 200

            print(f"De {sender}: {text}")

            if text:
                respuesta = get_llm_response(sender, text)

                texto_pedido, pedido_actual = procesar_mensaje_para_pedido(
                    numero=sender,
                    mensaje=text,
                    historial_reciente=CONVERSACIONES.get(sender, []),
                    catalogo=CATALOGO,
                    numero_dueno=NUMERO_DUENIO_HUELLA,
                    funcion_enviar_whatsapp=send_whatsapp_message,
                )

                if texto_pedido:
                    respuesta = texto_pedido

                print(f"Respondiendo: {respuesta}")
                send_whatsapp_message(sender, respuesta)

    except (KeyError, IndexError) as e:
        print("No era un mensaje de texto normal, o vino vacío:", e)

    return jsonify(status="ok"), 200


@app.route("/debug/conversaciones", methods=["GET"])
def ver_conversaciones():
    """Ruta de debug: te deja ver en el navegador el historial guardado
    de cada cliente. Solo para desarrollo — NUNCA dejar esto expuesto así
    en un bot real (expone conversaciones de clientes sin autenticación)."""
    return jsonify(CONVERSACIONES)


if __name__ == "__main__":
    app.run(port=5000, debug=True)