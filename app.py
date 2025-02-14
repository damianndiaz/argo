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
import random  # Para selección aleatoria


def parse_rutina_request(texto):
    """
    Extrae un diccionario con la cantidad de ejercicios solicitados para cada categoría.
    Ejemplo: "2 ejercicios de zona media, 3 de fuerza, 2 enfocados en el rugby y 3 de cognitivos"
    devolvería: {"Zona Media": 2, "Fuerza": 3, "Deporte": 2, "Cognitivos": 3}
    """
    patrones = {
        "Zona Media": r"(\d+)\s*ejercicios?\s*de\s*zona\s*media",
        "Fuerza": r"(\d+)\s*ejercicios?\s*de\s*fuerza",
        # Para Deporte se acepta tanto "de deporte(s)" como "enfocados en (el) rugby" o "de rugby"
        "Deporte": r"(\d+)\s*(?:ejercicios?\s*(?:de\s*deporte[s]?|enfocados\s*(?:en\s*)?(?:rugby)))",
        "Cognitivos": r"(\d+)\s*ejercicios?\s*de\s*cognitivo[s]?"
    }
    resultados = {}
    for categoria, patron in patrones.items():
        match = re.search(patron, texto, re.IGNORECASE)
        if match:
            resultados[categoria] = int(match.group(1))
    return resultados

def get_physical_exercises_by_category(texto):
    """
    Procesa el archivo de ejercicios físicos y devuelve un diccionario con listas por categoría.
    Se esperan secciones cuyo nombre sea exactamente: "Zona Media", "Fuerza" y "Deporte".
    """
    categorias_interes = {"Zona Media", "Fuerza", "Deporte"}
    ejercicios = {cat: [] for cat in categorias_interes}
    current_cat = None
    lines = texto.splitlines()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Si la línea coincide con alguna categoría de interés, actualizamos current_cat
        if line in categorias_interes:
            current_cat = line
            continue
        # Si tenemos una categoría activa, agregamos la línea
        if current_cat:
            ejercicios[current_cat].append(line)
    return ejercicios

def get_cognitive_exercises(texto):
    """
    Procesa el archivo de ejercicios cognitivos y devuelve una lista de ejercicios.
    Se omite la cabecera si existe (por ejemplo, líneas que comiencen con "-Cognitivo").
    """
    lines = texto.splitlines()
    ejercicios = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith("-cognit"):
            continue
        ejercicios.append(line)
    return ejercicios

