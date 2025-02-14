import json
import base64
import io
import matplotlib.pyplot as plt
from fpdf import FPDF
import os
from datetime import datetime
import pytz
from database import get_appointment
from recordatorios import agendar_turno_y_programar_recordatorios

# Zona horaria de Argentina
ARG_TZ = pytz.timezone("America/Argentina/Buenos_Aires")

def get_assistant_answer(client, user_msg: str = None, thread_id: str = None, assistant_id: str = "asst_XKvU1ulcVEy8UZd5fatnZ60c"):
    """
    Envía el mensaje del usuario a la Beta de Threads y procesa la respuesta.
    
    Flujo:
    1) Crea un thread si no existe, inyectando instrucciones internas.
    2) Agrega el mensaje del usuario.
    3) Ejecuta el Assistant y espera la respuesta.
    4) Revisa los mensajes del assistant para ver si hay un JSON con:
       - function_name="generate_prepost_report": Genera el PDF.
       - function_name="schedule_appointment": Extrae los datos y agenda el turno.
         Si el número de WhatsApp no se proporciona, devuelve un mensaje solicitándolo.
    5) Si no se detecta ninguna función especial, devuelve la respuesta textual normal.
    """
    if not thread_id:
        print("Ningún thread_id provisto, generando uno nuevo...")
        internal_instructions = (
            "Sos Argo, un médico argentino experto en entrenamiento físico, cognitivo, nutrición y neurociencias, "
            "con experiencia en el abordaje de niños, adolescentes y adultos con obesidad, TDAH y TEA. "
            "Trabajás en el Centro de Entrenamiento Marangoni (CEM), donde colaborás con entrenadores y médicos "
            "para brindar asistencia fundamentada y profesional. Mantené un tono respetuoso y claro pero evitá ser robótico.\n\n"
            "**Normas Generales**\n"
            "- Responde únicamente con información relacionada a entrenamiento físico, cognitivo, nutrición o neurociencias.\n"
            "- Ignorá términos desconocidos, fragmentos aleatorios o conceptos que no pertenezcan a tu campo.\n"
            "- Si no tenés información suficiente, respondé con: 'Actualmente no tengo información suficiente para responder con precisión.'\n\n"
            "**Respuestas con JSON (Informes Pre/Post)**\n"
            "- Si se te pide un informe Pre/Post, responde **exclusivamente** con un JSON en el siguiente formato:\n"
            "```json\n"
            "{\n"
            '  "function_name": "generate_prepost_report",\n'
            '  "arguments": {\n'
            '    "patient_name": "NOMBRE",\n'
            '    "patient_age": 9,\n'
            '    "cognitive_results": {\n'
            '      "Métrica 1": {"pre": 0, "post": 0},\n'
            '      "Métrica 2": {"pre": 0, "post": 0}\n'
            "    }\n"
            "  }\n"
            "}\n"
            "```\n"
            "- NO incluyas texto adicional.\n\n"
            "**Solicitud de Agendamiento de Turnos**\n"
            "- Si se te solicita agendar un turno, responde **exclusivamente** con un JSON en el siguiente formato:\n"
            "```json\n"
            "{\n"
            '  "function_name": "schedule_appointment",\n'
            '  "arguments": {\n'
            '    "patient_name": "NOMBRE",\n'
            '    "patient_whatsapp": "WHATSAPP_NUMBER",\n'
            '    "appointment_date": "YYYY-MM-DD",\n'
            '    "appointment_time": "HH:MM"\n'
            "  }\n"
            "}\n"
            "```\n"
            "- NO incluyas texto adicional.\n"
        )
        thread = client.beta.threads.create(
            messages=[
                {"role": "assistant", "content": internal_instructions},
                {"role": "assistant", "content": "Hola, soy Argo. ¿En qué puedo ayudarte hoy?"}
            ]
        )
        thread_id = thread.id
        print(f"Nuevo thread iniciado. ID: {thread_id}")
    else:
        print(f"El cliente proporciona thread_id y se utiliza. ID: {thread_id}")

    messages = client.beta.threads.messages.list(thread_id=thread_id)
    if (not user_msg or user_msg.strip() == "") and len(messages) == 1:
        message = client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content="Hola, me explicarías de qué forma puedes ayudarme?"
        )
        print("El usuario envía mensaje inicial vacío. Se agrega uno por default.")
    else:
        message = client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=user_msg
        )
        print(f"Mensaje del usuario: '{user_msg}' agregado al thread.")
    message_id = message.id if message else None

    if message_id and assistant_id:
        run = client.beta.threads.runs.create_and_poll(
            thread_id=thread_id,
            assistant_id=assistant_id
        )
        print("Se inicia Assistant Run...")
        if run.status == 'requires_action':
            print("Assistant Run requiere acciones.")
        if run.status == 'completed':
            print("Assistant Run finalizado.")
    else:
        print("No se encontró message_id o assistant_id.")

    all_msgs = client.beta.threads.messages.list(thread_id=thread_id).data

    # Buscar JSON para agendamiento de turnos
    schedule_confirmation_msg = None
    for msg in all_msgs:
        if msg.role == "assistant":
            parsed = try_parse_function_call(join_msg_content(msg))
            if parsed and parsed.get("function_name") == "schedule_appointment":
                fn_args = parsed["arguments"]
                patient_name = fn_args.get("patient_name", "Paciente")
                patient_whatsapp_json = fn_args.get("patient_whatsapp", "").strip()
                appointment_date = fn_args.get("appointment_date", "")
                appointment_time = fn_args.get("appointment_time", "")
                try:
                    # Parsear y localizar en la zona de Argentina
                    raw_dt = datetime.strptime(f"{appointment_date} {appointment_time}", "%Y-%m-%d %H:%M")
                    appointment_dt = ARG_TZ.localize(raw_dt)
                except Exception as e:
                    print("Error al convertir fecha y hora:", e)
                    appointment_dt = datetime.now(ARG_TZ)
                patient_key = patient_name.lower()
                patient_data = get_appointment(patient_key)
                if patient_data is None:
                    if not patient_whatsapp_json:
                        schedule_confirmation_msg = "Para agendar el turno, necesito que me proporciones tu número de Whatsapp."
                        return {
                            "thread_id": thread_id,
                            "assistant_answer_text": schedule_confirmation_msg,
                            "tool_output_details": None
                        }
                    else:
                        patient_whatsapp = patient_whatsapp_json
                else:
                    patient_whatsapp = patient_data.get("whatsapp")
                agendar_turno_y_programar_recordatorios(patient_key, patient_name, patient_whatsapp, appointment_dt)
                schedule_confirmation_msg = f"Turno agendado para {patient_name} el {appointment_dt.strftime('%d/%m/%Y a las %H:%M')}. Se ha enviado un WhatsApp de confirmación."
                break

    if schedule_confirmation_msg:
        return {
            "thread_id": thread_id,
            "assistant_answer_text": schedule_confirmation_msg,
            "tool_output_details": None
        }

    # Generación del informe pre-post: se recorre en orden inverso para capturar la solicitud más reciente.
    pdf_base64 = None
    pdf_confirmation_msg = None
    for msg in reversed(all_msgs):
        if msg.role == "assistant":
            parsed = try_parse_function_call(join_msg_content(msg))
            if parsed and parsed.get("function_name") == "generate_prepost_report":
                fn_args = parsed["arguments"]
                patient_name = fn_args.get("patient_name", "Paciente")
                patient_age = fn_args.get("patient_age", 0)
                cog_results = fn_args.get("cognitive_results", {})
                pdf_bytes = generate_informe_prepost_cem_3pages(patient_name, patient_age, cog_results)
                pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8")
                pdf_confirmation_msg = f"¡Aquí tienes tu informe pre-post para {patient_name} (edad {patient_age})!"
                break

    if pdf_base64:
        client.beta.threads.messages.create(
            thread_id=thread_id,
            role="assistant",
            content=pdf_confirmation_msg
        )
        final_answer = f"¡Aquí tienes tu informe pre-post para {patient_name} (edad {patient_age})!"
        return {
            "thread_id": thread_id,
            "assistant_answer_text": final_answer,
            "tool_output_details": {"pdf_base64": pdf_base64}
        }

    answer_raw = ""
    for msg in all_msgs:
        if msg.role == "assistant":
            potential = join_msg_content(msg)
            if try_parse_function_call(potential) is None and potential.strip():
                answer_raw = potential
                break

    return {
        "thread_id": thread_id,
        "assistant_answer_text": answer_raw,
        "tool_output_details": None
    }

