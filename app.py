import streamlit as st
from openai import OpenAI
import os
from dotenv import load_dotenv
from assistant import get_assistant_answer
import base64

# Para procesar PDFs, DOCX e imágenes:
import pdfplumber
import docx
import pytesseract
from PIL import Image

# Cargá la API key de la forma que uses (acá asumo en st.secrets)
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
    st.write("Asistente IA Centro Entrenamiento Marangoni")

    # Autenticación
    password = st.text_input("App Password", type="password")
    if not password:
        st.info("Por favor, ingrese la clave de la aplicación.", icon="🗝️")
        st.stop()
    else:
        if password != st.secrets["app_password"]:
            st.info("La clave provista es incorrecta.", icon="🗝️")
            st.stop()

    # Manejo de estado
    if "thread_id" not in st.session_state:
        st.session_state.thread_id = None

    if "messages" not in st.session_state:
        st.session_state.messages = []

        # Almacena el texto del archivo subido (si existe).
    # Cuando sea None, significa que no hay archivo cargado.
    if "archivo_context" not in st.session_state:
        st.session_state.archivo_context = None

    # Bloque para subir y descartar archivos
    st.markdown("Elige un archivo para que Argo lo tenga en cuenta")
    file = st.file_uploader(
        "Elige un archivo para que Argo lo tenga en cuenta",
        type=["pdf", "docx", "jpg", "jpeg", "png"],
        label_visibility="collapsed"
    )
    if file:
        # Procesar según tipo
        if file.type == "application/pdf":
            try:
                with pdfplumber.open(file) as pdf:
                    pages_text = [p.extract_text() or "" for p in pdf.pages]
                extracted_text = "\n".join(pages_text)
                st.session_state.archivo_context = extracted_text
                st.success("Se ha procesado el PDF y guardado en contexto.")
            except Exception as e:
                st.warning(f"Error al procesar PDF: {e}")
        elif file.type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            try:
                doc = docx.Document(file)
                extracted_text = "\n".join(para.text for para in doc.paragraphs)
                st.session_state.archivo_context = extracted_text
                st.success("Se ha procesado el DOCX y guardado en contexto.")
            except Exception as e:
                st.warning(f"Error al procesar DOCX: {e}")
        else:
            # Asumimos imagen (jpg, png)
            try:
                image = Image.open(file)
                ocr_text = pytesseract.image_to_string(image)
                st.session_state.archivo_context = ocr_text
                st.success("Se ha aplicado OCR a la imagen y guardado en contexto.")
            except Exception as e:
                st.warning(f"Error al procesar la imagen: {e}")
                
    # Mensaje inicial si no hay ninguno
    if len(st.session_state.messages) == 0:
        initial_message = "Hola, soy Argo. ¿En qué puedo ayudarte hoy?"
        st.session_state.messages.append({"role": "assistant", "content": initial_message})

    # Mostramos el historial de mensajes
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Input del usuario
    user_input = st.chat_input("Escribe tu mensaje aquí...")
    if user_input:
        # Si hay archivo en contexto, inyectamos su contenido al final
        # de lo que el usuario envía, para que el Assistant lo "vea".
        final_input = user_input
        if st.session_state.archivo_context:
            final_input += f"\n\n[Contexto del archivo subido]:\n{st.session_state.archivo_context}"

        # Añadimos el mensaje del usuario (como lo escribió, para mostrar en la UI)
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        # Llamamos a la función que interactúa con la Beta de Threads,
        # usando 'final_input' que incluye el texto del archivo.
        response = get_assistant_answer(
            client=openai_client,
            user_msg=final_input,  # <<< mandamos final_input
            thread_id=st.session_state.thread_id
        )

        answer_text = response["assistant_answer_text"]
        st.session_state.thread_id = response["thread_id"]

        # Añadimos la respuesta del asistente al historial
        st.session_state.messages.append({"role": "assistant", "content": answer_text})
        with st.chat_message("assistant"):
            st.markdown(answer_text)

        # Verificamos si hay un PDF en la respuesta
        tool_output = response.get("tool_output_details")
        if tool_output and "pdf_base64" in tool_output:
            pdf_base64 = tool_output["pdf_base64"]
            pdf_data = base64.b64decode(pdf_base64)

            st.session_state.messages.append({"role": "assistant", "content": "Aquí puedes descargar tu informe."})
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
