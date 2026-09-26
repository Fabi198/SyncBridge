import os
import io
import json
import logging
from pathlib import Path
from googleapiclient.http import MediaIoBaseDownload
from src.config import CURRENT_NODE, BASE_PATH
from src.gdrive import get_drive_service, get_or_create_root_folder, get_or_create_folder

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

def download_file_by_id(service, file_id, destination_path):
    """Descarga un archivo desde Google Drive usando su file_id"""
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path.write_bytes(fh.getvalue())

def process_mailbox_instructions(service, mailbox_id):
    """Busca el archivo maestro cluster_instructions.json en el buzón y ejecuta las órdenes"""
    try:
        # 1. Buscar si existe el archivo maestro de instrucciones
        query = f"name = 'cluster_instructions.json' and '{mailbox_id}' in parents and trashed = false"
        results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute().get('files', [])
        
        if not results:
            logging.info("📭 No hay instrucciones pendientes en este buzón.")
            return

        instruction_file_id = results[0]['id']
        logging.info("📥 Archivo 'cluster_instructions.json' encontrado en la nube. Descargando...")

        # 2. Descargar el contenido del JSON de instrucciones
        request = service.files().get_media(fileId=instruction_file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        instructions = json.loads(fh.getvalue().decode('utf-8'))
        if not isinstance(instructions, list):
            logging.error("❌ El archivo de instrucciones no es un array válido.")
            return

        # 3. Procesar orden por orden
        for item in instructions:
            action = item.get("action")
            rel_path = item.get("rel_path")
            file_id = item.get("file_id")
            src = item.get("src")
            dest = item.get("dest")

            if not rel_path:
                continue

            target_path = BASE_PATH / rel_path

            if action == "CREATE_OR_UPDATE":
                if file_id:
                    logging.info(f"📥 [CONSUMO] Descargando archivo cloud para: {rel_path}")
                    download_file_by_id(service, file_id, target_path)
                
            elif action == "DELETE" or action == "DELETE_DIR":
                if target_path.exists():
                    if target_path.is_file():
                        target_path.unlink()
                        logging.info(f"🗑️ [CONSUMO] Archivo borrado localmente: {rel_path}")
                    elif target_path.is_dir():
                        import shutil
                        shutil.rmtree(target_path, ignore_errors=True)
                        logging.info(f"🗑️ [CONSUMO] Directorio borrado localmente: {rel_path}")

            elif action == "RENAME":
                if dest:
                    # Mapear dest a ruta local si viene absoluta
                    dest_path = BASE_PATH / Path(dest).relative_to(CURRENT_NODE["base_path"])
                    if target_path.exists():
                        dest_path.parent.mkdir(parents=True, exist_ok=True)
                        target_path.rename(dest_path)
                        logging.info(f"🔄 [CONSUMO] Renombrado local: {rel_path} ➡️ {dest_path.name}")

            elif action == "MOVE_DIRECTORY":
                # Lógica para mover carpetas enteras
                if dest and target_path.exists():
                    dest_path = BASE_PATH / Path(dest).relative_to(CURRENT_NODE["base_path"])
                    import shutil
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(target_path), str(dest_path))
                    logging.info(f"📁 [CONSUMO] Carpeta movida localmente: {rel_path}")

        # 4. Limpieza: Una vez aplicadas todas con éxito, borrar el archivo de instrucciones de la nube
        service.files().delete(fileId=instruction_file_id).execute()
        logging.info("🧹 Lote de instrucciones procesado con éxito y eliminado de la nube.")

    except Exception as e:
        logging.error(f"❌ Error procesando las instrucciones del buzón: {e}", exc_info=True)

if __name__ == "__main__":
    print("--- Probando Consumidor de Instrucciones ---")
    service = get_drive_service()
    root_folder = get_or_create_root_folder(service)
    
    # Apuntamos al buzón actual ("MiPC") para probar que lea sus propias órdenes pendientes
    mailbox_id = get_or_create_folder(service, CURRENT_NODE["mailbox"], root_folder)
    
    process_mailbox_instructions(service, mailbox_id)