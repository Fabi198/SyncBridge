import os
import io
import json
import time
import logging
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, filedialog
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

CONFIG_FILE = Path("src/config.py")
SCOPES = ['https://www.googleapis.com/auth/drive.file']

class SyncBridgeWizard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SyncBridge - Asistente de Configuración P2P")
        self.geometry("560x480")
        self.resizable(False, False)
        
        # Variables de estado
        self.service = None
        self.root_folder_id = None
        self.cluster_state = {}
        self.state_file_id = None
        self.node_names = []
        self.nodes_configured = {}
        
        self.client_id_var = tk.StringVar()
        self.client_secret_var = tk.StringVar()
        self.selected_node = tk.StringVar()
        self.node1_name = tk.StringVar(value="MiPC")
        self.node2_name = tk.StringVar(value="CompuOficina")
        self.base_path_var = tk.StringVar(value="D:\\")

        self.container = tk.Frame(self, padx=25, pady=25)
        self.container.pack(fill="both", expand=True)

        # Mostrar pantalla inicial para pedir Client ID y Client Secret
        self.show_credentials_screen()

    def clear_container(self):
        for widget in self.container.winfo_children():
            widget.destroy()

    def show_credentials_screen(self):
        self.clear_container()
        
        tk.Label(self.container, text="Credenciales de Google Drive", font=("Arial", 16, "bold")).pack(anchor="w", pady=(0, 5))
        tk.Label(self.container, text="Ingresá las credenciales de tu proyecto de Google Cloud (OAuth 2.0) para conectar la aplicación:", font=("Arial", 9), wraplength=500, justify="left").pack(anchor="w", pady=(0, 15))

        tk.Label(self.container, text="Client ID:", font=("Arial", 10, "bold")).pack(anchor="w", pady=(5, 2))
        tk.Entry(self.container, textvariable=self.client_id_var, font=("Arial", 10), width=50).pack(anchor="w", pady=2)

        tk.Label(self.container, text="Client Secret:", font=("Arial", 10, "bold")).pack(anchor="w", pady=(10, 2))
        tk.Entry(self.container, textvariable=self.client_secret_var, font=("Arial", 10), width=50, show="*").pack(anchor="w", pady=2)

        tk.Button(self.container, text="Conectar y Autenticar 🔑", bg="#0078D7", fg="white", font=("Arial", 10, "bold"), padx=15, pady=8, command=self.authenticate_with_credentials).pack(anchor="e", pady=(35, 0))

    def authenticate_with_credentials(self):
        client_id = self.client_id_var.get().strip()
        client_secret = self.client_secret_var.get().strip()

        if not client_id or not client_secret:
            messagebox.showwarning("Campos vacíos", "Por favor, ingresá tanto el Client ID como el Client Secret.")
            return

        try:
            # Mostrar estado de carga
            self.clear_container()
            tk.Label(self.container, text="Autenticando...", font=("Arial", 14, "bold")).pack(anchor="w", pady=10)
            tk.Label(self.container, text="Se abrirá tu navegador web para autorizar el acceso a Google Drive.", font=("Arial", 10)).pack(anchor="w", pady=10)
            self.update()

            # Generar client_config en memoria para el flujo de OAuth
            client_config = {
                "installed": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            }

            flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            creds = flow.run_local_server(port=0)

            # Construir servicio de Drive
            self.service = build('drive', 'v3', credentials=creds)
            
            # Crear o buscar carpeta raíz de SyncBridge en Drive
            self.root_folder_id = self.get_or_create_root_folder_dynamic()

            # Consultar estado en la nube
            self.check_cluster_status()

            # Avanzar a la siguiente pantalla
            if not self.node_names:
                self.show_node_creation_screen()
            else:
                self.show_node_selection_screen()

        except Exception as e:
            messagebox.showerror("Error de Autenticación", f"No se pudo completar la conexión con Google Drive:\n{e}")
            self.show_credentials_screen()

    def get_or_create_root_folder_dynamic(self):
        folder_name = "SyncBridge"
        query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = self.service.files().list(q=query, spaces='drive', fields='files(id, name)').execute().get('files', [])
        
        if results:
            return results[0]['id']
        
        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        folder = self.service.files().create(body=file_metadata, fields='id').execute()
        return folder.get('id')

    def check_cluster_status(self):
        try:
            state_query = f"name = 'cluster_state.json' and '{self.root_folder_id}' in parents and trashed = false"
            state_files = self.service.files().list(q=state_query, spaces='drive', fields='files(id)').execute().get('files', [])
            
            if state_files:
                self.state_file_id = state_files[0]['id']
                request = self.service.files().get_media(fileId=self.state_file_id)
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                try:
                    self.cluster_state = json.loads(fh.getvalue().decode('utf-8'))
                except Exception:
                    self.cluster_state = {}

            self.node_names = self.cluster_state.get("node_names", [])
            self.nodes_configured = self.cluster_state.get("nodes_configured", {})
        except Exception as e:
            logging.error(f"Error al verificar estado del clúster: {e}")

    def show_node_creation_screen(self):
        self.clear_container()
        
        tk.Label(self.container, text="Configuración Inicial del Clúster", font=("Arial", 14, "bold")).pack(anchor="w", pady=5)
        tk.Label(self.container, text="No se encontró un clúster previo en tu Drive. Definí los nombres para los dos equipos que integrarán la red P2P:", font=("Arial", 9), wraplength=500, justify="left").pack(anchor="w", pady=5)

        tk.Label(self.container, text="Nombre del Nodo 1 (Esta PC):", font=("Arial", 10, "bold")).pack(anchor="w", pady=(15, 2))
        tk.Entry(self.container, textvariable=self.node1_name, font=("Arial", 10), width=40).pack(anchor="w", pady=2)

        tk.Label(self.container, text="Nombre del Nodo 2 (El otro equipo):", font=("Arial", 10, "bold")).pack(anchor="w", pady=(15, 2))
        tk.Entry(self.container, textvariable=self.node2_name, font=("Arial", 10), width=40).pack(anchor="w", pady=2)

        tk.Button(self.container, text="Siguiente ➡️", bg="#0078D7", fg="white", font=("Arial", 10, "bold"), padx=15, pady=5, command=self.process_node_creation).pack(anchor="e", pady=(30, 0))

    def process_node_creation(self):
        n1 = self.node1_name.get().strip()
        n2 = self.node2_name.get().strip()
        
        if not n1 or not n2:
            messagebox.showwarning("Campos vacíos", "Por favor, ingresá nombres válidos para ambos nodos.")
            return
        if n1 == n2:
            messagebox.showwarning("Nombres iguales", "Los nombres de los nodos deben ser diferentes.")
            return

        self.node_names = [n1, n2]
        self.cluster_state["node_names"] = self.node_names
        self.cluster_state["nodes_configured"] = {n1: False, n2: False}

        try:
            for n in self.node_names:
                get_or_create_folder = lambda s, name, parent: s.files().create(body={'name': name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [parent]}, fields='id').execute().get('id') if not s.files().list(q=f"name = '{name}' and '{parent}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false", fields='files(id)').execute().get('files') else s.files().list(q=f"name = '{name}' and '{parent}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false", fields='files(id)').execute().get('files')[0]['id']
                get_or_create_folder(self.service, f"mailbox_{n}", self.root_folder_id)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron crear los buzones en Google Drive:\n{e}")
            return

        self.show_node_selection_screen()

    def show_node_selection_screen(self):
        self.clear_container()

        tk.Label(self.container, text="Identidad de este Equipo", font=("Arial", 14, "bold")).pack(anchor="w", pady=5)
        tk.Label(self.container, text="Seleccioná qué nodo de la red P2P querés configurar en esta máquina:", font=("Arial", 9), wraplength=500, justify="left").pack(anchor="w", pady=5)

        frame_radio = tk.Frame(self.container, pady=10)
        frame_radio.pack(anchor="w", fill="x")

        for node in self.node_names:
            is_configured = self.nodes_configured.get(node, False)
            state = "disabled" if is_configured else "normal"
            text = f"{node} (Ya configurado)" if is_configured else f"{node} (Disponible)"
            
            rb = tk.Radiobutton(frame_radio, text=text, variable=self.selected_node, value=node, font=("Arial", 10), state=state)
            rb.pack(anchor="w", pady=5)
            if not is_configured and not self.selected_node.get():
                self.selected_node.set(node)

        tk.Button(self.container, text="Siguiente ➡️", bg="#0078D7", fg="white", font=("Arial", 10, "bold"), padx=15, pady=5, command=self.show_path_selection_screen).pack(anchor="e", pady=(30, 0))

    def show_path_selection_screen(self):
        if not self.selected_node.get():
            messagebox.showwarning("Selección requerida", "Por favor, elegí un nodo disponible.")
            return

        self.clear_container()

        tk.Label(self.container, text=f"Carpeta Base para '{self.selected_node.get()}'", font=("Arial", 14, "bold")).pack(anchor="w", pady=5)
        tk.Label(self.container, text="Seleccioná la carpeta local de tu disco que querés mantener sincronizada en el clúster:", font=("Arial", 9), wraplength=500, justify="left").pack(anchor="w", pady=5)

        frame_path = tk.Frame(self.container, pady=15)
        frame_path.pack(anchor="w", fill="x")

        tk.Entry(frame_path, textvariable=self.base_path_var, font=("Arial", 10), width=45).pack(side="left", padx=(0, 10))
        tk.Button(frame_path, text="Examinar...", command=self.browse_folder, font=("Arial", 9)).pack(side="left")

        tk.Button(self.container, text="Finalizar e Instalar 🚀", bg="#28a745", fg="white", font=("Arial", 10, "bold"), padx=15, pady=5, command=self.save_and_finish).pack(anchor="e", pady=(30, 0))

    def browse_folder(self):
        folder_selected = filedialog.askdirectory()
        if folder_selected:
            self.base_path_var.set(folder_selected)

    def save_and_finish(self):
        node_name = self.selected_node.get()
        base_path_str = self.base_path_var.get().strip()

        if not base_path_str:
            messagebox.showwarning("Ruta vacía", "Por favor, seleccioná una ruta válida.")
            return

        base_path = Path(base_path_str)
        if not base_path.exists():
            try:
                base_path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo crear la carpeta base:\n{e}")
                return

        mailbox_name = f"mailbox_{node_name}"
        safe_base_path = str(base_path).replace("\\", "/")

        config_content = f'''# Archivo de configuración autogenerado por el Asistente de SyncBridge
from pathlib import Path

BASE_PATH = Path(r"{safe_base_path}")

CURRENT_NODE = {{
    "name": "{node_name}",
    "mailbox": "{mailbox_name}",
    "base_path": BASE_PATH
}}

GDRIVE_CONFIG = {{
    "folder_id": "{self.root_folder_id}"
}}

SYNC_SECRET = "sync_bridge_secure_token"
'''
        temp_path = None
        try:
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(config_content, encoding='utf-8')

            self.cluster_state["nodes_configured"][node_name] = True
            
            temp_path = Path(tempfile_dir := os.environ.get('TEMP', '.')) / f"cluster_state_{int(time.time() * 1000)}.json"
            temp_path.write_text(json.dumps(self.cluster_state, indent=4), encoding='utf-8')

            media = MediaFileUpload(str(temp_path), mimetype='application/json', resumable=True)
            if self.state_file_id:
                self.service.files().update(fileId=self.state_file_id, media_body=media).execute()
            else:
                file_metadata = {'name': 'cluster_state.json', 'parents': [self.root_folder_id]}
                self.service.files().create(body=file_metadata, media_body=media, fields='id').execute()

            messagebox.showinfo("¡Instalación Completa!", f"Este equipo quedó configurado exitosamente como '{node_name}'.\n¡Ya podés iniciar el sincronizador!")
            self.destroy()
        except Exception as e:
            messagebox.showerror("Error al guardar", f"Ocurrió un error al registrar la configuración:\n{e}")
        finally:
            if temp_path and temp_path.exists():
                for _ in range(3):
                    try:
                        temp_path.unlink()
                        break
                    except (PermissionError, OSError):
                        time.sleep(0.5)

if __name__ == "__main__":
    app = SyncBridgeWizard()
    app.mainloop()