def join_msg_content(msg):
    """
    Combina el contenido de msg.content (que puede ser una lista o cadena) en un string.
    """
    if hasattr(msg, "content") and isinstance(msg.content, list):
        texts = []
        for c in msg.content:
            if hasattr(c, "text") and hasattr(c.text, "value"):
                texts.append(c.text.value)
        return "\n".join(texts)
    return msg.content if hasattr(msg, "content") else ""

def try_parse_function_call(response_str: str):
    """
    Intenta parsear un JSON que contenga "function_name" y "arguments".
    Remueve delimitadores de código (```json y ```).
    """
    try:
        response_str = response_str.strip()
        if response_str.startswith("```json"):
            response_str = response_str.replace("```json", "", 1).strip()
        if response_str.endswith("```"):
            response_str = response_str[:-3].strip()
        data = json.loads(response_str)
        return data
    except Exception as e:
        print("Error parsing JSON:", e)
        return None

def generate_informe_prepost_cem_3pages(patient_name: str, patient_age: int, cognitive_results: dict) -> bytes:
    """
    Genera un PDF de 3 páginas con información Pre/Post:
      - Pag 1: Portada
      - Pag 2: Metodología
      - Pag 3: Datos del paciente y gráfico
    """
    metrics = list(cognitive_results.keys())
    pre_vals = [cognitive_results[m]["pre"] for m in metrics]
    post_vals = [cognitive_results[m]["post"] for m in metrics]

    fig, ax = plt.subplots(figsize=(6, 4))
    x_range = range(len(metrics))
    ax.barh([x + 0.2 for x in x_range], post_vals, height=0.4, label="POST", color="#f7941d")
    ax.barh([x - 0.2 for x in x_range], pre_vals, height=0.4, label="PRE", color="#0072bc")
    ax.set_yticks(x_range)
    ax.set_yticklabels(metrics)
    ax.invert_yaxis()
    ax.legend()
    ax.set_title(f"Informe Pre-Post de {patient_name} (Edad: {patient_age})")

    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format='png', dpi=150)
    plt.close(fig)
    buf.seek(0)

    pdf = FPDF(orientation='L', unit='mm', format=(190.5, 338.7))
    pdf.set_auto_page_break(auto=False, margin=0)

    pdf.add_page()
    pdf.set_font("Arial", "B", 44)
    pdf.ln(40)
    pdf.cell(0, 10, "Estudio comparativo de alumnos CEM 2025", ln=True, align="C")
    pdf.ln(10)
    pdf.set_font("Arial", "", 28)
    pdf.multi_cell(0, 8, "Evaluación de funciones ejecutivas pre y post período de aplicación de programa CEM", align="C")

    pdf.add_page()
    pdf.set_font("Arial", "B", 44)
    pdf.ln(20)
    pdf.cell(0, 10, "Metodología", ln=True, align="C")
    pdf.ln(10)
    pdf.set_font("Arial", "", 28)
    metodologia_text = (
        "* Administración pre/post de Yelow red (funciones ejecutivas)\n"
        "* Experiencia de intervención realizada en el programa\n"
        "  correspondiente a: PIPS"
    )
    pdf.multi_cell(0, 8, metodologia_text, align="L")

    pdf.add_page()
    temp_img_path = "temp_chart.png"
    with open(temp_img_path, "wb") as tmp_img:
        tmp_img.write(buf.getvalue())
    
    pdf.set_font("Arial", "B", 32)
    pdf.ln(10)
    pdf.cell(0, 10, f"{patient_name}, {patient_age} años.", ln=True)

    pdf.image(temp_img_path, x=100, y=40, w=170)

    if os.path.exists(temp_img_path):
        os.remove(temp_img_path)
        
    pdf_bytes = pdf.output(dest="S").encode("latin-1", errors="replace")
    return pdf_bytes
