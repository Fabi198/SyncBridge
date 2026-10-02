import os
import sys
import io
import json
import logging
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, filedialog, ttk
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

CONFIG_FILE = Path("src/config.py")
SCOPES = ['https://www.googleapis.com/auth/drive.file']

class SyncBridgeWizard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SyncBridge - Asistente de Configuración P2P")
        self.geometry("560x520")
        self.resizable(False, False)
        
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
        self.node2_name = tk.StringVar(value="Notebook")
        self.base_path_var = tk.StringVar(value=str(Path.home() / "SyncBridge"))
        
        # Variables para los checkboxes de subcarpetas
        self.subfolder_vars = {}

        self.container = tk.Frame(self, padx=25, pady=25)
        self.container.pack(fill="both", expand=True)

        self.show_credentials_screen()

    def clear_container(self):
        for widget in self.container.winfo_children():
            widget.destroy()

    def show_credentials_screen(self):
        self.clear_container()
        tk.Label(self.container, text="Credenciales de Google Drive", font=("Arial", 16, "bold")).pack(anchor="w", pady=(0, 5))
        tk.Label(self.container, text="Ingresá las credenciales de tu proyecto de Google Cloud (OAuth 2.0):", font=("Arial", 9), wraplength=500, justify="left").pack(anchor="w", pady=(0, 15))

        tk.Label(self.container, text="Client ID:", font=("Arial", 10, "bold")).pack(anchor="w", pady=(5, 2))
        tk.Entry(self.container, textvariable=self.client_id_var, font=("Arial", 10), width=50).pack(anchor="w", pady=2)

        tk.Label(self.container, text="Client Secret:", font=("Arial", 10, "bold")).pack(anchor="w", pady=(10, 2))
        tk.Entry(self.container, textvariable=self.client_secret_var, font=("Arial", 10), width=50, show="*").pack(anchor="w", pady=2)

        tk.Button(self.container, text="Conectar y Autenticar 🔑", bg="#0078D7", fg="white", font=("Arial", 10, "bold"), padx=15, pady=8, command=self.authenticate_with_credentials).pack(anchor="e", pady=(35, 0))

    def authenticate_with_credentials(self):
        client_id = self.client_id_var.get().strip()
        client_secret = self.client_secret_var.get().strip()

        if not client_id or not client_secret:
            messagebox.showwarning("Campos vacíos", "Por favor, ingresá ambos campos.")
            return

        try:
            self.clear_container()
            tk.Label(self.container, text="Autenticando...", font=("Arial", 14, "bold")).pack(anchor="w", pady=10)
            tk.Label(self.container, text="Se abrirá tu navegador web para autorizar el acceso.", font=("Arial", 10)).pack(anchor="w", pady=10)
            self.update()

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

            self.service = build('drive', 'v3', credentials=creds)
            self.root_folder_id = self.get_or_create_root_folder_dynamic()
            self.check_cluster_status()

            if not self.node_names:
                self.show_node_creation_screen()
            else:
                self.show_node_selection_screen()

        except Exception as e:
            messagebox.showerror("Error de Autenticación", f"No se pudo completar la conexión:\n{e}")
            self.show_credentials_screen()

    def get_or_create_root_folder_dynamic(self):
        folder_name = "SyncBridge"
        query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = self.service.files().list(q=query, spaces='drive', fields='files(id, name)').execute().get('files', [])
        if results:
            return results[0]['id']
        file_metadata = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder'}
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
        tk.Label(self.container, text="Definí los nombres para los dos equipos que integrarán la red P2P:", font=("Arial", 9)).pack(anchor="w", pady=5)

        tk.Label(self.container, text="Nombre del Nodo 1 (Esta PC):", font=("Arial", 10, "bold")).pack(anchor="w", pady=(15, 2))
        tk.Entry(self.container, textvariable=self.node1_name, font=("Arial", 10), width=40).pack(anchor="w", pady=2)

        tk.Label(self.container, text="Nombre del Nodo 2 (El otro equipo):", font=("Arial", 10, "bold")).pack(anchor="w", pady=(15, 2))
        tk.Entry(self.container, textvariable=self.node2_name, font=("Arial", 10), width=40).pack(anchor="w", pady=2)

        tk.Button(self.container, text="Siguiente ➡️", bg="#0078D7", fg="white", font=("Arial", 10, "bold"), padx=15, pady=5, command=self.process_node_creation).pack(anchor="e", pady=(30, 0))

    def process_node_creation(self):
        n1 = self.node1_name.get().strip()
        n2 = self.node2_name.get().strip()
        if not n1 or not n2 or n1 == n2:
            messagebox.showwarning("Atención", "Ingresá nombres válidos y diferentes para ambos nodos.")
            return

        self.node_names = [n1, n2]
        self.cluster_state["node_names"] = self.node_names
        self.cluster_state["nodes_configured"] = {n1: False, n2: False}

        try:
            for n in self.node_names:
                get_or_create_folder = lambda s, name, parent: s.files().create(body={'name': name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [parent]}, fields='id').execute().get('id') if not s.files().list(q=f"name = '{name}' and '{parent}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false", fields='files(id)').execute().get('files') else s.files().list(q=f"name = '{name}' and '{parent}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false", fields='files(id)').execute().get('files')[0]['id']
                get_or_create_folder(self.service, f"mailbox_{n}", self.root_folder_id)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron crear los buzones:\n{e}")
            return

        self.show_node_selection_screen()

    def show_node_selection_screen(self):
        self.clear_container()
        tk.Label(self.container, text="Identidad de este Equipo", font=("Arial", 14, "bold")).pack(anchor="w", pady=5)
        tk.Label(self.container, text="Seleccioná qué nodo querés configurar en esta máquina:", font=("Arial", 9)).pack(anchor="w", pady=5)

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
            messagebox.showwarning("Selección requerida", "Elegí un nodo disponible.")
            return

        self.clear_container()
        tk.Label(self.container, text=f"Carpeta Base para '{self.selected_node.get()}'", font=("Arial", 14, "bold")).pack(anchor="w", pady=5)
        tk.Label(self.container, text="Seleccioná la carpeta local principal que querés sincronizar:", font=("Arial", 9)).pack(anchor="w", pady=5)

        frame_path = tk.Frame(self.container, pady=15)
        frame_path.pack(anchor="w", fill="x")

        tk.Entry(frame_path, textvariable=self.base_path_var, font=("Arial", 10), width=45).pack(side="left", padx=(0, 10))
        tk.Button(frame_path, text="Examinar...", command=lambda: self.base_path_var.set(filedialog.askdirectory() or self.base_path_var.get()), font=("Arial", 9)).pack(side="left")

        tk.Button(self.container, text="Siguiente ➡️", bg="#0078D7", fg="white", font=("Arial", 10, "bold"), padx=15, pady=5, command=self.show_subfolder_selection_screen).pack(anchor="e", pady=(30, 0))

    def show_subfolder_selection_screen(self):
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

        self.clear_container()
        
        # Títulos
        tk.Label(self.container, text="Seleccionar Estructura a Sincronizar", font=("Arial", 14, "bold")).pack(anchor="w", pady=(0, 5))
        tk.Label(self.container, text="Expandí las carpetas y marcá las que quieras incluir en la red P2P:", font=("Arial", 9)).pack(anchor="w", pady=(0, 10))

        # --- CONTENEDOR CON ÁRBOL JERÁRQUICO ---
        tree_container = tk.Frame(self.container)
        tree_container.pack(fill="both", expand=True, pady=5)

        tree_scroll = ttk.Scrollbar(tree_container, orient="vertical")
        tree_scroll.pack(side="right", fill="y")

        # Creamos el Treeview (asegurate de tener 'from tkinter import ttk' arriba)
        self.tree = ttk.Treeview(
            tree_container, 
            yscrollcommand=tree_scroll.set, 
            selectmode="browse",
            height=12
        )
        self.tree.pack(side="left", fill="both", expand=True)
        tree_scroll.config(command=self.tree.yview)

        # Diccionario para almacenar las rutas y su estado de selección
        self.tree_vars = {}

        # Función recursiva para poblar carpetas y subcarpetas en forma de árbol
        def populate_tree(parent_id, current_path):
            try:
                for p in sorted(current_path.iterdir()):
                    if p.is_dir() and not p.name.startswith('.'):
                        node_id = self.tree.insert(parent_id, "end", text=f" ☑ {p.name}", open=False)
                        self.tree_vars[node_id] = {"path": p, "selected": True}
                        # Llamada recursiva para subcarpetas anidadas
                        populate_tree(node_id, p)
            except PermissionError:
                pass

        # Nodo raíz principal
        root_id = self.tree.insert("", "end", text=f" 📂 {base_path.name or base_path}", open=True)
        self.tree_vars[root_id] = {"path": base_path, "selected": True}
        
        # Construir el árbol completo de directorios
        populate_tree(root_id, base_path)

        # Evento para alternar el checkbox al hacer clic sobre un elemento del árbol
        def on_tree_click(event):
            item_id = self.tree.identify_row(event.y)
            if item_id and item_id in self.tree_vars:
                current_state = self.tree_vars[item_id]["selected"]
                new_state = not current_state
                self.tree_vars[item_id]["selected"] = new_state
                
                # Actualizar icono visual de selección
                current_text = self.tree.item(item_id, "text")
                for old_icon in [" ☑ ", " ◻ ", " 📂 "]:
                    current_text = current_text.replace(old_icon, "")
                
                icon = " ☑ " if new_state else " ◻ "
                prefix = " 📂 " if item_id == root_id else icon
                self.tree.item(item_id, text=f"{prefix}{current_text.strip()}")

        self.tree.bind("<Button-1>", on_tree_click)

        # --- BOTÓN FIJO ABAJO ---
        btn_finish = tk.Button(
            self.container, 
            text="Finalizar e Instalar 🚀", 
            bg="#28a745", 
            fg="white", 
            font=("Arial", 10, "bold"), 
            padx=15, 
            pady=8, 
            command=self.save_and_finish_tree
        )
        btn_finish.pack(anchor="e", pady=(15, 0))

    def save_and_finish_tree(self):
        # Recolectar rutas relativas de las subcarpetas seleccionadas en el árbol
        base_path_str = self.base_path_var.get().strip()
        base_path = Path(base_path_str)
        
        selected_subfolders = []
        for node_id, data in self.tree_vars.items():
            if data["selected"] and data["path"] != base_path:
                try:
                    rel_path = data["path"].relative_to(base_path)
                    selected_subfolders.append(str(rel_path).replace("\\", "/"))
                except ValueError:
                    pass

        # Inyectamos la lista en la variable que lee el guardado y ejecutamos
        self.subfolder_vars_list = selected_subfolders
        self.save_and_finish_custom(selected_subfolders)

    def save_and_finish_custom(self, selected_subfolders):
        node_name = self.selected_node.get()
        base_path_str = self.base_path_var.get().strip()
        base_path = Path(base_path_str)
        mailbox_name = f"mailbox_{node_name}"
        safe_base_path = str(base_path).replace("\\", "/")

        client_id_val = self.client_id_var.get().strip()
        client_secret_val = self.client_secret_var.get().strip()

        config_content = f'''# Archivo de configuración autogenerado por el Asistente de SyncBridge
from pathlib import Path

BASE_PATH = Path(r"{safe_base_path}")

CURRENT_NODE = {{
    "name": "{node_name}",
    "mailbox": "{mailbox_name}",
    "base_path": BASE_PATH,
    "included_subfolders": {selected_subfolders}
}}

GDRIVE_CONFIG = {{
    "folder_id": "{self.root_folder_id}",
    "client_id": "{client_id_val}",
    "client_secret": "{client_secret_val}"
}}

SYNC_SECRET = "sync_bridge_secure_token"
'''
        try:
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(config_content, encoding='utf-8')

            self.cluster_state["nodes_configured"][node_name] = True
            
            json_data = json.dumps(self.cluster_state, indent=4).encode('utf-8')
            fh = io.BytesIO(json_data)
            media = MediaIoBaseUpload(fh, mimetype='application/json', resumable=True)

            state_query = f"name = 'cluster_state.json' and '{self.root_folder_id}' in parents and trashed = false"
            state_files = self.service.files().list(q=state_query, spaces='drive', fields='files(id)').execute().get('files', [])

            if state_files:
                self.state_file_id = state_files[0]['id']
                for extra in state_files[1:]:
                    try:
                        self.service.files().delete(fileId=extra['id']).execute()
                    except Exception:
                        pass
                self.service.files().update(fileId=self.state_file_id, media_body=media).execute()
            else:
                file_metadata = {'name': 'cluster_state.json', 'parents': [self.root_folder_id]}
                created = self.service.files().create(body=file_metadata, media_body=media, fields='id').execute()
                self.state_file_id = created.get('id')

            messagebox.showinfo("¡Instalación Completa!", f"Este equipo quedó configurado como '{node_name}'.\n¡Ya podés iniciar!")
            self.destroy()
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo guardar:\n{e}")
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

        # Escanear subcarpetas directas dentro de la carpeta base
        try:
            subfolders = [f.name for f in base_path.iterdir() if f.is_dir() and not f.name.startswith('.')]
        except Exception:
            subfolders = []

        self.clear_container()
        
        # Títulos
        tk.Label(self.container, text="Seleccionar Subcarpetas a Sincronizar", font=("Arial", 14, "bold")).pack(anchor="w", pady=(0, 5))
        tk.Label(self.container, text="Marcá las subcarpetas que querés incluir en la sincronización P2P:", font=("Arial", 9)).pack(anchor="w", pady=(0, 10))

        # --- CONTENEDOR CON SCROLL PARA LOS CHECKBOXES ---
        outer_frame = tk.Frame(self.container)
        outer_frame.pack(fill="both", expand=True, pady=5)

        canvas = tk.Canvas(outer_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer_frame, orient="vertical", command=canvas.yview) if 'ttk' in globals() or 'ttk' in locals() else tk.Scrollbar(outer_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.subfolder_vars.clear()

        if not subfolders:
            tk.Label(scrollable_frame, text="(No se encontraron subcarpetas directas. Se sincronizará toda la raíz).", font=("Arial", 9, "italic"), fg="gray").pack(anchor="w", pady=10)
        else:
            for sub in subfolders:
                var = tk.BooleanVar(value=True)  # Por defecto marcadas
                self.subfolder_vars[sub] = var
                cb = tk.Checkbutton(scrollable_frame, text=sub, variable=var, font=("Arial", 10))
                cb.pack(anchor="w", pady=3)

        # --- BOTÓN FIJO ABAJO (Siempre visible) ---
        btn_finish = tk.Button(
            self.container, 
            text="Finalizar e Instalar 🚀", 
            bg="#28a745", 
            fg="white", 
            font=("Arial", 10, "bold"), 
            padx=15, 
            pady=8, 
            command=self.save_and_finish
        )
        btn_finish.pack(anchor="e", pady=(15, 0))

    def save_and_finish_tree(self):
        # Recolectar rutas relativas o absolutas seleccionadas desde el árbol
        base_path_str = self.base_path_var.get().strip()
        base_path = Path(base_path_str)
        
        selected_subfolders = []
        for node_id, data in self.tree_vars.items():
            if data["selected"] and data["path"] != base_path:
                try:
                    rel_path = data["path"].relative_to(base_path)
                    selected_subfolders.get if hasattr(selected_subfolders, "get") else selected_subfolders.append(str(rel_path))
                except ValueError:
                    pass

        # Reutilizamos la lógica existente de guardado pasando las subcarpetas seleccionadas
        # (Asegúrate de que 'save_and_finish' tome 'selected_subfolders' o actualiza las variables globales antes de llamarlo)
        self.selected_subfolders_final = selected_subfolders
        self.save_and_finish()


    def save_and_finish(self):
        node_name = self.selected_node.get()
        base_path_str = self.base_path_var.get().strip()
        base_path = Path(base_path_str)
        mailbox_name = f"mailbox_{node_name}"
        safe_base_path = str(base_path).replace("\\", "/")

        # Obtener lista de subcarpetas seleccionadas por el usuario
        selected_subfolders = [sub for sub, var in self.subfolder_vars.items() if var.get()]

        client_id_val = self.client_id_var.get().strip()
        client_secret_val = self.client_secret_var.get().strip()

        # Guardar configuración incluyendo las subcarpetas elegidas
        config_content = f'''# Archivo de configuración autogenerado por el Asistente de SyncBridge
from pathlib import Path

BASE_PATH = Path(r"{safe_base_path}")

CURRENT_NODE = {{
    "name": "{node_name}",
    "mailbox": "{mailbox_name}",
    "base_path": BASE_PATH,
    "included_subfolders": {selected_subfolders}
}}

GDRIVE_CONFIG = {{
    "folder_id": "{self.root_folder_id}",
    "client_id": "{client_id_val}",
    "client_secret": "{client_secret_val}"
}}

SYNC_SECRET = "sync_bridge_secure_token"
'''
        try:
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(config_content, encoding='utf-8')

            self.cluster_state["nodes_configured"][node_name] = True
            
            json_data = json.dumps(self.cluster_state, indent=4).encode('utf-8')
            fh = io.BytesIO(json_data)
            media = MediaIoBaseUpload(fh, mimetype='application/json', resumable=True)

            state_query = f"name = 'cluster_state.json' and '{self.root_folder_id}' in parents and trashed = false"
            state_files = self.service.files().list(q=state_query, spaces='drive', fields='files(id)').execute().get('files', [])

            if state_files:
                self.state_file_id = state_files[0]['id']
                for extra in state_files[1:]:
                    try:
                        self.service.files().delete(fileId=extra['id']).execute()
                    except Exception:
                        pass
                
                self.service.files().update(fileId=self.state_file_id, media_body=media).execute()
            else:
                file_metadata = {'name': 'cluster_state.json', 'parents': [self.root_folder_id]}
                created = self.service.files().create(body=file_metadata, media_body=media, fields='id').execute()
                self.state_file_id = created.get('id')

            messagebox.showinfo("¡Instalación Completa!", f"Este equipo quedó configurado como '{node_name}'.\n¡Ya podés iniciar!")
            self.destroy()
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo guardar:\n{e}")

def run_setup_wizard() -> bool:
    if CONFIG_FILE.exists():
        try:
            sys.path.append(str(Path(__file__).parent.parent))
            from src.config import GDRIVE_CONFIG, CURRENT_NODE
            if GDRIVE_CONFIG.get("folder_id") and CURRENT_NODE.get("name"):
                return True
        except Exception:
            pass

    app = SyncBridgeWizard()
    app.mainloop()

    if CONFIG_FILE.exists():
        try:
            from src.config import GDRIVE_CONFIG, CURRENT_NODE
            if GDRIVE_CONFIG.get("folder_id") and CURRENT_NODE.get("name"):
                return True
        except Exception:
            pass
            
    return False