import json
import base64
import io
import matplotlib.pyplot as plt
from fpdf import FPDF

def get_assistant_answer(
    client,
    user_msg: str = None,
    thread_id: str = None,
    assistant_id: str = "asst_XKvU1ulcVEy8UZd5fatnZ60c"
):
    """
    Envía el mensaje del usuario a la Beta de Threads.
    1) Crea un thread si no existe (inyectando un "assistant" message con instrucciones más estrictas).
    2) Agrega el mensaje de usuario.
    3) Ejecuta el assistant y obtiene todos los mensajes del hilo.
    4) Revisa todos los 'assistant' messages para ver si hay JSON con function_name="generate_prepost_report".
       Si lo encuentra, genera un PDF y lo retorna.
    5) Si no encuentra JSON, retorna el texto final del assistant sin PDF.
    """

    # 1) Crear thread si no existe
    if not thread_id:
        print("Ningún thread_id provisto, generando uno nuevo...")

        # Instrucciones internas (simulando system).
        # Se fuerza a NO dar disclaimers ni texto extra, solo JSON cuando se pida un informe.
        internal_instructions = (
            "Eres Argo, un médico argentino experto. "
            "Si se te pide generar un informe pre/post con datos, responde "
            "EXCLUSIVAMENTE con un JSON y NADA de texto adicional, en el siguiente formato:\n\n"
            "{\n"
            '  "function_name": "generate_prepost_report",\n'
            '  "arguments": {\n'
            '    "patient_name": "NOMBRE",\n'
            '    "patient_age": 9,\n'
            '    "cognitive_results": {\n'
            '      "Métrica 1": {"pre": 0, "post": 0},\n'
            '      ...\n'
            "    }\n"
            "  }\n"
            "}\n\n"
            "NO añadas texto extra, disclaimers ni explicaciones. "
            "En otras preguntas, responde normalmente. "
            "Cuando no estés generando un informe, contesta con texto libre."
        )

        thread = client.beta.threads.create(
            messages=[
                {
                    "role": "assistant",
                    "content": internal_instructions
                },
                {
                    "role": "assistant",
                    "content": "Hola, soy Argo. ¿En qué puedo ayudarte hoy?"
                }
            ]
        )
        thread_id = thread.id
        print(f"Nuevo thread iniciado. ID: {thread_id}")
    else:
        print(f"El cliente proporciona thread_id y se utiliza. ID: {thread_id}")

    # 2) Agregar mensaje del usuario
    messages = client.beta.threads.messages.list(thread_id=thread_id)
    if (not user_msg or user_msg.strip() == "") and len(messages) == 1:
        # Caso mensaje inicial vacío
        message = client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content="Hola, me explicarías de qué forma puedes ayudarme?"
        )
        print("El usuario envía mensaje inicial vacío. Se agrega uno por default.")
    else:
        # Mensaje normal
        message = client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=user_msg
        )
        print(f"Mensaje del usuario: '{user_msg}' agregado al thread.")

    message_id = message.id if message else None

    # 3) Ejecutar el Assistant
    if message_id and assistant_id:
        run = client.beta.threads.runs.create_and_poll(
            thread_id=thread_id,
            assistant_id=assistant_id
        )
        print("Se inicia Assistant Run...")
        if run.status == 'requires_action':
            print("Assistant Run requiere acciones del servidor.")
        if run.status == 'completed':
            print("Assistant Run finalizado.")
    else:
        print("No se encuentra message_id o assistant_id para realizar la corrida")

    # 4) Recuperar TODOS los mensajes de la conversación
    all_msgs = client.beta.threads.messages.list(thread_id=thread_id).data

    # Buscamos el mensaje final del assistant, para retornarlo como answer_raw
    answer_raw = ""
    for msg in all_msgs:
        if msg.role == "assistant" and answer_raw == "":
            # El primer 'assistant' que encontremos es el más reciente en la Beta
            answer_raw = join_msg_content(msg)

    # 5) Revisar si en alguno de los mensajes 'assistant' existe un JSON con function_name="generate_prepost_report"
    pdf_base64 = None
    pdf_confirmation_msg = None

    for msg in all_msgs:
        if msg.role == "assistant":
            parsed = try_parse_function_call(join_msg_content(msg))
            if parsed and parsed.get("function_name") == "generate_prepost_report":
                fn_args = parsed["arguments"]
                patient_name = fn_args.get("patient_name", "Paciente")
                patient_age = fn_args.get("patient_age", 0)
                cog_results = fn_args.get("cognitive_results", {})

                # Generar PDF
                pdf_bytes = generate_informe_prepost_cem_3pages(patient_name, patient_age, cog_results)
                pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8")
                pdf_confirmation_msg = f"Informe Pre-Post para {patient_name} (edad {patient_age}) generado."
                break  # Solo generamos 1 vez

    # Si encontramos JSON y generamos el PDF, devolvemos la confirmación + pdf_base64
    if pdf_base64:
        # Inyectamos un mensaje en el hilo (opcional)
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

    # 6) Si no encontramos JSON, retornamos el contenido textual
    return {
        "thread_id": thread_id,
        "assistant_answer_text": answer_raw,
        "tool_output_details": None
    }

