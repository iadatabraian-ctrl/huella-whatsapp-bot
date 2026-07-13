"""
test_conversacion.py — Simula una conversación de WhatsApp completa contra
tu webhook local, para que Claude pueda revisar la coherencia de las
respuestas pegando el output de la consola.

Uso:
1. Dejá corriendo `python app.py` en otra terminal.
2. En una terminal nueva, en la misma carpeta: python test_conversacion.py
3. Copiá TODO el output de la consola donde corre app.py (los "De: ..." y
   "Respondiendo: ...") y pegaselo a Claude en el chat.

No usa WhatsApp real ni Meta — solo le pega directo a tu Flask local con
el mismo formato de JSON que manda Meta, así tu webhook lo procesa igual.
"""

import requests
import time

URL = "http://127.0.0.1:5000/webhook"
NUMERO_SIMULADO = "099999999"  # número de prueba, no uses uno real

# Conversación de prueba: ajustá los mensajes para el escenario que quieras
# probar. Cada string es un mensaje "del cliente".
MENSAJES = [
    "Hola",
    "Quiero una placa para mi perro",
    "Línea Starter, color rojo, se llama Rocco",
    "Cantidad 1",
    "Envío a Rivera, calle Sarandí 123",
    "Pago con transferencia",
    "El nombre en blanco",
    "Mi número es 098765432",
    "Sí",
]

def payload(texto, wamid_sufijo):
    """Arma el mismo JSON que manda Meta al webhook."""
    return {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": NUMERO_SIMULADO,
                        "id": f"wamid.TEST{wamid_sufijo}",
                        "text": {"body": texto},
                        "type": "text",
                    }]
                }
            }]
        }]
    }


def main():
    print(f"=== Simulando conversación con {len(MENSAJES)} mensajes ===\n")
    for i, texto in enumerate(MENSAJES):
        print(f">>> Enviando mensaje {i+1}: \"{texto}\"")
        resp = requests.post(URL, json=payload(texto, i))
        print(f"    Status: {resp.status_code}")
        time.sleep(1.5)  # da tiempo a que se procese y se vea en la consola de app.py
    print("\n=== Listo. Revisá la consola donde corre app.py para ver las respuestas. ===")


if __name__ == "__main__":
    main()
