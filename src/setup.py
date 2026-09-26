import os
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from dotenv import load_dotenv

ENV_PATH = Path(".env")
RULES_PATH = Path("sync_rules.json")

class SetupWizardGUI:
    """Ventana gráfica completa para el primer arranque (credenciales + carpeta base + reglas)"""
    def __init__(self, root):
        self.root = root
        self.root.title("SyncBridge - Configuración Inicial")
        self.root.geometry("600x620")
        self.root.minsize(500, 500)
        self.root.config(bg="#f4f6f9")
        
        self.base_path = Path.home() / "SyncBridgeFolder"
        self.base_path.mkdir(exist_ok=True)
        self.checked_paths = set()
        self.node_states = {}
        
        # Cabecera
        header = tk.Frame(root, bg="#0f52ba", pady=12)
        header.pack(fill=tk.X)
        tk.Label(header, text="🚀 Bienvenido a SyncBridge - Configuración Inicial", fg="white", bg="#0f52ba", font=("Arial", 11, "bold")).pack()
        
        # Contenedor principal con Scroll o Padding
        body = tk.Frame(root, bg="#f4f6f9", padx=15, pady=10)
        body.pack(fill=tk.BOTH, expand=True)
        
        # 1. Sección Credenciales Google
        cred_frame = tk.LabelFrame(body, text=" 🔑 Credenciales de Google Drive API ", bg="#f4f6f9", fg="#0f52ba", font=("Arial", 9, "bold"), padx=10, pady=8)
        cred_frame.pack(fill=tk.X, pady=(0, 10))
        
        tk.Label(cred_frame, text="Client ID:", bg="#f4f6f9", font=("Arial", 8)).pack(anchor=tk.W)
        self.client_id_entry = tk.Entry(cred_frame, font=("Arial", 9), relief=tk.SOLID, bd=1)
        self.client_id_entry.pack(fill=tk.X, pady=(0, 5), ipady=2)
        
        tk.Label(cred_frame, text="Client Secret:", bg="#f4f6f9", font=("Arial", 8)).pack(anchor=tk.W)
        self.client_secret_entry = tk.Entry(cred_frame, font=("Arial", 9), relief=tk.SOLID, bd=1, show="*")
        self.client_secret_entry.pack(fill=tk.X, ipady=2)

        # 2. Sección Carpeta Base
        path_frame = tk.LabelFrame(body, text=" 📁 Carpeta Base a Monitorear ", bg="#f4f6f9", fg="#0f52ba", font=("Arial", 9, "bold"), padx=10, pady=8)
        path_frame.pack(fill=tk.X, pady=(0, 10))
        
        p_box = tk.Frame(path_frame, bg="#f4f6f9")
        p_box.pack(fill=tk.X)
        
        self.path_entry = tk.Entry(p_box, font=("Arial", 9), relief=tk.SOLID, bd=1)
        self.path_entry.insert(0, str(self.base_path))
        self.path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=2)
        
        tk.Button(p_box, text="Examinar...", bg="#6c757d", fg="white", font=("Arial", 8), command=self.browse_base).pack(side=tk.RIGHT, padx=5)

        # 3. Sección Subcarpetas (Árbol con Checkboxes)
        tree_frame_container = tk.LabelFrame(body, text=" ☑️ Subcarpetas a Sincronizar (Opcional - Vacío = Todo) ", bg="#f4f6f9", fg="#0f52ba", font=("Arial", 9, "bold"), padx=10, pady=8)
        tree_frame_container.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        tree_box = tk.Frame(tree_frame_container, bg="#f4f6f9")
        tree_box.pack(fill=tk.BOTH, expand=True)
        
        self.tree = ttk.Treeview(tree_box, columns=("path",), selectmode="browse", height=6)
        self.tree.heading("#0", text="Estructura", anchor=tk.W)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(tree_box, orient=tk.VERTICAL, command=self.tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.config(yscrollcommand=scrollbar.set)
        
        self.load_tree_data()
        self.tree.bind("<Button-1>", self.on_click)
        self.tree.bind("<<TreeviewOpen>>", self.on_expand)

        # Botón Guardar
        tk.Button(body, text="💾 Guardar y Arrancar SyncBridge", bg="#28a745", fg="white", font=("Arial", 10, "bold"), pady=8, command=self.save_and_exit).pack(fill=tk.X)

    def load_tree_data(self):
        for child in self.tree.get_children():
            self.tree.delete(child)
        self.node_states.clear()
        
        if not self.base_path.exists():
            return
            
        is_checked = str(self.base_path) in self.checked_paths
        icon = "☑" if is_checked else "☐"
        root_id = self.tree.insert("", "end", text=f"{icon} {self.base_path.name or self.base_path}", open=True, values=[str(self.base_path)])
        self.node_states[root_id] = is_checked
        self.populate_children(root_id, self.base_path)

    def populate_children(self, parent_id, parent_path):
        for child in self.tree.get_children(parent_id):
            if self.tree.item(child, "text") == "Cargando...":
                self.tree.delete(child)
        try:
            for entry in sorted(parent_path.iterdir()):
                if entry.is_dir() and not entry.name.startswith('.'):
                    ep_str = str(entry.resolve())
                    is_chk = ep_str in self.checked_paths
                    icon = "☑" if is_chk else "☐"
                    cid = self.tree.insert(parent_id, "end", text=f"{icon} {entry.name}", values=[ep_str])
                    self.node_states[cid] = is_chk
                    try:
                        if any(e.is_dir() for e in entry.iterdir() if not e.name.startswith('.')):
                            self.tree.insert(cid, "end", text="Cargando...")
                    except PermissionError:
                        pass
        except PermissionError:
            pass

    def on_expand(self, event):
        item_id = self.tree.focus()
        if not item_id:
            return
        children = self.tree.get_children(item_id)
        if len(children) == 1 and self.tree.item(children[0], "text") == "Cargando...":
            path_str = self.tree.item(item_id, "values")[0]
            self.populate_children(item_id, Path(path_str))

    def on_click(self, event):
        if self.tree.identify("region", event.x, event.y) == "tree":
            item_id = self.tree.identify_row(event.y)
            if item_id:
                new_state = not self.node_states.get(item_id, False)
                self.node_states[item_id] = new_state
                path_str = self.tree.item(item_id, "values")[0]
                if new_state: self.checked_paths.add(path_str)
                else: self.checked_paths.discard(path_str)
                curr_txt = self.tree.item(item_id, "text")[2:]
                self.tree.item(item_id, text=f"{'☑' if new_state else '☐'} {curr_txt}")

    def browse_base(self):
        sel = filedialog.askdirectory(title="Seleccionar Carpeta Base", initialdir=str(self.base_path))
        if sel:
            self.base_path = Path(sel).resolve()
            self.path_entry.delete(0, tk.END)
            self.path_entry.insert(0, str(self.base_path))
            self.load_tree_data()

    def save_and_exit(self):
        cid = self.client_id_entry.get().strip()
        csec = self.client_secret_entry.get().strip()
        bpath = self.path_entry.get().strip()
        
        if not cid or not csec:
            messagebox.showerror("Error", "Debes ingresar las credenciales de Google Client ID y Secret.")
            return
        if not bpath or not Path(bpath).exists():
            messagebox.showerror("Error", "La ruta base especificada no es válida.")
            return
            
        self.config_data = {
            "client_id": cid,
            "client_secret": csec,
            "base_path": bpath,
            "rules": list(self.checked_paths)
        }
        self.root.destroy()

def run_setup_wizard():
    load_dotenv(ENV_PATH)
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    base_path = os.getenv("BASE_PATH")
    
    if client_id and client_secret and base_path and Path(base_path).exists():
        return True # Ya está configurado, arranca silencioso
        
    root = tk.Tk()
    wizard = SetupWizardGUI(root)
    root.mainloop()
    
    if not hasattr(wizard, "config_data"):
        return False
        
    data = wizard.config_data
    node_name = Path(data["base_path"]).name or "MiPC"
    
    # Guardar .env
    env_content = f"""GOOGLE_CLIENT_ID={data['client_id']}
GOOGLE_CLIENT_SECRET={data['client_secret']}
BASE_PATH={data['base_path']}
NODE_NAME={node_name}
"""
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write(env_content)
        
    # Guardar sync_rules.json
    with open(RULES_PATH, "w", encoding="utf-8") as f:
        json.dump({"included_paths": data["rules"]}, f, indent=4)
        
    return True