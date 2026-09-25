import os
import io
import json
import logging
from pathlib import Path
from googleapiclient.http import MediaIoBaseDownload
from src.config import CURRENT_NODE, GDRIVE_CONFIG
from src.gdrive import get_drive_service, read_cluster_state, get_or_create_cluster_state

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

def process_remote_instructions(service, state_file_id):
    """Revisa los buzones de los demás nodos una sola vez, descarga comandos y los aplica"""
    logging.info(f"🔍 [SYNC ENGINE] Verificando buzones remotos para el nodo: {CURRENT_NODE['name']}...")
    try:
        cluster_state = read_cluster_state(service, state_file_id)
        nodes = cluster_state.get("nodes", {})
        root_folder_id = GDRIVE_CONFIG["folder_id"]
        
        acciones_procesadas = 0
        
        for node_name, node_info in nodes.items():
            if node_name == CURRENT_NODE["name"]:
                continue
                
            mailbox_name = node_info.get("mailbox")
            if not mailbox_name:
                continue
                
            # Buscar el buzón del otro nodo
            query = f"name = '{mailbox_name}' and '{root_folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
            folders = results.get('files', [])
            
            if not folders:
                continue
                
            mailbox_id = folders[0]['id']
            
            # Buscar comandos pendientes
            cmd_query = f"'{mailbox_id}' in parents and name contains 'cmd_' and trashed = false"
            cmd_results = service.files().list(q=cmd_query, spaces='drive', fields='files(id, name)').execute()
            commands = cmd_results.get('files', [])
            
            for cmd_file in commands:
                file_id = cmd_file['id']
                file_name = cmd_file['name']
                
                logging.info(f"📥 Descargando instrucción de {node_name}: {file_name}")
                
                request = service.files().get_media(fileId=file_id)
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                fh.seek(0)
                
                instruction = json.loads(fh.read().decode('utf-8'))
                execute_local_instruction(instruction)
                
                # Borrar de la nube para no re-procesarlo
                service.files().delete(fileId=file_id).execute()
                acciones_procesadas += 1
                logging.info(f"🗑️ Instrucción procesada y eliminada de la nube: {file_name}")
                
        if acciones_procesadas == 0:
            logging.info("✨ No hay nuevas instrucciones remotas pendientes. Todo al día.")
        else:
            logging.info(f"✅ Sincronización de entrada finalizada. Se aplicaron {acciones_procesadas} cambios.")
                
    except Exception as e:
        logging.error(f"❌ Error al procesar instrucciones remotas: {e}")

def execute_local_instruction(instruction):
    """Aplica la instrucción en el disco local"""
    action = instruction.get("action")
    src = instruction.get("src")
    dest = instruction.get("dest")
    
    try:
        if action == "RENAME":
            src_path = Path(src)
            dest_path = Path(dest)
            if src_path.exists():
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                src_path.rename(dest_path)
                logging.info(f"✨ [REPLICADO] Renombrado local: {src} ➡️ {dest}")
            else:
                logging.warning(f"⚠️ No se encontró el origen para renombrar: {src}")
                
        elif action == "DELETE":
            target_path = Path(src)
            if target_path.exists() and target_path.is_file():
                target_path.unlink()
                logging.info(f"✨ [REPLICADO] Borrado local: {src}")
                
    except Exception as e:
        logging.error(f"❌ Error ejecutando instrucción local '{action}': {e}")

if __name__ == "__main__":
    print(f"--- Sincronizador de Entrada (Run-Once) para: {CURRENT_NODE['name']} ---")
    service = get_drive_service()
    state_file_id = get_or_create_cluster_state(service)
    
    # Ejecuta una sola vez y finaliza limpiamente
    process_remote_instructions(service, state_file_id)
    print("🏁 Motor de sincronización finalizado.")