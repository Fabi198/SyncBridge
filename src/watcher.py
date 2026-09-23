import time
import os
import logging
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from src.config import CURRENT_NODE

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

class SyncHandler(FileSystemEventHandler):
    def __init__(self):
        super().__init__()
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

    def on_created(self, event):
        if not self.is_initialized or self.is_muted or event.is_directory or self._is_ignorable(event.src_path):
            return
        
        try:
            path_obj = Path(event.src_path)
            if path_obj.exists() and path_obj.is_file():
                self.file_sizes[event.src_path] = path_obj.stat().st_size
                logging.info(f"🟢 [CAMBIO REAL - CREACIÓN] {event.src_path}")
        except Exception:
            pass

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
            logging.info(f"🟡 [CAMBIO REAL - MODIFICACIÓN DE PESO] {event.src_path} ({current_size} bytes)")
        except Exception:
            pass

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
                
            logging.info(f"🔵 [CAMBIO REAL - RENOMBRE] {event.src_path} ➡️ {event.dest_path}")
        except Exception:
            pass

    def on_deleted(self, event):
        if not self.is_initialized or self.is_muted or event.is_directory or self._is_ignorable(event.src_path):
            return
        
        if event.src_path in self.file_sizes:
            del self.file_sizes[event.src_path]

        logging.info(f"🔴 [CAMBIO REAL - BORRADO] {event.src_path}")

def start_watching():
    path_to_watch = CURRENT_NODE["base_path"]
    
    if not path_to_watch.exists():
        logging.error(f"❌ La ruta base {path_to_watch} no existe en este equipo.")
        return

    event_handler = SyncHandler()
    event_handler.perform_baseline_scan(path_to_watch)

    observer = Observer()
    observer.schedule(event_handler, path=str(path_to_watch), recursive=True)
    
    observer.start()
    logging.info(f"👀 Watchdog en línea vigilando cambios futuros en: {path_to_watch}")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Deteniendo el Watchdog...")
        observer.stop()
    observer.join()

if __name__ == "__main__":
    print(f"Iniciando monitor inteligente completo para: {CURRENT_NODE['name']}")
    start_watching()