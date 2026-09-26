import os
import sys
import subprocess
import threading
import pystray
from PIL import Image, ImageDraw
from pathlib import Path
import tkinter as tk
from tkinter import messagebox
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

def show_cluster_status():
    print(f"📊 Nodo: {CURRENT_NODE['name']} | Ruta: {BASE_PATH}")

def open_sync_gui_isolated():
    try:
        from src.gui import open_sync_gui
        threading.Thread(target=open_sync_gui, daemon=True).start()
    except Exception as e:
        print(f"Error GUI: {e}")

def stop_app(icon):
    icon.stop()
    os._exit(0)

def setup_tray(icon):
    try:
        icon.visible = True
        # Esto hace que Windows lance un globo o notificación flotante al lado del reloj
        icon.notify("SyncBridge está sincronizando en segundo plano.", "¡SyncBridge Iniciado!")
    except Exception as e:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Error en setup_tray", str(e))

def init_system_tray():
    try:
        icon_image = create_dynamic_icon()
        
        menu = pystray.Menu(
            pystray.MenuItem("📊 Ver estado del clúster", lambda: show_cluster_status()),
            pystray.MenuItem("⚙️ Configurar carpetas...", lambda: open_sync_gui_isolated()),
            pystray.MenuItem("📁 Abrir carpeta base", lambda: open_base_folder()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Salir de SyncBridge", lambda icon, item: stop_app(icon))
        )
        
        global tray_icon
        tray_icon = pystray.Icon("SyncBridge", icon_image, "SyncBridge P2P Sync", menu)
        
        # Intentamos ejecutar el tray atrapando cualquier excepción crítica
        tray_icon.run(setup=setup_tray)
        
    except Exception as e:
        # Si algo falla al crear o correr el ícono, se abrirá un cartel rojo sí o sí
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "SyncBridge - Error Crítico en Tray", 
            f"El sistema de bandeja falló con el siguiente error:\n\n{type(e).__name__}: {str(e)}"
        )
        sys.exit(1)