import time
import os
import logging
import json
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from src.config import CURRENT_NODE, GDRIVE_CONFIG
from src.gdrive import (
    get_drive_service, 
    get_or_create_cluster_state, 
    get_or_create_folder,
    upload_file_to_mailbox
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

class SyncHandler(FileSystemEventHandler):
    def __init__(self, service, mailbox_id):
        super().__init__()
        self.service = service
        self.mailbox_id = mailbox_id
        self.is_muted = False
        self.file_sizes = {}
        self.is_initialized = False

    def _is_ignorable(self, path_str: str) -> bool:
        path_lower = path_str.lower()
        path_obj = Path(path_str)
        
        protected_folders = {
            "windowsapps", "system volume information", "$recycle.bin", 
            "recovery", "msocache", "config.msi", "system32", "syswow64"
        }
        
        if any(folder in path_lower for folder in protected_folders):
            return True

        system_exclusions = {"desktop.ini", "thumbs.db", "pagefile.sys", "swapfile.sys", "hiberfil.sys"}
        if path_obj.name.lower() in system_exclusions:
            return True
            
        ignored_extensions = {".tmp", ".log", ".crdownload", ".part", ".etl", ".sys", ".lnk"}
        if path_obj.suffix.lower() in ignored_extensions:
            return True
            
        if "~$" in path_obj.name:
            return True
            
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

    def register_instruction(self, action, src, dest=None):
        """Crea un archivo JSON de instrucción liviano para comandos como RENAME o DELETE"""
        try:
            instruction = {
                "node": CURRENT_NODE["name"],
                "action": action,
                "src": str(src),
                "dest": str(dest) if dest else None,
                "timestamp": time.time()
            }
            
            instruction_filename = f"cmd_{int(time.time() * 1000)}.json"
            local_temp_path = Path(instruction_filename)
            
            with open(local_temp_path, 'w', encoding='utf-8') as f:
                json.dump(instruction, f, indent=4)
                
            upload_file_to_mailbox(self.service, local_temp_path, self.mailbox_id)
            
            if local_temp_path.exists():
                local_temp_path.unlink()
            logging.info(f"📤 Instrucción de clúster '{action}' enviada a la nube.")
        except Exception as e:
            logging.error(f"❌ Error al registrar instrucción '{action}': {e}")

    def on_created(self, event):
        if not self.is_initialized or self.is_muted or event.is_directory or self._is_ignorable(event.src_path):
            return
        
        try:
            path_obj = Path(event.src_path)
            if path_obj.exists() and path_obj.is_file():
                self.file_sizes[event.src_path] = path_obj.stat().st_size
                logging.info(f"🟢 [CREACIÓN] Subiendo archivo: {event.src_path}")
                upload_file_to_mailbox(self.service, event.src_path, self.mailbox_id)
        except Exception as e:
            logging.error(f"❌ Error en creación: {e}")

    def on_modified(self, event):
        if not self.is_initialized or self.is_muted or event.is_directory or self._is_ignorable(event.src_path):
            return
        
        try:
            path_obj = Path(event.src_path)
            if not path_obj.exists() or not path_obj.is_file():
                return

            current_size = path_obj.stat().st_size
            last_size = self.file_sizes.get(event.src_path)

            if last_size == current_size:
                return

            self.file_sizes[event.src_path] = current_size
            logging.info(f"🟡 [MODIFICACIÓN] Actualizando archivo: {event.src_path}")
            upload_file_to_mailbox(self.service, event.src_path, self.mailbox_id)
        except Exception as e:
            logging.error(f"❌ Error en modificación: {e}")

    def on_moved(self, event):
        if not self.is_initialized or self.is_muted or event.is_directory:
            return
        
        if self._is_ignorable(event.src_path) or self._is_ignorable(event.dest_path):
            return
        
        try:
            if event.src_path in self.file_sizes:
                del self.file_sizes[event.src_path]
            
            path_obj = Path(event.dest_path)
            if path_obj.exists() and path_obj.is_file():
                self.file_sizes[event.dest_path] = path_obj.stat().st_size
                
            logging.info(f"🔵 [RENOMBRE] {event.src_path} ➡️ {event.dest_path}")
            self.register_instruction("RENAME", event.src_path, event.dest_path)
        except Exception as e:
            logging.error(f"❌ Error en renombramiento: {e}")

    def on_deleted(self, event):
        if not self.is_initialized or self.is_muted or event.is_directory or self._is_ignorable(event.src_path):
            return
        
        if event.src_path in self.file_sizes:
            del self.file_sizes[event.src_path]

        logging.info(f"🔴 [BORRADO] {event.src_path}")
        self.register_instruction("DELETE", event.src_path)

def start_watching():
    path_to_watch = CURRENT_NODE["base_path"]
    
    if not path_to_watch.exists():
        logging.error(f"❌ La ruta base {path_to_watch} no existe en este equipo.")
        return

    print(f"--- Inicializando sincronizador para: {CURRENT_NODE['name']} ---")
    
    # Conexión a Google Drive y preparación del buzón del nodo
    service = get_drive_service()
    root_folder = GDRIVE_CONFIG["folder_id"]
    mailbox_id = get_or_create_folder(service, CURRENT_NODE["mailbox"], root_folder)
    get_or_create_cluster_state(service)

    event_handler = SyncHandler(service, mailbox_id)
    event_handler.perform_baseline_scan(path_to_watch)

    observer = Observer()
    observer.schedule(event_handler, path=str(path_to_watch), recursive=True)
    
    observer.start()
    logging.info(f"==================================================")
    logging.info(f" 👀 WATCHDOG + COMANDOS ACTIVO EN NODO: {CURRENT_NODE['name']}")
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