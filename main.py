import sys
import os

# 🛡️ Blindaje contra prints sin consola
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

import time
import threading
import queue
from pathlib import Path
from dotenv import load_dotenv
import tkinter as tk
from tkinter import messagebox, ttk

# 1. Ejecutar el asistente de configuración inicial si no existe el .env
from src.setup import run_setup_wizard
if not run_setup_wizard():
    sys.exit(0)

# 2. Forzar recarga de entorno después del setup
load_dotenv(override=True)

# 3. Importar módulos de la app
from src.config import BASE_PATH, CURRENT_NODE
from src.manifest import load_or_create_manifest
from src.tray import init_system_tray
from src.watcher import start_watching  # 👈 Nuestro querido Watchdog

def main():
    init_error = None
    is_finished = False
    
    file_queue = queue.Queue()

    def background_task():
        nonlocal init_error, is_finished
        try:
            BASE_PATH.mkdir(parents=True, exist_ok=True)
            
            def report_progress(filename):
                file_queue.put(filename)

            load_or_create_manifest(
                base_path=BASE_PATH, 
                node_name=CURRENT_NODE["name"], 
                on_progress=report_progress
            )
        except Exception as e:
            init_error = e
        finally:
            is_finished = True

    # Lanzar la creación/carga del manifiesto en hilo secundario
    worker_thread = threading.Thread(target=background_task, daemon=True)
    worker_thread.start()

    # --- VENTANA DE CARGA GRÁFICA ---
    splash = tk.Tk()
    splash.title("SyncBridge")
    splash.geometry("420x160")
    splash.resizable(False, False)
    splash.eval('tk::PlaceWindow . center')
    
    frame = ttk.Frame(splash, padding=20)
    frame.pack(fill=tk.BOTH, expand=True)
    
    ttk.Label(frame, text="Sincronizando y preparando nodos...", font=("Segoe UI", 10, "bold")).pack(pady=(0, 5))
    
    file_label = ttk.Label(frame, text="Iniciando escaneo...", font=("Consolas", 8), foreground="#555555")
    file_label.pack(pady=(0, 10))
    
    progress = ttk.Progressbar(frame, mode="indeterminate", length=360)
    progress.pack()
    progress.start(10)

    def update_ui():
        try:
            while True:
                filename = file_queue.get_nowait()
                display_name = (filename[:45] + '..') if len(filename) > 47 else filename
                file_label.config(text=f"Leyendo: {display_name}")
        except queue.Empty:
            pass

        if is_finished:
            splash.destroy()
        else:
            splash.after(30, update_ui)

    splash.after(30, update_ui)
    splash.mainloop()
    # ---------------------------------

    if init_error:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "SyncBridge - Error de Inicio", 
            f"Ocurrió un error al iniciar los servicios:\n\n{str(init_error)}"
        )
        sys.exit(1)

    try:
        # 🚀 1. Arrancar el Watchdog de sincronización en segundo plano (demonio)
        print("👀 Iniciando vigilante Watchdog...")
        watcher_thread = threading.Thread(target=start_watching, daemon=True)
        watcher_thread.start()

        # 🖥️ 2. Iniciar el System Tray en el hilo principal (bloqueante saludable)
        print("🖥️ Iniciando System Tray...")
        init_system_tray()
        
    except Exception as e:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("SyncBridge - Error Crítico", f"No se pudo iniciar los servicios de fondo:\n\n{str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()