def join_msg_content(msg):
    """
    Combina el texto de msg.content (que a veces es un array de partes).
    """
    if hasattr(msg, "content") and isinstance(msg.content, list):
        texts = []
        for c in msg.content:
            if hasattr(c, "text") and hasattr(c.text, "value"):
                texts.append(c.text.value)
        return "\n".join(texts)
    return ""

def try_parse_function_call(response_str: str):
    """
    Intenta parsear un JSON con "function_name" y "arguments".
    """
    try:
        data = json.loads(response_str)
        return data
    except:
        return None

def generate_informe_prepost_cem_3pages(
    patient_name: str,
    patient_age: int,
    cognitive_results: dict
) -> bytes:
    """
    Genera un PDF de 3 páginas con info Pre/Post:
      - Pag1: Portada
      - Pag2: Metodología
      - Pag3: Gráfico
    """
    import matplotlib.pyplot as plt
    import io
    from fpdf import FPDF

    metrics = list(cognitive_results.keys())
    pre_vals = [cognitive_results[m]["pre"] for m in metrics]
    post_vals = [cognitive_results[m]["post"] for m in metrics]

    fig, ax = plt.subplots(figsize=(6, 4))
    x_range = range(len(metrics))
    ax.barh([x+0.2 for x in x_range], post_vals, height=0.4, label="POST", color="#f7941d")
    ax.barh([x-0.2 for x in x_range], pre_vals, height=0.4, label="PRE", color="#0072bc")
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

    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=False, margin=0)

    # Pag 1
    pdf.add_page()
    pdf.set_font("Calibri", "B", 44)
    pdf.ln(40)
    pdf.cell(0, 10, "Estudio comparativo de alumnos CEM 2025", ln=True, align="C")
    pdf.ln(10)
    pdf.set_font("Calibri", "", 28)
    pdf.multi_cell(0, 8, "Evaluación de funciones ejecutivas pre y post período de aplicación de programa CEM", align="C")

    # Pag 2
    pdf.add_page()
    pdf.set_font("Calibri", "B", 44)
    pdf.ln(20)
    pdf.cell(0, 10, "Metodología", ln=True, align="C")
    pdf.ln(10)
    pdf.set_font("Calibri", "", 28)
    metodologia_text = (
        "* Administración pre/post de Yelow red (funciones ejecutivas)\n"
        "* Experiencia de intervención realizada en el programa\n"
        "  correspondiente a: PIPS"
    )
    pdf.multi_cell(0, 8, metodologia_text, align="L")

    # Pag 3
    pdf.add_page()
    with open("temp_chart.png", "wb") as tmp_img:
        tmp_img.write(buf.getvalue())

    pdf.set_font("Calibri", "B", 32)
    pdf.ln(10)
    pdf.cell(0, 10, f"{patient_name} (edad {patient_age})", ln=True)

    # Posicionar el gráfico a la derecha.
    # En orientación landscape A4, el ancho total es ~297 mm.
    # Se coloca la imagen en x=150 mm para ubicarse en la mitad derecha,
    # y se ajusta el ancho de la imagen a 120 mm.
    pdf.image(temp_img_path, x=150, y=20, w=120)

    pdf_bytes = pdf.output(dest="S").encode("latin-1", errors="replace")
    return pdf_bytes
