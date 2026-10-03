import io
import json
import time
import logging
import threading
from pathlib import Path
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import src.config 
from src.config import BASE_PATH, CURRENT_NODE, GDRIVE_CONFIG

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

def get_drive_service():
    """Construye y retorna el servicio de Google Drive usando las credenciales dinámicas de config.py"""
    logging.debug("🔌 Solicitando servicio de Google Drive...")
    from src.gdrive import get_drive_service as base_get_service
    return base_get_service()

def process_mailbox():
    """Revisa el buzón propio, descarga los paquetes de cambios pendientes y los aplica localmente de forma segura"""
    node_name = CURRENT_NODE["name"]
    mailbox_name = CURRENT_NODE["mailbox"]
    root_folder_id = GDRIVE_CONFIG["folder_id"]
    
    logging.info(f"🔍 [CONSUMIDOR] Iniciando revisión del buzón '{mailbox_name}' para el nodo '{node_name}' (Base Path: {BASE_PATH})")
    
    try:
        service = get_drive_service()

        # 1. Buscar el ID de la carpeta de nuestro buzón en Google Drive
        query_mailbox = f"name = '{mailbox_name}' and '{root_folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        res = service.files().list(q=query_mailbox, fields='files(id, name)').execute().get('files', [])
        
        if not res:
            logging.warning(f"⚠️ [CONSUMIDOR] No se encontró el buzón '{mailbox_name}' en Google Drive (Root ID: {root_folder_id}).")
            return

        mailbox_id = res[0]['id']
        logging.info(f"📂 [CONSUMIDOR] Buzón encontrado en Drive con ID: {mailbox_id}")

        # 2. Buscar archivos dentro del buzón
        query_files = f"'{mailbox_id}' in parents and trashed = false"
        files_in_box = service.files().list(
            q=query_files, 
            orderBy='createdTime asc', 
            fields='files(id, name, mimeType)'
        ).execute().get('files', [])

        if not files_in_box:
            logging.info(f"📭 [CONSUMIDOR] El buzón '{mailbox_name}' está vacio. Al día.")
            return

        logging.info(f"📥 [CONSUMIDOR] Encontrados {len(files_in_box)} elementos en el buzón. Procesando...")

        for file_item in files_in_box:
            file_id = file_item['id']
            file_name = file_item['name']
            logging.info(f"📄 [CONSUMIDOR] Analizando archivo en buzón: '{file_name}' (ID: {file_id})")

            # Descargar contenido del archivo desde Google Drive a memoria
            try:
                request = service.files().get_media(fileId=file_id)
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                content_bytes = fh.getvalue()
                logging.info(f"⬇ [CONSUMIDOR] Descargados {len(content_bytes)} bytes del archivo '{file_name}'")
            except Exception as e:
                logging.error(f"❌ [CONSUMIDOR] Error al descargar el archivo del buzón {file_name}: {e}")
                continue

            if not content_bytes:
                logging.warning(f"⚠ [CONSUMIDOR] El archivo '{file_name}' está vacío. Eliminando de Drive...")
                try:
                    service.files().delete(fileId=file_id).execute()
                except Exception:
                    pass
                continue

            try:
                # Si el archivo es el consolidado de instrucciones (cluster_instructions.json)
                if file_name == "cluster_instructions.json":
                    instructions = json.loads(content_bytes.decode('utf-8'))
                    if not isinstance(instructions, list):
                        instructions = [instructions]

                    logging.info(f"📋 [CONSUMIDOR] Se leyeron {len(instructions)} instrucciones en 'cluster_instructions.json'.")

                    for inst in instructions:
                        try:
                            origin_node = inst.get("node")
                            logging.debug(f"🔍 [CONSUMIDOR] Inspeccionando instrucción generada por nodo: '{origin_node}' (Acción: {inst.get('action')}, RelPath: {inst.get('rel_path')})")

                            # 🛡️ IMPORTANTE: Ignorar instrucciones generadas por nosotros mismos para evitar bucles de eco
                            if origin_node == CURRENT_NODE["name"]:
                                logging.info(f"🛡️ [CONSUMIDOR] Omitiendo instrucción propia proveniente de '{origin_node}' para evitar bucle.")
                                continue

                            action = inst.get("action")
                            rel_path = inst.get("rel_path")
                            cloud_file_id = inst.get("file_id")

                            if not rel_path:
                                logging.warning(f"⚠️ [CONSUMIDOR] Instrucción descartada por falta de 'rel_path'. Contenido: {inst}")
                                continue

                            # Validar subcarpetas permitidas
                            included_subfolders = CURRENT_NODE.get("included_subfolders", [])
                            top_folder = rel_path.split("/")[0] if "/" in rel_path else rel_path
                            if included_subfolders and top_folder not in included_subfolders:
                                logging.info(f"🛑 [CONSUMIDOR] Ruta '{rel_path}' ignorada por filtros de subcarpetas (Top folder: '{top_folder}').")
                                continue

                            target_path = BASE_PATH / rel_path
                            logging.info(f"🎯 [CONSUMIDOR] Ruta de destino calculada localmente: {target_path}")

                            # 🔇 SILENCIAR EL WATCHDOG MIENTRAS APLICAMOS LOS CAMBIOS DE LA RED
                            src.config.IS_SYNCING_FROM_NETWORK = True
                            
                            try:
                                if action == "CREATE_OR_UPDATE" and cloud_file_id:
                                    logging.info(f"☁ [CONSUMIDOR] Descargando archivo adjunto de Drive (ID: {cloud_file_id}) para replicar en: {target_path}")
                                    
                                    # 1. Descargar el archivo real desde Google Drive usando el file_id compartido
                                    req_file = service.files().get_media(fileId=cloud_file_id)
                                    fh_file = io.BytesIO()
                                    dl_file = MediaIoBaseDownload(fh_file, req_file)
                                    done_file = False
                                    while not done_file:
                                        _, done_file = dl_file.next_chunk()

                                    # Crear carpetas intermedias explícitamente
                                    target_path.parent.mkdir(parents=True, exist_ok=True)
                                    logging.info(f"📁 [CONSUMIDOR] Directorio contenedor asegurado: {target_path.parent}")
                                    
                                    # Escribir el archivo localmente (el watcher lo ignorará gracias a la bandera)
                                    target_path.write_bytes(fh_file.getvalue())
                                    logging.info(f"✅ [CONSUMIDOR] ¡ÉXITO! Archivo sincronizado y escrito localmente: {target_path} (Relativo: {rel_path})")

                                    # 2. Eliminar el archivo temporal compartido de la nube
                                    try:
                                        service.files().delete(fileId=cloud_file_id).execute()
                                        logging.info(f"🗑 [CONSUMIDOR] Archivo temporal en nube (ID: {cloud_file_id}) eliminado correctamente.")
                                    except Exception as del_e:
                                        logging.warning(f"⚠️ [CONSUMIDOR] No se pudo borrar el archivo temporal {cloud_file_id}: {del_e}")

                                elif action in ["DELETE", "DELETE_DIR"]:
                                    logging.info(f"🗑️ [CONSUMIDOR] Ejecutando orden de eliminación para: {target_path}")
                                    if target_path.exists():
                                        if target_path.is_file():
                                            target_path.unlink()
                                        elif target_path.is_dir():
                                            import shutil
                                            shutil.rmtree(target_path, ignore_errors=True)
                                        logging.info(f"🗑️ [CONSUMIDOR] Elemento eliminado localmente con éxito: {rel_path}")
                                    else:
                                        logging.info(f"ℹ️ [CONSUMIDOR] El elemento a eliminar ya no existía localmente: {target_path}")

                                elif action == "CREATE_DIR":
                                    logging.info(f"📁 [CONSUMIDOR] Creando directorio local: {target_path}")
                                    target_path.mkdir(parents=True, exist_ok=True)
                                    logging.info(f"✅ [CONSUMIDOR] Directorio creado con éxito: {target_path}")

                                elif action in ["RENAME", "MOVE_DIRECTORY"]:
                                    dest_raw = inst.get("dest")
                                    if not dest_raw:
                                        logging.warning(f"⚠️ [CONSUMIDOR] Instrucción RENAME descartada por falta de 'dest'. Contenido: {inst}")
                                        continue
                                    
                                    dest_path_obj = Path(dest_raw)
                                    if dest_path_obj.is_absolute():
                                        try:
                                            dest_target_path = BASE_PATH / dest_path_obj.relative_to(dest_path_obj.anchor)
                                        except Exception:
                                            dest_target_path = BASE_PATH / dest_path_obj.name
                                    else:
                                        dest_target_path = BASE_PATH / dest_path_obj

                                    logging.info(f"🔄 [CONSUMIDOR] Ejecutando renombramiento/movimiento de '{target_path}' a '{dest_target_path}'")
                                    
                                    if target_path.exists():
                                        dest_target_path.parent.mkdir(parents=True, exist_ok=True)
                                        target_path.rename(dest_target_path)
                                        logging.info(f"✅ [CONSUMIDOR] Renombrado aplicado con éxito localmente.")
                                    else:
                                        logging.info(f"ℹ️ [CONSUMIDOR] El archivo original a renombrar no existía localmente: {target_path}")

                            finally:
                                # 🔊 REACTIVAR EL WATCHDOG PASE LO QUE PASE
                                src.config.IS_SYNCING_FROM_NETWORK = False

                        except Exception as inner_e:
                            logging.error(f"❌ [CONSUMIDOR] Error procesando una instrucción individual ({inst}): {inner_e}")

                    # 3. Borrar el archivo 'cluster_instructions.json' del buzón de forma permanente una vez procesado
                    service.files().delete(fileId=file_id).execute()
                    logging.info(f"🗑 [CONSUMIDOR] Archivo maestro 'cluster_instructions.json' consumido y eliminado de la nube.")

            except Exception as e:
                logging.error(f"❌ [CONSUMIDOR] Error al procesar el contenido del archivo {file_name}: {e}")

    except Exception as e:
        logging.error(f"❌ [CONSUMIDOR] Error crítico en el ciclo de consumo para {mailbox_name}: {e}")

def force_sync_now():
    """Función para disparar la sincronización manualmente (ideal para el System Tray)"""
    logging.info("🔄 [CONSUMIDOR] Forzando sincronización manual del buzón por solicitud...")
    sync_thread = threading.Thread(target=process_mailbox, daemon=True)
    sync_thread.start()

def start_consumer_loop(interval_hours=5):
    """
    Ejecuta el consumidor inmediatamente al encender/iniciar el dispositivo,
    y luego se queda en pausa repitiendo cada X horas (por defecto 5hs).
    """
    logging.info(f"🚀 [CONSUMIDOR] Iniciando motor Consumidor continuo para el nodo [ {CURRENT_NODE['name']} ]...")
    
    # 1. Sincronización obligatoria al iniciar el dispositivo
    process_mailbox()

    # 2. Bucle pasivo con intervalo largo (ej: cada 5 horas)
    interval_seconds = interval_hours * 3600
    while True:
        time.sleep(interval_seconds)
        process_mailbox()