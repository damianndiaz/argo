import sqlite3
import os
from datetime import datetime

# La ruta del archivo de base de datos se construye a partir del directorio actual
DB_PATH = os.path.join(os.path.dirname(__file__), "Argo.db")

def init_db():
    """Inicializa la base de datos creando la tabla de turnos si no existe."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_key TEXT UNIQUE,
            patient_name TEXT,
            whatsapp TEXT,
            appointment_datetime TEXT
        )
    ''')
    conn.commit()
    conn.close()

def upsert_appointment(patient_key: str, patient_name: str, whatsapp: str, appointment_datetime: datetime):
    """
    Inserta o actualiza el turno de un paciente.
    
    :param patient_key: Identificador único del paciente (por ejemplo, "mia").
    :param patient_name: Nombre completo del paciente.
    :param whatsapp: Número de WhatsApp en formato E.164 (ejemplo: "+5491123456789").
    :param appointment_datetime: Objeto datetime con la fecha y hora del turno.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Usamos "INSERT OR REPLACE" para actualizar si el registro ya existe (basado en patient_key)
    c.execute('''
        INSERT INTO appointments (patient_key, patient_name, whatsapp, appointment_datetime)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(patient_key) DO UPDATE SET
            patient_name = excluded.patient_name,
            whatsapp = excluded.whatsapp,
            appointment_datetime = excluded.appointment_datetime
    ''', (patient_key, patient_name, whatsapp, appointment_datetime.strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

def get_appointment(patient_key: str):
    """
    Recupera el turno de un paciente.
    
    :param patient_key: Identificador del paciente.
    :return: Diccionario con los datos del turno o None si no existe.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT patient_key, patient_name, whatsapp, appointment_datetime FROM appointments WHERE patient_key = ?', (patient_key,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "patient_key": row[0],
            "patient_name": row[1],
            "whatsapp": row[2],
            "appointment_datetime": datetime.strptime(row[3], "%Y-%m-%d %H:%M:%S")
        }
    return None

# Inicializamos la base de datos al importar este módulo
init_db()