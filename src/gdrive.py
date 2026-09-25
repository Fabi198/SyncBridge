import os
import io
import json
import pickle
from pathlib import Path
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from src.config import GDRIVE_CONFIG, CURRENT_NODE
from googleapiclient.http import MediaIoBaseUpload

# Alcance completo para administrar la carpeta de sincronización y los buzones
SCOPES = ['https://www.googleapis.com/auth/drive']
TOKEN_PATH = Path("token.pickle")

def get_drive_service():
    """Autentica y retorna el servicio de Google Drive usando las credenciales del .env"""
    creds = None
    
    if TOKEN_PATH.exists():
        with open(TOKEN_PATH, 'rb') as token:
            creds = pickle.load(token)
            
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            client_config = {
                "installed": {
                    "client_id": GDRIVE_CONFIG["client_id"],
                    "client_secret": GDRIVE_CONFIG["client_secret"],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            }
            flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            creds = flow.run_local_server(port=0, prompt='select_account')
            
        with open(TOKEN_PATH, 'wb') as token:
            pickle.dump(creds, token)
            
    return build('drive', 'v3', credentials=creds)

def get_or_create_folder(service, folder_name, parent_id):
    """Busca una carpeta dentro de un directorio padre; si no existe, la crea."""
    query = f"name = '{folder_name}' and '{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    files = results.get('files', [])
    
    if files:
        return files[0]['id']
    else:
        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_id]
        }
        folder = service.files().create(body=file_metadata, fields='id').execute()
        print(f"📁 Carpeta '{folder_name}' creada en Google Drive (ID: {folder.get('id')})")
        return folder.get('id')

def get_or_create_cluster_state(service):
    """Busca o crea el archivo cluster_state.json en la carpeta raíz compartida de Drive"""
    folder_id = GDRIVE_CONFIG["folder_id"]
    query = f"name = 'cluster_state.json' and '{folder_id}' in parents and trashed = false"
    
    results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    files = results.get('files', [])
    
    if files:
        return files[0]['id']
    else:
        initial_state = {
            "locks": {},
            "nodes": {
                CURRENT_NODE["name"]: {"status": "active", "mailbox": CURRENT_NODE["mailbox"]}
            }
        }
        media = MediaIoBaseUpload(
            io.BytesIO(json.dumps(initial_state, indent=4).encode('utf-8')),
            mimetype='application/json',
            resumable=True
        )
        file_metadata = {
            'name': 'cluster_state.json',
            'parents': [folder_id]
        }
        file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        print(f"🔒 Archivo cluster_state.json inicializado en la nube.")
        return file.get('id')

def read_cluster_state(service, file_id):
    """Lee el estado actual del clúster desde la nube"""
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    fh.seek(0)
    return json.loads(fh.read().decode('utf-8'))

def update_cluster_state(service, file_id, state_data):
    """Actualiza de forma atómica el estado del clúster en la nube"""
    media = MediaIoBaseUpload(
        io.BytesIO(json.dumps(state_data, indent=4).encode('utf-8')),
        mimetype='application/json',
        resumable=True
    )
    service.files().update(fileId=file_id, media_body=media).execute()

def upload_file_to_mailbox(service, file_path, mailbox_id):
    """Sube o actualiza un archivo local al buzón de Google Drive del nodo"""
    path = Path(file_path)
    if not path.is_file():
        return
        
    file_name = path.name
    
    # Verificar si el archivo ya existe en el buzón para actualizarlo o crearlo nuevo
    query = f"name = '{file_name}' and '{mailbox_id}' in parents and trashed = false"
    results = service.files().list(q=query, spaces='drive', fields='files(id)').execute()
    files = results.get('files', [])
    
    with open(path, 'rb') as f:
        media = MediaIoBaseUpload(f, mimetype='application/octet-stream', resumable=True)
        
        if files:
            file_id = files[0]['id']
            service.files().update(fileId=file_id, media_body=media).execute()
            print(f"☁️ Archivo actualizado en la nube: {file_name}")
        else:
            file_metadata = {
                'name': file_name,
                'parents': [mailbox_id]
            }
            service.files().create(body=file_metadata, media_body=media, fields='id').execute()
            print(f"☁️ Archivo subido a la nube: {file_name}")




if __name__ == "__main__":
    print(f"--- Probando conexión a Drive para el nodo: {CURRENT_NODE['name']} ---")
    service = get_drive_service()
    
    # Asegurar que exista el buzón específico del nodo en la nube y el estado del clúster
    root_folder = GDRIVE_CONFIG["folder_id"]
    mailbox_id = get_or_create_folder(service, CURRENT_NODE["mailbox"], root_folder)
    state_file_id = get_or_create_cluster_state(service)
    cluster_state = read_cluster_state(service, state_file_id)

    print(f"✅ Buzón verificado en nube (ID: {mailbox_id})")
    print(f"✅ Estado del clúster cargado:", cluster_state)