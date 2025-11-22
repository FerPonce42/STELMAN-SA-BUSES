import os
import mysql.connector
from mysql.connector import pooling

def get_connection():
    """Devuelve una conexión a la base de datos usando variables de entorno opcionales.

    Variables de entorno soportadas:
    - DB_HOST (por defecto: localhost)
    - DB_USER (por defecto: root)
    - DB_PASSWORD (por defecto: '')
    - DB_NAME (por defecto: empresa_bus_bd)
    """
    host = os.environ.get('DB_HOST', 'localhost')
    user = os.environ.get('DB_USER', 'root')
    password = os.environ.get('DB_PASSWORD', '')
    database = os.environ.get('DB_NAME', 'empresa_bus_bd')

    return mysql.connector.connect(
        host=host,
        user=user,
        password=password,
        database=database
    )
   