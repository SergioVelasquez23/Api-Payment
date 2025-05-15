from flask import Flask, request, jsonify
from dotenv import load_dotenv
import epaycosdk.epayco as epayco
import json
import os
import requests


# Cargar variables de entorno
load_dotenv()

# Configuración de Epayco
apiKey = os.getenv("PUBLIC_KEY")
privateKey = os.getenv("PRIVATE_KEY")
lenguage = "ES"
test = True  # Cambiar a False en producción
options = {"apiKey": apiKey, "privateKey": privateKey, "test": test, "lenguage": lenguage}

# Inicializar cliente de Epayco
objepayco = epayco.Epayco(options)

# Inicializar aplicación Flask
app = Flask(__name__)

def send_email(email, bill, charge_details):
    """
    Función para enviar un correo al cliente con los detalles de la factura usando el servicio de notificaciones.
    """
    try:
        # Obtener la URL del servicio de notificaciones del archivo .env
        notification_url = os.getenv('NOTIFICATION_SERVICE_URL')

        # Manejar valores faltantes o None en charge_details['data']
        data = charge_details.get('data', {})
        valor = data.get('valor', 'N/A')
        descripcion = data.get('descripcion', 'N/A')
        estado = data.get('estado', 'N/A')
        respuesta = data.get('respuesta', 'N/A')

        # Preparar los datos para enviar al servicio de notificaciones
        email_data = {
            "recipient": email,
            "message": f"""
            Gracias por tu pago. Aquí están los detalles de tu factura:

            Número de factura: {bill}
            Valor: {valor}
            Descripción: {descripcion}
            Estado: {estado}
            Respuesta: {respuesta}

            Si tienes alguna pregunta, no dudes en contactarnos.

            Saludos,
            Tu Empresa
            """,
            "subject": f"Factura {bill} - Detalles del Pago"
        }

        # Hacer la petición al servicio de notificaciones
        response = requests.post(notification_url, json=email_data)
        
        if response.status_code == 200:
            print(f"Notificación de pago enviada exitosamente a {email}")
            return True
        else:
            try:
                error_response = response.json()
            except ValueError:
                error_response = response.text
            print(f"Error al enviar la notificación: {error_response}")
            return False


    except Exception as e:
        print(f"Error al conectar con el servicio de notificaciones: {e}")
        return False

@app.route('/charge', methods=['POST'])
def charge():
    ms_negocio = os.getenv('MS_NEGOCIO_URL')
    try:
        # Obtener datos del cliente y de la tarjeta desde el cuerpo de la solicitud
        data = request.get_json()
        if not data or not data.get('card') or not data.get('customer') or not data.get('due'):
            return jsonify({
                "error": "Datos incompletos",
                "details": "Se requieren los datos de tarjeta, cliente y cuota"
            }), 400

        # Generar token de la tarjeta
        token_card = objepayco.token.create({
            "card[number]": data['card']['number'],
            "card[exp_year]": data['card']['exp_year'],
            "card[exp_month]": data['card']['exp_month'],
            "card[cvc]": data['card']['cvc']
        })

        if not token_card.get('status', False):
            return jsonify({"error": "Error al generar el token", "details": token_card}), 400

        # Crear cliente en Epayco
        customer = objepayco.customer.create({
            "token_card": token_card['id'],
            "name": data['customer']['name'],
            "last_name": data['customer']['last_name'],
            "email": data['customer']['email'],
            "phone": data['customer']['phone'],
            "default": True
        })

        if not customer.get('status', False):
            return jsonify({"error": "Error al crear el cliente", "details": customer}), 400

        customer_id = customer['data']['customerId']

        # Preparar información de pago
        payment_info = {
            "token_card": token_card['id'],
            "customer_id": customer_id,
            "doc_type": "CC",
            "doc_number": data['customer']['doc_number'],
            "name": data['customer']['name'],
            "last_name": data['customer']['last_name'],
            "email": data['customer']['email'],
            "bill": data['due']['id_servicio'],
            "description": data.get('description', f"Pago de cuota #{data['due']['id']}"),
            "value": int(data['due']['valor']),
            "tax": int(data.get('tax', 0)),
            "tax_base": int(data.get('tax_base', data['due']['valor'])),
            "currency": "COP",
            "dues": int(data.get('dues', 1)),
            "ip": request.remote_addr,
            "url_response": os.getenv('URL_RESPONSE', 'https://tudominio.com/respuesta'),
            "url_confirmation": os.getenv('URL_CONFIRMATION', 'https://tudominio.com/confirmacion'),
            "method_confirmation": "GET",
            "use_default_card_customer": True
        }

        # Crear cargo
        charge = objepayco.charge.create(payment_info)
        
        if not charge.get('status', False):
            return jsonify({"error": "Error en el cargo", "details": charge}), 400

        # Crear factura en ms-negocio (solo con los campos necesarios)
        factura = {
            "detalle": payment_info['description'],
            "id_cuota": data['due']['id']
        }
        
        # Enviar la factura a ms-negocio
        factura_response = requests.post(f"{ms_negocio}/facturas", json=factura)
        
        if factura_response.status_code != 200:
            print(f"Error al crear la factura: {factura_response.text}")
            return jsonify({
                "error": "Error al crear la factura",
                "details": factura_response.json()
            }), 500

        # Enviar correo al cliente con los detalles
        email_sent = send_email(
            data['customer']['email'],
            factura_response.json().get('id'),
            charge
        )

        # Formatear la respuesta
        response = {
            "message": "Pago procesado exitosamente",
            "email_sent": email_sent,
            "payment_details": charge['data'],
            "factura": factura_response.json()
        }

        return jsonify(response), 200

    except Exception as e:
        print(f"Error procesando la solicitud: {str(e)}")
        return jsonify({
            "error": "Error interno del servidor",
            "details": str(e)
        }), 500

if __name__ == '__main__':
    app.run(port=5001, debug=True)