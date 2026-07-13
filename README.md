# Huella Bot — Asistente de WhatsApp con IA para toma de pedidos

Bot conversacional de WhatsApp para **Huella** (@huella_saltouy), un negocio de placas
personalizadas para mascotas en Salto, Uruguay. Atiende consultas de catálogo,
precios y tiempos de entrega, y además **toma pedidos completos de forma
estructurada**, validando cada dato antes de confirmar y notificando al dueño
del negocio en tiempo real.

> Proyecto de portfolio construido como caso de uso real para un negocio local,
> usando la API oficial de WhatsApp (Meta Cloud API) + Claude (Anthropic) como
> motor conversacional.

## Arquitectura

```
Cliente (WhatsApp)
      │
      ▼
Meta Cloud API ──▶ Webhook Flask (app.py)
                          │
                          ├──▶ Claude API (capa conversacional)
                          │      responde consultas de catálogo, precios, etc.
                          │
                          └──▶ Lógica de pedidos (pedidos.py)
                                 ├─ extrae datos del pedido con Claude (JSON estructurado)
                                 ├─ valida que estén TODOS los campos obligatorios
                                 ├─ guarda el pedido confirmado en JSON
                                 └─ notifica al dueño por WhatsApp
```

Dos "cerebros" separados corren sobre cada mensaje entrante:
1. **Capa conversacional** — charla natural, vende, responde dudas del catálogo.
2. **Capa estructurada** — extrae y valida los datos del pedido en paralelo, y
   solo ella tiene la autoridad de decir "pedido confirmado".

## Decisiones técnicas

- **Separación de responsabilidades**: la lógica conversacional (`app.py`) y la
  lógica de negocio de pedidos (`pedidos.py`) están desacopladas. Esto evitó un
  bug real durante el desarrollo: el bot conversacional podía "sonar" como que
  había confirmado un pedido sin que el sistema de pedidos hubiera validado
  realmente los datos. La solución fue instruir explícitamente a la capa
  conversacional para que nunca declare un pedido confirmado por su cuenta —
  esa es la única función exclusiva de `pedidos.py`.

- **Extracción de datos vía LLM, no regex**: en vez de parsear mensajes con
  reglas fijas, se le pide a Claude que extraiga un JSON estructurado de cada
  mensaje. Esto permite manejar lenguaje natural variado ("mi perrito se llama
  Bobi", "quiero envío a Rivera") sin reglas hardcodeadas.

- **Anti-alucinación de datos**: el prompt de extracción prohíbe explícitamente
  que el modelo "invente" o asuma valores no dichos por el cliente (ej. asumir
  forma de pago "efectivo" por default). Ningún campo se completa salvo que el
  cliente lo haya dicho explícitamente.

- **Detección de tipo de envío sin lista hardcodeada**: para decidir si un
  envío es local (Salto) o requiere agencia (DAC a otras ciudades), se usa el
  conocimiento geográfico del propio modelo en vez de mantener una lista
  manual de todas las ciudades y pueblos de Uruguay.

- **Notificación automática al dueño**: al confirmarse un pedido, se reutiliza
  la misma función de envío de WhatsApp para avisarle al dueño del negocio con
  el resumen completo — sin esto, un pedido confirmado quedaría "silencioso"
  en un archivo JSON que nadie mira.

## Campos que valida un pedido antes de confirmarse

| Campo | Descripción |
|---|---|
| `producto` | Línea de placa elegida |
| `color` | Color de la placa |
| `cantidad` | Cantidad de unidades |
| `nombre_mascota` | Nombre grabado en la placa |
| `color_nombre` | Color del texto grabado |
| `telefono_grabado` | Teléfono a grabar atrás (puede diferir del número de WhatsApp) |
| `direccion_envio` | Dirección exacta (calle y número — una ciudad sola no alcanza) |
| `tipo_envio` | Local (Salto) o DAC (resto del país) |
| `forma_pago` | Transferencia o efectivo |

## Setup

1. Clonar el repo e instalar dependencias:
   ```
   pip install flask requests python-dotenv anthropic
   ```

2. Crear un archivo `.env` en la raíz con:
   ```
   WHATSAPP_TOKEN=tu_token_de_meta
   PHONE_NUMBER_ID=tu_phone_number_id
   VERIFY_TOKEN=un_token_que_elijas
   ANTHROPIC_API_KEY=tu_api_key_de_anthropic
   NUMERO_DUENIO_HUELLA=numero_whatsapp_del_dueno_sin_signo_mas
   ```

3. Correr localmente:
   ```
   python app.py
   ```

4. Exponer el puerto 5000 con [ngrok](https://ngrok.com/) (o similar) para
   registrar el webhook en Meta for Developers.

## Estructura del proyecto

```
├── app.py                      # Webhook Flask + capa conversacional
├── pedidos.py                  # Lógica de extracción, validación y notificación de pedidos
├── catalogo_huella.json        # Catálogo de productos (fuente de verdad del bot)
├── pedidos_confirmados.json    # Se genera automáticamente al confirmarse pedidos
└── .env                        # Variables de entorno (no se sube al repo)
```

## Mejoras futuras

- **Costo de envío por DAC en tiempo real**: actualmente el bot informa que el
  envío es "por DAC" pero no calcula el costo exacto, porque DAC no publica
  una tabla fija de tarifas por destino (depende de un simulador dinámico sin
  API pública). Próximo paso: conseguir cotizaciones de referencia para los
  destinos más comunes y cargarlas como aproximación.
- Migrar el almacenamiento de conversaciones y pedidos de JSON/RAM a una base
  de datos (SQLite/Postgres) para persistencia real en producción.
- Panel simple (web) para que el dueño vea el historial de pedidos sin
  depender solo de las notificaciones de WhatsApp.

## Nota sobre seguridad

Este repo no incluye el archivo `.env` real ni datos de clientes reales
(`pedidos_confirmados.json`) — están excluidos vía `.gitignore`.
