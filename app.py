import streamlit as st
from openai import OpenAI
import os
from dotenv import load_dotenv
from assistant import get_assistant_answer
import base64

# Para procesar PDFs, DOCX e imágenes (si querés mantener la parte de subir archivos)
import pdfplumber
import docx
import pytesseract
from PIL import Image

openai_api_key = st.secrets["OPENAI_API_KEY"]

if openai_api_key:
    openai_client = OpenAI(api_key=openai_api_key)
    if openai_client:
        print("OpenAI client created.")
else:
    st.error("Failed to load OpenAI API key")
    st.stop()

def main():
    st.set_page_config(page_title="Argo", page_icon="🧠")
    st.title("Argo 🧠")
    st.write("Asistente IA - Centro Entrenamiento Marangoni")

    # Autenticación
    password = st.text_input("App Password", type="password")
    if not password:
        st.info("Por favor, ingrese la clave de la aplicación.", icon="🗝️")
        st.stop()
    else:
        if password != st.secrets["app_password"]:
            st.info("La clave provista es incorrecta.", icon="🗝️")
            st.stop()

    # Manejo de estado para thread_id, mensajes, y archivos
    if "thread_id" not in st.session_state:
        st.session_state.thread_id = None
    if "messages" not in st.session_state:
        st.session_state.messages = []
    # Almacena el texto del archivo subido (PDF/DOCX/IMG) si querés
    if "archivo_context" not in st.session_state:
        st.session_state.archivo_context = None
    # Almacena el texto de ejercicios.txt
    if "ejercicios_text" not in st.session_state:
        # Cargamos localmente el archivo ejercicios.txt (opcional)
        try:
            with open("ejercicios.txt", "r", encoding="utf-8") as f:
                st.session_state.ejercicios_text = f.read()
        except FileNotFoundError:
            st.session_state.ejercicios_text = None

    # --- Bloque de subida de archivos (PDF/DOCX/IMG) ---
    file = st.file_uploader(
        "",
        type=["pdf","docx","jpg","jpeg","png"],
        label_visibility="collapsed"
    )
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
            # Asumimos imagen
            try:
                image = Image.open(file)
                ocr_text = pytesseract.image_to_string(image)
                st.session_state.archivo_context = ocr_text
                st.success("Imagen procesada con OCR.")
            except Exception as e:
                st.warning(f"Error al procesar la imagen: {e}")

    # Botón para eliminar el archivo subido
    if st.session_state.archivo_context:
        if st.button("Eliminar archivo"):
            st.session_state.archivo_context = None
            st.success("Archivo descartado.")

    # Mensaje inicial si no hay ninguno
    if len(st.session_state.messages) == 0:
        initial_message = "Hola, soy Argo. ¿En qué puedo ayudarte hoy?"
        st.session_state.messages.append({"role": "assistant", "content": initial_message})

    # Mostrar historial
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Input del usuario
    user_input = st.chat_input("Escribe tu mensaje aquí...")
    if user_input:
        # 1) Empezamos con el texto original
        final_input = user_input

        # 2) Si hay un archivo subido, lo inyectamos
        if st.session_state.archivo_context:
            final_input += f"\n\n[Contenido del archivo subido]:\n{st.session_state['archivo_context']}"

        # 3) Si el usuario pide ejercicios/rutinas, inyectamos ejercicios.txt
        keywords = ["rutina","ejercicios","entrenamiento","planificar"]
        if st.session_state.ejercicios_text and any(k in user_input.lower() for k in keywords):
            final_input += f"\n\n[Lista de ejercicios permitidos]:\n{st.session_state['ejercicios_text']}"

        # Guardamos el mensaje del usuario en la conversación
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        # Llamamos al Assistant con final_input
        response = get_assistant_answer(
            client=openai_client,
            user_msg=final_input,
            thread_id=st.session_state.thread_id
        )

        answer_text = response["assistant_answer_text"]
        st.session_state.thread_id = response["thread_id"]

        # Guardamos la respuesta
        st.session_state.messages.append({"role": "assistant", "content": answer_text})
        with st.chat_message("assistant"):
            st.markdown(answer_text)

        # Chequear si se generó un PDF
        tool_output = response.get("tool_output_details")
        if tool_output and "pdf_base64" in tool_output:
            pdf_base64 = tool_output["pdf_base64"]
            pdf_data = base64.b64decode(pdf_base64)

            st.session_state.messages.append({"role": "assistant", "content": "Aquí tienes tu informe."})
            with st.chat_message("assistant"):
                st.markdown("### Descargar Informe Pre-Post")
                st.download_button(
                    label="Descargar PDF",
                    data=pdf_data,
                    file_name="informe_prepost.pdf",
                    mime="application/pdf"
                )

if __name__ == '__main__':
    main()
