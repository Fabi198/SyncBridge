import io
import json
import time
import logging
import threading
from pathlib import Path
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from src.config import BASE_PATH, CURRENT_NODE, GDRIVE_CONFIG

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

def get_drive_service():
    """Construye y retorna el servicio de Google Drive usando las credenciales dinámicas de config.py"""
    from src.gdrive import get_drive_service as base_get_service
    return base_get_service()

def process_mailbox():
    """Revisa el buzón propio, descarga los paquetes de cambios pendientes y los aplica localmente"""
    node_name = CURRENT_NODE["name"]
    mailbox_name = CURRENT_NODE["mailbox"]
    root_folder_id = GDRIVE_CONFIG["folder_id"]
    
    try:
        service = get_drive_service()

        # 1. Buscar el ID de la carpeta de nuestro buzón en Google Drive
        query_mailbox = f"name = '{mailbox_name}' and '{root_folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        res = service.files().list(q=query_mailbox, fields='files(id, name)').execute().get('files', [])
        
        if not res:
            logging.warning(f"⚠️ No se encontró el buzón '{mailbox_name}' en Google Drive.")
            return

        mailbox_id = res[0]['id']

        # 2. Buscar archivos dentro del buzón (ej: cluster_instructions.json o paquetes individuales)
        query_files = f"'{mailbox_id}' in parents and trashed = false"
        files_in_box = service.files().list(
            q=query_files, 
            orderBy='createdTime asc', 
            fields='files(id, name, mimeType)'
        ).execute().get('files', [])

        if not files_in_box:
            logging.info(f"📭 Buzón '{mailbox_name}' al día. No hay elementos pendientes.")
            return

        logging.info(f"📥 Encontrados {len(files_in_box)} elementos en el buzón {mailbox_name}. Procesando...")

        for file_item in files_in_box:
            file_id = file_item['id']
            file_name = file_item['name']

            # Descargar contenido del archivo desde Google Drive a memoria
            request = service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()

            try:
                content_bytes = fh.getvalue()
                if not content_bytes:
                    service.files().delete(fileId=file_id).execute()
                    continue

                # Si el archivo es el consolidado de instrucciones (cluster_instructions.json)
                if file_name == "cluster_instructions.json":
                    instructions = json.loads(content_bytes.decode('utf-8'))
                    if not isinstance(instructions, list):
                        instructions = [instructions]

                    for inst in instructions:
                        action = inst.get("action")
                        rel_path = inst.get("rel_path")
                        cloud_file_id = inst.get("file_id")

                        if not rel_path:
                            continue

                        # Validar subcarpetas permitidas
                        included_subfolders = CURRENT_NODE.get("included_subfolders", [])
                        top_folder = rel_path.split("/")[0] if "/" in rel_path else rel_path
                        if included_subfolders and top_folder not in included_subfolders:
                            continue

                        target_path = BASE_PATH / rel_path

                        if action == "CREATE_OR_UPDATE" and cloud_file_id:
                            # Descargar el archivo real desde Google Drive usando el file_id compartido
                            req_file = service.files().get_media(fileId=cloud_file_id)
                            fh_file = io.BytesIO()
                            dl_file = MediaIoBaseDownload(fh_file, req_file)
                            done_file = False
                            while not done_file:
                                _, done_file = dl_file.next_chunk()

                            target_path.parent.mkdir(parents=True, exist_ok=True)
                            target_path.write_bytes(fh_file.getvalue())
                            logging.info(f"✅ Sincronizado localmente (Actualizado/Creado): {rel_path}")

                        elif action in ["DELETE", "DELETE_DIR"]:
                            if target_path.exists():
                                if target_path.is_file():
                                    target_path.unlink()
                                elif target_path.is_dir():
                                    import shutil
                                    shutil.rmtree(target_path, ignore_errors=True)
                                logging.info(f"🗑️ Sincronizado localmente (Eliminado): {rel_path}")

                    # Una vez procesadas todas las instrucciones, borramos el archivo del buzón
                    service.files().delete(fileId=file_id).execute()
                    logging.info(f"🗑️ Archivo maestro 'cluster_instructions.json' consumido y eliminado del buzón.")

            except Exception as e:
                logging.error(f"❌ Error al procesar el archivo del buzón {file_name}: {e}")

    except Exception as e:
        logging.error(f"❌ Error en el ciclo del consumidor para {mailbox_name}: {e}")

def force_sync_now():
    """Función para disparar la sincronización manualmente (ideal para el System Tray)"""
    logging.info("🔄 Forzando sincronización manual del buzón...")
    sync_thread = threading.Thread(target=process_mailbox, daemon=True)
    sync_thread.start()

def start_consumer_loop(interval_hours=5):
    """
    Ejecuta el consumidor inmediatamente al encender/iniciar el dispositivo,
    y luego se queda en pausa repitiendo cada X horas (por defecto 5hs).
    """
    logging.info(f"🚀 Iniciando motor Consumidor para el nodo [ {CURRENT_NODE['name']} ]...")
    
    # 1. Sincronización obligatoria al iniciar el dispositivo
    process_mailbox()

    # 2. Bucle pasivo con intervalo largo (ej: cada 5 horas)
    interval_seconds = interval_hours * 3600
    while True:
        time.sleep(interval_seconds)
        process_mailbox()