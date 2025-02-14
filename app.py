import streamlit as st
from openai import OpenAI
import os
from dotenv import load_dotenv
from assistant import get_assistant_answer
import base64
import pdfplumber
import docx
import pytesseract
from PIL import Image
from datetime import datetime
from recordatorios import agendar_turno_y_programar_recordatorios
from database import get_appointment
import re
import pytz  # Para trabajar con zona horaria

# Inicialización del cliente OpenAI
openai_api_key = st.secrets["OPENAI_API_KEY"]
if openai_api_key:
    openai_client = OpenAI(api_key=openai_api_key)
    if openai_client:
        print("OpenAI client created.")
else:
    st.error("Failed to load OpenAI API key")
    st.stop()

# Zona horaria de Argentina
ARG_TZ = pytz.timezone("America/Argentina/Buenos_Aires")

# Función auxiliar para extraer la información del turno desde el mensaje
def extract_appointment_info(message: str):
    """
    Extrae patient_name, day, month y hour de un mensaje que siga el patrón:
      "agendale un turno a <patient> para el <day> de <mes> a las <hour> Hs"
    Retorna una tupla (patient_key, patient_name, appointment_datetime) o None si no se pudo extraer.
    La fecha se crea con la zona horaria de Argentina.
    """
    pattern = r"agendale un turno a\s+(\w+)\s+para el\s+(\d{1,2})\s+de\s+(\w+)\s+a las\s+(\d{1,2})"
    match = re.search(pattern, message, re.IGNORECASE)
    if match:
        patient_name = match.group(1).strip()
        day = int(match.group(2))
        month_str = match.group(3).lower()
        hour = int(match.group(4))
        months = {
            "enero": 1,
            "febrero": 2,
            "marzo": 3,
            "abril": 4,
            "mayo": 5,
            "junio": 6,
            "julio": 7,
            "agosto": 8,
            "septiembre": 9,
            "octubre": 10,
            "noviembre": 11,
            "diciembre": 12
        }
        month = months.get(month_str)
        if not month:
            return None
        now = datetime.now(ARG_TZ)
        # Se crea el turno y se localiza en la zona de Argentina
        try:
            appointment_dt = ARG_TZ.localize(datetime(now.year, month, day, hour, 0))
        except Exception as e:
            print("Error al localizar fecha:", e)
            return None
        # Si la fecha ya pasó, se asume para el próximo año
        if appointment_dt < now:
            appointment_dt = ARG_TZ.localize(datetime(now.year + 1, month, day, hour, 0))
        patient_key = patient_name.lower()
        return patient_key, patient_name, appointment_dt
    return None

