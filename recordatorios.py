from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from twilio.rest import Client
import time
from database import upsert_appointment
import pytz
import streamlit as st

# Zona horaria Argentina
ARG_TZ = pytz.timezone("America/Argentina/Buenos_Aires")

def get_twilio_client_and_number():
    account_sid = st.secrets.twilio.account_sid
    auth_token = st.secrets.twilio.auth_token
    whatsapp_number = st.secrets.twilio.whatsapp_number
    client = Client(account_sid, auth_token)
    return client, whatsapp_number

def enviar_whatsapp(mensaje: str, destino: str, max_retries=3, delay=2):
    account_sid = st.secrets.twilio.account_sid
    auth_token = st.secrets.twilio.auth_token
    whatsapp_number = st.secrets.twilio.whatsapp_number
    client = Client(account_sid, auth_token)
    
    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                body=mensaje,
                from_=whatsapp_number,
                to=f"whatsapp:{destino}"
            )
            print(f"Mensaje enviado a {destino}: SID {response.sid}")
            return response.sid
        except Exception as e:
            print(f"Error al enviar WhatsApp (Intento {attempt+1}/{max_retries}):", e)
            time.sleep(delay)
    print("No se pudo enviar el mensaje tras varios intentos.")
    return None

def generar_mensaje_motivacional(tipo: str, patient_name: str) -> str:
    if tipo == "confirmacion":
        return f"¡Hola {patient_name}! Tu turno ha sido agendado correctamente. ¡Estamos emocionados de verte en el Centro de Entrenamiento Marangoni!"
    elif tipo == "recordatorio_24h":
        return f"Recordatorio: Hola {patient_name}, faltan 24 horas para tu turno. ¡Preparate y mantené esa energía positiva!"
    elif tipo == "recordatorio_3h":
        return f"¡Che, ya falta poco para tu turno, {patient_name}! Te esperamos en el Centro de Entrenamiento Marangoni. ¡No pierdas el impulso!"
    else:
        return f"Hola {patient_name}, este es un recordatorio."

scheduler = BackgroundScheduler()
scheduler.start()

def agendar_turno_y_programar_recordatorios(patient_key: str, patient_name: str, patient_whatsapp: str, appointment_datetime: datetime):
    upsert_appointment(patient_key, patient_name, patient_whatsapp, appointment_datetime)
    
    mensaje_confirmacion = generar_mensaje_motivacional("confirmacion", patient_name)
    enviar_whatsapp(mensaje_confirmacion, patient_whatsapp)

    now = datetime.now(ARG_TZ)
    reminder_24h = appointment_datetime - timedelta(hours=24)
    reminder_3h = appointment_datetime - timedelta(hours=3)

    if reminder_24h > now:
        scheduler.add_job(
            enviar_whatsapp,
            'date',
            run_date=reminder_24h,
            args=[generar_mensaje_motivacional("recordatorio_24h", patient_name), patient_whatsapp],
            id=f"recordatorio_24h_{patient_key}_{appointment_datetime.timestamp()}",
            replace_existing=True
        )
        print(f"Recordatorio 24h programado para {reminder_24h}")
    else:
        print("El horario para el recordatorio de 24h ya pasó.")

    if reminder_3h > now:
        scheduler.add_job(
            enviar_whatsapp,
            'date',
            run_date=reminder_3h,
            args=[generar_mensaje_motivacional("recordatorio_3h", patient_name), patient_whatsapp],
            id=f"recordatorio_3h_{patient_key}_{appointment_datetime.timestamp()}",
            replace_existing=True
        )
        print(f"Recordatorio 3h programado para {reminder_3h}")
    else:
        print("El horario para el recordatorio de 3h ya pasó.")

    print("Turno agendado y recordatorios programados.")