def armar_rutina(solicitud_texto, fisicos_text, cognitivos_text):
    """
    Dada la solicitud del usuario (texto que indica cantidades por categoría) y los contenidos de
    los archivos, arma una rutina seleccionando aleatoriamente los ejercicios solicitados.
    """
    cantidades = parse_rutina_request(solicitud_texto)
    rutina = "Aquí tienes tu planificación:\n\n"
    # Procesar ejercicios físicos
    if fisicos_text:
        fisicos_dict = get_physical_exercises_by_category(fisicos_text)
        for categoria in ["Zona Media", "Fuerza", "Deporte"]:
            if categoria in cantidades:
                cantidad = cantidades[categoria]
                disponibles = fisicos_dict.get(categoria, [])
                if disponibles:
                    if len(disponibles) < cantidad:
                        seleccionados = disponibles  # si no hay suficientes, tomar todos
                    else:
                        seleccionados = random.sample(disponibles, cantidad)
                    rutina += f"**{categoria}**:\n" + "\n".join(f"- {ej}" for ej in seleccionados) + "\n\n"
    # Procesar ejercicios cognitivos
    if cognitivos_text and "Cognitivos" in cantidades:
        cognitivos_list = get_cognitive_exercises(cognitivos_text)
        cantidad = cantidades["Cognitivos"]
        if cognitivos_list:
            if len(cognitivos_list) < cantidad:
                seleccionados = cognitivos_list
            else:
                seleccionados = random.sample(cognitivos_list, cantidad)
            rutina += "**Cognitivos**:\n" + "\n".join(f"- {ej}" for ej in seleccionados) + "\n\n"
    if rutina.strip() == "Aquí tienes tu planificación:":
        rutina += "No se pudieron seleccionar ejercicios. Verifica la solicitud y el contenido de los archivos."
    return rutina
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
      "agendale un turno a <patient> para el <día> de <mes> a las <hora> Hs"
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

        # Si el mensaje incluye una solicitud de turno, se procesa como turno
        if "agendale un turno" in user_input.lower():
            info = extract_appointment_info(user_input)
            if info is None:
                respuesta = ("No pude extraer la información del turno. "
                             "Asegúrate de usar el formato: 'agendale un turno a [nombre] "
                             "para el [día] de [mes] a las [hora] Hs'.")
                response = {}
            else:
                patient_key, patient_name, appointment_dt = info
                patient_data = get_appointment(patient_key)
                if patient_data is None:
                    respuesta = (f"El paciente {patient_name} no se encuentra en la base de datos. "
                                 "Por favor, regístralo antes de agendar un turno.")
                    response = {}
                else:
                    patient_whatsapp = patient_data.get("whatsapp")
                    agendar_turno_y_programar_recordatorios(patient_key, patient_name, patient_whatsapp, appointment_dt)
                    respuesta = (f"Turno agendado para {patient_name} el "
                                 f"{appointment_dt.strftime('%d/%m/%Y a las %H:%M')}. Se ha enviado un WhatsApp de confirmación.")
                    response = {}
        # Si el mensaje solicita una rutina (por ejemplo, incluye la palabra "rutina")
        elif "rutina" in user_input.lower():
            # Se espera que el usuario indique cantidades por categoría (ejemplo: "2 ejercicios de zona media, 3 de fuerza, 2 de deportes y 3 cognitivos")
            rutina_plan = armar_rutina(user_input, st.session_state.ejercicios_fisicos or "", st.session_state.ejercicios_cognitivos or "")
            # En este caso, en lugar de enviar el prompt al asistente, Argo responde con la planificación generada.
            respuesta = rutina_plan
            response = {}
        else:
            # Si no es turno ni rutina, se arma el prompt "normal"
            final_input = user_input
            if st.session_state.archivo_context:
                final_input += f"\n\n[Contenido del archivo subido]:\n{st.session_state['archivo_context']}"
            
            # Incorporar ejemplos de ejercicios si se menciona "planificar" o "ejercicios" (se envía solo un subconjunto)
            user_input_lower = user_input.lower()
            if "planificar" in user_input_lower:
                if st.session_state.ejercicios_fisicos:
                    # Selecciona 5 ejercicios de cada base (ejemplo)
                    lines_fisicos = st.session_state.ejercicios_fisicos.splitlines()
                    lines_fisicos = [line.strip() for line in lines_fisicos if line.strip()]
                    subset_fisicos = "\n".join(random.sample(lines_fisicos, min(5, len(lines_fisicos))))
                    final_input += f"\n\n[Ejercicios físicos (ejemplo)]:\n{subset_fisicos}"
                if st.session_state.ejercicios_cognitivos:
                    lines_cognitivos = st.session_state.ejercicios_cognitivos.splitlines()
                    lines_cognitivos = [line.strip() for line in lines_cognitivos if line.strip()]
                    subset_cognitivos = "\n".join(random.sample(lines_cognitivos, min(5, len(lines_cognitivos))))
                    final_input += f"\n\n[Ejercicios cognitivos (ejemplo)]:\n{subset_cognitivos}"
            else:
                agregado = False
                if "cognitiv" in user_input_lower:
                    if st.session_state.ejercicios_cognitivos:
                        lines_cognitivos = st.session_state.ejercicios_cognitivos.splitlines()
                        lines_cognitivos = [line.strip() for line in lines_cognitivos if line.strip()]
                        subset_cognitivos = "\n".join(random.sample(lines_cognitivos, min(5, len(lines_cognitivos))))
                        final_input += f"\n\n[Ejercicios cognitivos (ejemplo)]:\n{subset_cognitivos}"
                        agregado = True
                if "fisic" in user_input_lower or "físic" in user_input_lower:
                    if st.session_state.ejercicios_fisicos:
                        lines_fisicos = st.session_state.ejercicios_fisicos.splitlines()
                        lines_fisicos = [line.strip() for line in lines_fisicos if line.strip()]
                        subset_fisicos = "\n".join(random.sample(lines_fisicos, min(5, len(lines_fisicos))))
                        final_input += f"\n\n[Ejercicios físicos (ejemplo)]:\n{subset_fisicos}"
                        agregado = True
                if not agregado and "ejercici" in user_input_lower:
                    if st.session_state.ejercicios_fisicos:
                        lines_fisicos = st.session_state.ejercicios_fisicos.splitlines()
                        lines_fisicos = [line.strip() for line in lines_fisicos if line.strip()]
                        subset_fisicos = "\n".join(random.sample(lines_fisicos, min(5, len(lines_fisicos))))
                        final_input += f"\n\n[Ejercicios físicos (ejemplo)]:\n{subset_fisicos}"
                    if st.session_state.ejercicios_cognitivos:
                        lines_cognitivos = st.session_state.ejercicios_cognitivos.splitlines()
                        lines_cognitivos = [line.strip() for line in lines_cognitivos if line.strip()]
                        subset_cognitivos = "\n".join(random.sample(lines_cognitivos, min(5, len(lines_cognitivos))))
                        final_input += f"\n\n[Ejercicios cognitivos (ejemplo)]:\n{subset_cognitivos}"
            
            # Se omite mostrar el prompt de depuración al usuario
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
