import os
import sys
import subprocess
import threading
import logging
import pystray
from PIL import Image, ImageDraw
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk
from src.config import BASE_PATH, CURRENT_NODE

def create_dynamic_icon():
    image = Image.new('RGBA', (64, 64), color=(15, 82, 186, 255))
    dc = ImageDraw.Draw(image)
    dc.ellipse([16, 16, 48, 48], fill=(255, 255, 255, 255))
    return image

def open_base_folder():
    BASE_PATH.mkdir(parents=True, exist_ok=True)
    if os.name == 'nt':
        os.startfile(BASE_PATH)
    elif os.name == 'posix':
        subprocess.run(['xdg-open' if sys.platform.startswith('linux') else 'open', str(BASE_PATH)])

def open_activity_log():
    """Abre el archivo de registro de actividad con el editor predeterminado de Windows"""
    log_file_path = BASE_PATH / "syncbridge.log"
    if not log_file_path.exists():
        log_file_path.write_text("--- SyncBridge Activity Log Iniciado ---\n", encoding="utf-8")
    
    if os.name == 'nt':
        os.startfile(log_file_path)
    else:
        subprocess.run(['xdg-open' if sys.platform.startswith('linux') else 'open', str(log_file_path)])

def show_cluster_status():
    """Muestra una ventana emergente propia con el estado del clúster"""
    def _open_window():
        try:
            root = tk.Tk()
            root.title("SyncBridge - Estado del Clúster")
            root.geometry("420x220")
            root.resizable(False, False)
            root.eval('tk::PlaceWindow . center')
            
            frame = ttk.Frame(root, padding=20)
            frame.pack(fill=tk.BOTH, expand=True)
            
            node_name = CURRENT_NODE.get("name", "Desconocido")
            mailbox = CURRENT_NODE.get("mailbox", "N/A")
            
            info_text = (
                f"Estado del Nodo Actual:\n\n"
                f"• Nombre del Nodo: {node_name}\n"
                f"• Buzón en Cloud: {mailbox}\n"
                f"• Ruta Base Local: {BASE_PATH}\n\n"
                f"El servicio de monitoreo (Watchdog) está activo."
            )
            
            label = ttk.Label(frame, text=info_text, font=("Segoe UI", 9))
            label.pack(anchor="w", pady=(0, 15))
            
            btn = ttk.Button(frame, text="Aceptar", command=root.destroy)
            btn.pack(side=tk.BOTTOM, pady=5)
            
            root.mainloop()
        except Exception as e:
            logging.error(f"Error mostrando estado del clúster: {e}", exc_info=True)

    threading.Thread(target=_open_window, daemon=True).start()

def open_sync_gui_isolated():
    try:
        from src.gui import open_sync_gui
        threading.Thread(target=open_sync_gui, daemon=True).start()
    except Exception as e:
        logging.error(f"Error abriendo GUI: {e}")

def stop_app(icon):
    icon.stop()
    os._exit(0)

def setup_tray(icon):
    icon.visible = True

def init_system_tray():
    icon_image = create_dynamic_icon()
    
    menu = pystray.Menu(
        pystray.MenuItem("📊 Ver estado del clúster", lambda: show_cluster_status()),
        pystray.MenuItem("📜 Ver registro de actividad", lambda: open_activity_log()),
        pystray.MenuItem("⚙️ Configurar carpetas...", lambda: open_sync_gui_isolated()),
        pystray.MenuItem("📁 Abrir carpeta base", lambda: open_base_folder()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Salir de SyncBridge", lambda icon, item: stop_app(icon))
    )
    
    global tray_icon
    tray_icon = pystray.Icon("SyncBridge", icon_image, "SyncBridge P2P Sync", menu)
    tray_icon.run(setup=setup_tray)