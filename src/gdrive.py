import os
import io
import json
import pickle
from pathlib import Path
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from src.config import GDRIVE_CONFIG, CURRENT_NODE, SYNC_SECRET
from src.crypto import encrypt_text, decrypt_text

SCOPES = ['https://www.googleapis.com/auth/drive']
TOKEN_PATH = Path("token.pickle")

def get_drive_service():
    """Autentica y retorna el servicio de Google Drive usando credenciales del .env"""
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

def get_or_create_root_folder(service):
    """Busca o crea la carpeta principal 'SyncBridge' en la raíz del Google Drive del usuario"""
    folder_name = "SyncBridge"
    query = f"name = '{folder_name}' and 'root' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    files = results.get('files', [])
    
    if files:
        root_id = files[0]['id']
        GDRIVE_CONFIG["folder_id"] = root_id
        return root_id
    else:
        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': ['root']
        }
        folder = service.files().create(body=file_metadata, fields='id').execute()
        root_id = folder.get('id')
        GDRIVE_CONFIG["folder_id"] = root_id
        print(f"✨ Carpeta principal 'SyncBridge' creada automáticamente en Google Drive (ID: {root_id})")
        return root_id

def upload_node_manifest(service, manifest_data, node_name):
    """Cifra y sube el manifiesto del nodo a Google Drive"""
    folder_id = GDRIVE_CONFIG["folder_id"]
    manifest_filename = f"manifest_{node_name}.json"
    
    json_str = json.dumps(manifest_data, indent=4)
    encrypted_content = encrypt_text(json_str, SYNC_SECRET)
    
    query = f"name = '{manifest_filename}' and '{folder_id}' in parents and trashed = false"
    results = service.files().list(q=query, spaces='drive', fields='files(id)').execute()
    files = results.get('files', [])
    
    media = MediaIoBaseUpload(
        io.BytesIO(encrypted_content.encode('utf-8')),
        mimetype='application/json',
        resumable=True
    )
    
    if files:
        file_id = files[0]['id']
        service.files().update(fileId=file_id, media_body=media).execute()
    else:
        file_metadata = {
            'name': manifest_filename,
            'parents': [folder_id]
        }
        service.files().create(body=file_metadata, media_body=media, fields='id').execute()

def download_remote_manifest(service, remote_node_name):
    """Descarga y descifra el manifiesto de otro nodo desde Google Drive"""
    folder_id = GDRIVE_CONFIG["folder_id"]
    manifest_filename = f"manifest_{remote_node_name}.json"
    
    query = f"name = '{manifest_filename}' and '{folder_id}' in parents and trashed = false"
    results = service.files().list(q=query, spaces='drive', fields='files(id)').execute()
    files = results.get('files', [])
    
    if not files:
        return None
        
    file_id = files[0]['id']
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
        
    fh.seek(0)
    encrypted_content = fh.read().decode('utf-8')
    
    decrypted_json_str = decrypt_text(encrypted_content, SYNC_SECRET)
    if not decrypted_json_str:
        return None
        
    return json.loads(decrypted_json_str)

def get_or_create_folder(service, folder_name, parent_id):
    """Busca o crea una subcarpeta dentro del directorio padre en Google Drive"""
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
        return folder.get('id')

def get_or_create_cluster_state(service):
    """Verifica o inicializa el estado global del clúster en Drive si es necesario"""
    folder_id = GDRIVE_CONFIG.get("folder_id")
    if not folder_id:
        folder_id = get_or_create_root_folder(service)
    
    # Podés asegurarte de crear una carpeta para buzones o estado global si lo requiere el clúster
    return get_or_create_folder(service, "ClusterMailboxes", folder_id)

def upload_file_to_mailbox(service, local_file_path, mailbox_folder_id):
    """Sube un archivo plano (como las instrucciones JSON) al buzón correspondiente en Drive"""
    path_obj = Path(local_file_path)
    file_metadata = {
        'name': path_obj.name,
        'parents': [mailbox_folder_id]
    }
    
    with open(path_obj, 'rb') as f:
        media = MediaIoBaseUpload(f, mimetype='application/octet-stream', resumable=True)
        file_result = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return file_result.get('id')