def main():
    st.set_page_config(page_title="Argo", page_icon="🧠")
    st.title("Argo 🧠")
    st.write("Asistente IA - Centro de Entrenamiento Marangoni")

    # Autenticación
    password = st.text_input("App Password", type="password")
    if not password:
        st.info("Por favor, ingrese la clave de la aplicación.", icon="🗝️")
        st.stop()
    else:
        if password != st.secrets["app_password"]:
            st.info("La clave provista es incorrecta.", icon="🗝️")
            st.stop()

    if "thread_id" not in st.session_state:
        st.session_state.thread_id = None
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "archivo_context" not in st.session_state:
        st.session_state.archivo_context = None
    if "ejercicios_fisicos" not in st.session_state:
        try:
            with open("ejercicios_fisicos.txt", "r", encoding="utf-8") as f:
                st.session_state.ejercicios_fisicos = f.read()
        except FileNotFoundError:
            st.session_state.ejercicios_fisicos = None

    if "ejercicios_cognitivos" not in st.session_state:
        try:
            with open("ejercicios_cognitivos.txt", "r", encoding="utf-8") as f:
                st.session_state.ejercicios_cognitivos = f.read()
        except FileNotFoundError:
            st.session_state.ejercicios_cognitivos = None

    file = st.file_uploader("", type=["pdf", "docx", "jpg", "jpeg", "png"], label_visibility="collapsed")
    if file:
        if file.type == "application/pdf":
            try:
                with pdfplumber.open(file) as pdf:
                    pages_text = [p.extract_text() or "" for p in pdf.pages]
                st.session_state.archivo_context = "\n".join(pages_text)
                st.success("PDF procesado.")
            except Exception as e:
                st.warning(f"Error al procesar PDF: {e}")
        elif file.type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            try:
                doc_file = docx.Document(file)
                extracted_text = "\n".join(para.text for para in doc_file.paragraphs)
                st.session_state.archivo_context = extracted_text
                st.success("DOCX procesado.")
            except Exception as e:
                st.warning(f"Error al procesar DOCX: {e}")
        else:
            try:
                image = Image.open(file)
                ocr_text = pytesseract.image_to_string(image)
                st.session_state.archivo_context = ocr_text
                st.success("Imagen procesada con OCR.")
            except Exception as e:
                st.warning(f"Error al procesar la imagen: {e}")

    if st.session_state.archivo_context:
        if st.button("Eliminar archivo"):
            st.session_state.archivo_context = None
            st.success("Archivo descartado.")

    if len(st.session_state.messages) == 0:
        initial_message = "Hola, soy Argo. ¿En qué puedo ayudarte hoy?"
        st.session_state.messages.append({"role": "assistant", "content": initial_message})

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    user_input = st.chat_input("Escribe tu mensaje aquí...")
    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        if "agendale un turno" in user_input.lower():
            info = extract_appointment_info(user_input)
            if info is None:
                respuesta = "No pude extraer la información del turno. Por favor, asegúrate de usar el formato: 'agendale un turno a [nombre] para el [día] de [mes] a las [hora] Hs'."
                response = {}
            else:
                patient_key, patient_name, appointment_dt = info
                patient_data = get_appointment(patient_key)
                if patient_data is None:
                    respuesta = f"El paciente {patient_name} no se encuentra en la base de datos. Por favor, regístralo antes de agendar un turno."
                    response = {}
                else:
                    patient_whatsapp = patient_data.get("whatsapp")
                    agendar_turno_y_programar_recordatorios(patient_key, patient_name, patient_whatsapp, appointment_dt)
                    respuesta = f"Turno agendado para {patient_name} el {appointment_dt.strftime('%d/%m/%Y a las %H:%M')}. Se ha enviado un WhatsApp de confirmación."
                    response = {}
        else:
            final_input = user_input
            if st.session_state.archivo_context:
                final_input += f"\n\n[Contenido del archivo subido]:\n{st.session_state['archivo_context']}"
            
            # Incorporar la base de datos de ejercicios según lo solicitado en el mensaje
            user_input_lower = user_input.lower()
            if "planificar" in user_input_lower:
                if st.session_state.ejercicios_fisicos:
                    final_input += f"\n\n[Ejercicios físicos]:\n{st.session_state.ejercicios_fisicos}"
                if st.session_state.ejercicios_cognitivos:
                    final_input += f"\n\n[Ejercicios cognitivos]:\n{st.session_state.ejercicios_cognitivos}"
            else:
                agregado = False
                if "cognitivo" in user_input_lower:
                    if st.session_state.ejercicios_cognitivos:
                        final_input += f"\n\n[Ejercicios cognitivos]:\n{st.session_state.ejercicios_cognitivos}"
                        agregado = True
                if "fisico" in user_input_lower or "físico" in user_input_lower:
                    if st.session_state.ejercicios_fisicos:
                        final_input += f"\n\n[Ejercicios físicos]:\n{st.session_state.ejercicios_fisicos}"
                        agregado = True
                if not agregado and "ejercicios" in user_input_lower:
                    if st.session_state.ejercicios_fisicos:
                        final_input += f"\n\n[Ejercicios físicos]:\n{st.session_state.ejercicios_fisicos}"
                    if st.session_state.ejercicios_cognitivos:
                        final_input += f"\n\n[Ejercicios cognitivos]:\n{st.session_state.ejercicios_cognitivos}"
            
            response = get_assistant_answer(client=openai_client, user_msg=final_input, thread_id=st.session_state.thread_id)
            respuesta = response["assistant_answer_text"]
            st.session_state.thread_id = response["thread_id"]

        st.session_state.messages.append({"role": "assistant", "content": respuesta})
        with st.chat_message("assistant"):
            st.markdown(respuesta)

        if response.get("tool_output_details") and "pdf_base64" in response["tool_output_details"]:
            pdf_base64 = response["tool_output_details"]["pdf_base64"]
            pdf_data = base64.b64decode(pdf_base64)
            st.session_state.messages.append({"role": "assistant", "content": "Aquí tienes tu informe."})
            with st.chat_message("assistant"):
                st.markdown("### Descargar Informe Pre-Post")
                st.download_button(label="Descargar PDF", data=pdf_data, file_name="informe_prepost.pdf", mime="application/pdf")

if __name__ == '__main__':
    main()
