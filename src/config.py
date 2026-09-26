import os
from pathlib import Path
from dotenv import load_dotenv

# Forzar la recarga del .env por si se acaba de crear en el primer arranque
load_dotenv(override=True)

# Soportamos tanto los nombres antiguos como los que usa el asistente gráfico nuevo
SYNC_SECRET = os.getenv("SYNC_SECRET", "")
GDRIVE_CLIENT_ID = os.getenv("GDRIVE_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID", "")
GDRIVE_CLIENT_SECRET = os.getenv("GDRIVE_CLIENT_SECRET") or os.getenv("GOOGLE_CLIENT_SECRET", "")

NODE_NAME = os.getenv("CURRENT_NODE_NAME") or os.getenv("NODE_NAME", "MiNodo")

# Leer la ruta base de forma dinámica
raw_base_path = os.getenv("SYNC_BASE_PATH") or os.getenv("BASE_PATH")
BASE_PATH = Path(raw_base_path) if raw_base_path else Path.home() / "SyncBridgeFolder"

GDRIVE_CONFIG = {
    "client_id": GDRIVE_CLIENT_ID,
    "client_secret": GDRIVE_CLIENT_SECRET,
    "folder_id": None # Se asignará dinámicamente al buscar/crear 'SyncBridge' en la nube
}

CURRENT_NODE = {
    "name": NODE_NAME,
    "base_path": BASE_PATH,
    "mailbox": f"mailbox_{NODE_NAME}"
}