import time
import os
import logging
import json
import threading
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import tkinter as tk
from tkinter import messagebox
import src.config
from src.config import CURRENT_NODE, GDRIVE_CONFIG
from src.gdrive import (
    get_drive_service,
    get_or_create_root_folder,
    get_or_create_cluster_state, 
    get_or_create_folder,
    upload_file_to_mailbox
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

class SyncHandler(FileSystemEventHandler):
    def __init__(self, service, root_folder_id):
        super().__init__()
        self.service = service
        self.root_folder_id = root_folder_id
        self.is_muted = False
        self.file_sizes = {}
        self.is_initialized = False
        self.queue_lock = threading.Lock()
        
        # Archivo local consolidado para acumular instrucciones y no spamear la API
        self.queue_file = CURRENT_NODE["base_path"] / "cluster_queue.json"
        
        # Hilo en segundo plano para procesar la cola, subir archivos con calma y enviar a los nodos
        self.batch_thread = threading.Thread(target=self._batch_sender_loop, daemon=True)
        self.batch_thread.start()

    def _is_ignorable(self, path_str: str) -> bool:
        # 🔇 Si la red está aplicando cambios, ignoramos absolutamente todo lo que pase en el disco
        if src.config.IS_SYNCING_FROM_NETWORK:
            return True

        path_lower = path_str.lower()
        path_obj = Path(path_str)
        
        protected_folders = {
            "windowsapps", "system volume information", "$recycle.bin", 
            "recovery", "msocache", "config.msi", "system32", "syswow64"
        }
        
        if any(folder in path_lower for folder in protected_folders):
            return True

        # 🛡️ Ignorar archivos internos y lotes temporales de SyncBridge
        name_lower = path_obj.name.lower()
        if name_lower in {"desktop.ini", "thumbs.db", "pagefile.sys", "swapfile.sys", "hiberfil.sys", "cluster_queue.json", "syncbridge.log"}:
            return True
        if name_lower.startswith("batch_cmd_") or name_lower.startswith("cluster_instructions_"):
            return True
            
        ignored_extensions = {".tmp", ".log", ".crdownload", ".part", ".etl", ".sys", ".lnk"}
        if path_obj.suffix.lower() in ignored_extensions:
            return True
            
        if "~$" in path_obj.name:
            return True
            
        # 📂 Filtrar según las subcarpetas seleccionadas en el asistente
        included_subfolders = CURRENT_NODE.get("included_subfolders", [])
        if included_subfolders:
            try:
                base_path = CURRENT_NODE["base_path"]
                rel = path_obj.relative_to(base_path)
                top_folder = rel.parts[0] if rel.parts else ""
                if top_folder and top_folder not in included_subfolders:
                    return True
            except ValueError:
                pass
            
        return False

    def perform_baseline_scan(self, base_path: Path):
        logging.info(f"🔍 Realizando escaneo inicial silencioso de {base_path}...")
        count = 0
        
        for root, dirs, files in os.walk(base_path):
            dirs[:] = [d for d in dirs if not self._is_ignorable(os.path.join(root, d))]
            
            for file in files:
                full_path = os.path.join(root, file)
                if self._is_ignorable(full_path):
                    continue
                try:
                    file_path_obj = Path(full_path)
                    if file_path_obj.exists() and file_path_obj.is_file():
                        self.file_sizes[full_path] = file_path_obj.stat().st_size
                        count += 1
                except (PermissionError, OSError):
                    pass
                    
        self.is_initialized = True
        logging.info(f"✅ Escaneo inicial completado. {count} archivos indexados. Watchdog activo y listo.")

    def register_instruction(self, action, src, dest=None, file_id=None, rel_path=None):
        """Agrega o actualiza la orden en cluster_queue.json manejando rutas absolutas y relativas correctamente"""
        try:
            base_path = CURRENT_NODE["base_path"]
            
            if not rel_path and src:
                try:
                    rel_path = Path(src).relative_to(base_path)
                except ValueError:
                    rel_path = Path(src).name

            with self.queue_lock:
                queue_data = []
                if self.queue_file.exists():
                    try:
                        with open(self.queue_file, 'r', encoding='utf-8') as f:
                            queue_data = json.load(f)
                    except json.JSONDecodeError:
                        queue_data = []
                
                # 💡 FUSIÓN INTELIGENTE CORREGIDA
                if action == "RENAME":
                    actualizado = False
                    for item in queue_data:
                        if item.get("action") == "CREATE_OR_UPDATE" and item.get("src") == str(src):
                            logging.info(f"✨ [OPTIMIZACIÓN DE COLA] Actualizando ruta de creación para archivo renombrado.")
                            
                            # Si 'dest' que vino es relativo, calculamos su absoluta y su relativa correcta
                            abs_dest = base_path / dest if not Path(dest).is_absolute() else Path(dest)
                            rel_dest = Path(dest) if not Path(dest).is_absolute() else Path(dest).relative_to(base_path)
                            
                            item["src"] = str(abs_dest)          # Ruta absoluta para que el batch encuentre el archivo
                            item["rel_path"] = str(rel_dest)     # Ruta relativa para la red
                            item["timestamp"] = time.time()
                            actualizado = True
                            break
                    if actualizado:
                        with open(self.queue_file, 'w', encoding='utf-8') as f:
                            json.dump(queue_data, f, indent=4)
                        return

                instruction = {
                    "node": CURRENT_NODE["name"],
                    "action": action,
                    "src": str(src),
                    "dest": str(dest) if dest else None,
                    "file_id": file_id,
                    "rel_path": str(rel_path) if rel_path else None,
                    "timestamp": time.time()
                }
                
                queue_data.append(instruction)
                
                with open(self.queue_file, 'w', encoding='utf-8') as f:
                    json.dump(queue_data, f, indent=4)
                    
            logging.info(f"📥 Orden '{action}' agregada/actualizada en la cola del clúster.")
        except Exception as e:
            logging.error(f"❌ Error al registrar instrucción '{action}': {e}")

    def _batch_sender_loop(self):
        """Procesa la cola local, sube archivos pendientes de a uno con reintentos y distribuye a los nodos"""
        from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
        import io

        while True:
            time.sleep(5)
            if not self.queue_file.exists():
                continue
                
            with self.queue_lock:
                try:
                    if not self.queue_file.exists() or self.queue_file.stat().st_size == 0:
                        continue
                    
                    new_instructions = json.loads(self.queue_file.read_text(encoding='utf-8'))
                    self.queue_file.unlink()
                except Exception:
                    continue

            # Sube los archivos a Google Drive usando la ruta absoluta correcta (src)
            for inst in new_instructions:
                if inst.get("action") == "CREATE_OR_UPDATE" and not inst.get("file_id"):
                    src_path = inst.get("src")
                    if src_path and Path(src_path).exists():
                        success = False
                        for intento in range(3):
                            try:
                                logging.info(f"☁ [BATCH] Subiendo archivo final a Drive (Intento {intento+1}/3): {src_path}")
                                file_id = upload_file_to_mailbox(self.service, src_path, self.root_folder_id)
                                if file_id:
                                    inst["file_id"] = file_id
                                    success = True
                                    break
                            except Exception as net_e:
                                logging.warning(f"⚠ Error de red al subir {src_path}, reintentando en 3s... ({net_e})")
                                time.sleep(3)
                        if not success:
                            logging.error(f"❌ No se pudo subir el archivo tras varios intentos: {src_path}")

            temp_path = None
            try:
                cluster_folder_id = get_or_create_root_folder(self.service)
                state_query = f"name = 'cluster_state.json' and '{cluster_folder_id}' in parents and trashed = false"
                state_files = self.service.files().list(q=state_query, spaces='drive', fields='files(id)').execute().get('files', [])
                
                node_names = []
                if state_files:
                    file_id = state_files[0]['id']
                    request = self.service.files().get_media(fileId=file_id)
                    fh = io.BytesIO()
                    downloader = MediaIoBaseDownload(fh, request)
                    done = False
                    while not done:
                        _, done = downloader.next_chunk()
                    
                    try:
                        state_data = json.loads(fh.getvalue().decode('utf-8'))
                        nodes_configured = state_data.get("nodes_configured", {})
                        node_names = list(nodes_configured.keys())
                    except Exception:
                        node_names = []

                current_name = CURRENT_NODE["name"]
                root_mailboxes_id = get_or_create_cluster_state(self.service)

                for target_node in node_names:
                    if target_node == current_name:
                        continue

                    mailbox_name = f"mailbox_{target_node}"
                    target_mailbox_id = get_or_create_folder(self.service, mailbox_name, root_mailboxes_id)

                    query = f"name = 'cluster_instructions.json' and '{target_mailbox_id}' in parents and trashed = false"
                    results = self.service.files().list(q=query, spaces='drive', fields='files(id)').execute().get('files', [])
                    
                    temp_dir = Path(os.environ.get('TEMP', CURRENT_NODE["base_path"]))
                    temp_path = temp_dir / f"cluster_instructions_{target_node}_{int(time.time() * 1000)}.json"

                    if results:
                        file_id = results[0]['id']
                        request = self.service.files().get_media(fileId=file_id)
                        fh = io.BytesIO()
                        downloader = MediaIoBaseDownload(fh, request)
                        done = False
                        while not done:
                            _, done = downloader.next_chunk()
                        
                        try:
                            existing_instructions = json.loads(fh.getvalue().decode('utf-8'))
                            if not isinstance(existing_instructions, list):
                                existing_instructions = []
                        except Exception:
                            existing_instructions = []

                        combined_instructions = existing_instructions + new_instructions
                        temp_path.write_text(json.dumps(combined_instructions, indent=4), encoding='utf-8')

                        media = MediaFileUpload(str(temp_path), mimetype='application/json', resumable=True)
                        self.service.files().update(fileId=file_id, media_body=media).execute()
                        logging.info(f"☁️ Órdenes enviadas y fusionadas en el buzón directo de [{target_node}].")
                    else:
                        temp_path.write_text(json.dumps(new_instructions, indent=4), encoding='utf-8')
                        
                        file_metadata = {
                            'name': 'cluster_instructions.json',
                            'parents': [target_mailbox_id]
                        }
                        media = MediaFileUpload(str(temp_path), mimetype='application/json', resumable=True)
                        self.service.files().create(body=file_metadata, media_body=media, fields='id').execute()
                        logging.info(f"☁️ Órdenes enviadas al nuevo buzón directo de [{target_node}].")

            except Exception as e:
                logging.error(f"❌ Error al distribuir las instrucciones a los nodos: {e}")
                with self.queue_lock:
                    try:
                        if self.queue_file.exists():
                            existing_local = json.loads(self.queue_file.read_text(encoding='utf-8'))
                            self.queue_file.write_text(json.dumps(existing_local + new_instructions, indent=4), encoding='utf-8')
                        else:
                            self.queue_file.write_text(json.dumps(new_instructions, indent=4), encoding='utf-8')
                    except Exception:
                        pass
            finally:
                if temp_path and temp_path.exists():
                    for _ in range(3):
                        try:
                            temp_path.unlink()
                            break
                        except (PermissionError, OSError):
                            time.sleep(0.5)

    def _prompt_new_folder(self, folder_path):
        def show():
            try:
                root = tk.Tk()
                root.withdraw()
                folder_name = Path(folder_path).name
                resp = messagebox.askyesno(
                    "SyncBridge - Nueva carpeta detectada",
                    f"Se detectó una nueva carpeta en la ruta base:\n'{folder_name}'\n\n¿Deseas mantenerla vigilada por el clúster?"
                )
                if resp:
                    logging.info(f"📂 Carpeta nueva aceptada para monitoreo: {folder_path}")
                root.destroy()
            except Exception as e:
                logging.error(f"Error en prompt de nueva carpeta: {e}")

        threading.Thread(target=show, daemon=True).start()

    def on_created(self, event):
        if not self.is_initialized or self.is_muted or self._is_ignorable(event.src_path):
            return
        
        try:
            path_obj = Path(event.src_path)
            
            if event.is_directory:
                if path_obj.parent == CURRENT_NODE["base_path"]:
                    self._prompt_new_folder(event.src_path)
                return

            if path_obj.exists() and path_obj.is_file():
                for _ in range(5):
                    try:
                        self.file_sizes[event.src_path] = path_obj.stat().st_size
                        break
                    except (PermissionError, OSError):
                        time.sleep(0.5)
                else:
                    return

                logging.info(f"🟢 [CREACIÓN] Archivo nuevo detectado (en cola): {event.src_path}")
                
                base_path = CURRENT_NODE["base_path"]
                rel_path = path_obj.relative_to(base_path)
                
                # Registra la orden de inmediato sin bloquear subiendo a la red; el hilo batch se encarga después
                self.register_instruction("CREATE_OR_UPDATE", event.src_path, file_id=None, rel_path=rel_path)
        except Exception as e:
            logging.error(f"❌ Error en creación: {e}")

    def on_modified(self, event):
        if not self.is_initialized or self.is_muted or event.is_directory or self._is_ignorable(event.src_path):
            return
        
        try:
            path_obj = Path(event.src_path)
            if not path_obj.exists() or not path_obj.is_file():
                return

            current_size = -1
            for _ in range(5):
                try:
                    current_size = path_obj.stat().st_size
                    break
                except (PermissionError, OSError):
                    time.sleep(0.5)
            
            if current_size == -1:
                return

            last_size = self.file_sizes.get(event.src_path)
            if last_size == current_size:
                return

            self.file_sizes[event.src_path] = current_size
            logging.info(f"🟡 [MODIFICACIÓN] Archivo actualizado (en cola): {event.src_path}")
            
            base_path = CURRENT_NODE["base_path"]
            rel_path = path_obj.relative_to(base_path)
            
            self.register_instruction("CREATE_OR_UPDATE", event.src_path, file_id=None, rel_path=rel_path)
        except Exception as e:
            logging.error(f"❌ Error en modificación: {e}")

    def on_moved(self, event):
        if not self.is_initialized or self.is_muted:
            return
        
        if src.config.IS_SYNCING_FROM_NETWORK:
            return

        if self._is_ignorable(event.src_path) or self._is_ignorable(event.dest_path):
            return
        
        try:
            base_path = CURRENT_NODE["base_path"]
            
            # 🛡️ VALIDACIÓN ROBUSTA: ¿Conocíamos este archivo de origen previamente?
            # Si NO está en nuestros registros ni en el disco como archivo previo, 
            # significa que el SO lo creó y renombró de golpe (ej. "Nuevo archivo" -> "script.py")
            origen_existia_en_cluster = (event.src_path in self.file_sizes) or Path(event.src_path).exists()

            # O si el origen no está dentro de nuestros archivos rastreados y el SO hizo un renombramiento instantáneo:
            if not origen_existia_en_cluster:
                logging.info(f"✨ [DETECCIÓN ROBUSTA] El origen '{event.src_path}' no existía previamente. Tratando como CREACIÓN.")
                
                path_dest = Path(event.dest_path)
                rel_dest = path_dest.relative_to(base_path)
                
                if event.is_directory or path_dest.is_dir():
                    self.register_instruction("CREATE_DIR", event.dest_path, rel_path=str(rel_dest))
                else:
                    if path_dest.exists() and path_dest.is_file():
                        self.file_sizes[event.dest_path] = path_dest.stat().st_size
                    self.register_instruction("CREATE_OR_UPDATE", event.dest_path, file_id=None, rel_path=str(rel_dest))
                return

            # --- Si el archivo SÍ existía, es un RENAME / MOVE genuino ---
            if event.is_directory:
                logging.info(f"📁 [MOVIMIENTO DE CARPETA] {event.src_path} ➡️ {event.dest_path}")
                rel_src = Path(event.src_path).relative_to(base_path)
                rel_dest = Path(event.dest_path).relative_to(base_path)
                self.register_instruction("MOVE_DIRECTORY", event.src_path, dest=str(rel_dest), rel_path=str(rel_src))
                return

            # Actualizamos el registro interno de tamaños
            if event.src_path in self.file_sizes:
                del self.file_sizes[event.src_path]
            
            path_obj = Path(event.dest_path)
            if path_obj.exists() and path_obj.is_file():
                self.file_sizes[event.dest_path] = path_obj.stat().st_size
                
            logging.info(f"🔵 [RENOMBRE/MOVER ARCHIVO] {event.src_path} ➡️ {event.dest_path}")
            
            rel_src = Path(event.src_path).relative_to(base_path)
            rel_dest = Path(event.dest_path).relative_to(base_path)
            
            self.register_instruction("RENAME", event.src_path, dest=str(rel_dest), rel_path=str(rel_src))
            
        except Exception as e:
            logging.error(f"❌ Error en movimiento/renombramiento: {e}")

    def on_deleted(self, event):
        if not self.is_initialized or self.is_muted or self._is_ignorable(event.src_path):
            return
        
        if event.src_path in self.file_sizes:
            del self.file_sizes[event.src_path]

        action_type = "DELETE_DIR" if event.is_directory else "DELETE"
        logging.info(f"🔴 [{action_type}] {event.src_path}")
        self.register_instruction(action_type, event.src_path)

def start_watching():
    path_to_watch = CURRENT_NODE["base_path"]
    
    if not path_to_watch.exists():
        logging.error(f"❌ La ruta base {path_to_watch} no existe en este equipo.")
        return

    print(f"--- Inicializando sincronizador para: {CURRENT_NODE['name']} ---")
    
    service = get_drive_service()
    
    root_folder = get_or_create_root_folder(service)
    if not root_folder:
        root_folder = GDRIVE_CONFIG.get("folder_id")

    get_or_create_cluster_state(service)

    event_handler = SyncHandler(service, root_folder)
    event_handler.perform_baseline_scan(path_to_watch)

    observer = Observer()
    observer.schedule(event_handler, path=str(path_to_watch), recursive=True)
    
    observer.start()
    logging.info(f"==================================================")
    logging.info(f" 👀 WATCHDOG + MULTI-NODE SENDER ACTIVO: {CURRENT_NODE['name']}")
    logging.info(f" 📂 Vigilando ruta: {path_to_watch}")
    logging.info(f"==================================================")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("🛑 Sincronizador detenido por el usuario.")
        observer.stop()
    observer.join()

if __name__ == "__main__":
    start_watching()