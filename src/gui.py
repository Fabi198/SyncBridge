import json
import os
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox
from src.config import BASE_PATH

RULES_PATH = Path("sync_rules.json")

def load_rules():
    if RULES_PATH.exists():
        try:
            with open(RULES_PATH, 'r', encoding='utf-8') as f:
                return json.load(f).get("included_paths", [])
        except Exception:
            pass
    return []

def save_rules(paths):
    with open(RULES_PATH, 'w', encoding='utf-8') as f:
        json.dump({"included_paths": paths}, f, indent=4)

class CheckTreeviewGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("SyncBridge - Selector de Carpetas")
        self.root.geometry("600x500")
        self.root.minsize(500, 400)
        self.root.config(bg="#f4f6f9")
        
        # Cabecera
        header_frame = tk.Frame(root, bg="#0f52ba", pady=12)
        header_frame.pack(fill=tk.X)
        tk.Label(header_frame, text="📁 Selector Jerárquico de Carpetas", fg="white", bg="#0f52ba", font=("Arial", 11, "bold")).pack()
        tk.Label(header_frame, text=f"Ruta Base: {BASE_PATH}", fg="#d0e1fd", bg="#0f52ba", font=("Arial", 9)).pack()

        # Contenedor principal
        content_frame = tk.Frame(root, bg="#f4f6f9", padx=15, pady=15)
        content_frame.pack(fill=tk.BOTH, expand=True)
        
        tk.Label(content_frame, text="Seleccioná las casillas de las carpetas que deseas sincronizar:", bg="#f4f6f9", fg="#333", justify=tk.LEFT).pack(anchor=tk.W, pady=(0, 8))
        
        # Treeview con Scrollbars
        tree_frame = tk.Frame(content_frame, bg="#f4f6f9")
        tree_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.tree = ttk.Treeview(tree_frame, columns=("path",), selectmode="browse")
        self.tree.heading("#0", text="Carpetas", anchor=tk.W)
        self.tree.column("#0", width=450, anchor=tk.W)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.config(yscrollcommand=scrollbar.set)
        
        # Estado de selección (almacena rutas completas checkeadas)
        self.checked_paths = set(os.path.abspath(p) for p in load_rules())
        self.node_states = {} # item_id -> bool
        
        # Construir árbol inicial (raiz)
        self.populate_root()
        
        # Eventos
        self.tree.bind("<Button-1>", self.on_click)
        self.tree.bind("<<TreeviewOpen>>", self.on_expand)

        # Botonera inferior
        btn_frame = tk.Frame(content_frame, bg="#f4f6f9", pady=10)
        btn_frame.pack(fill=tk.X)
        
        tk.Button(btn_frame, text="❌ Desmarcar Todo", bg="#dc3545", fg="white", font=("Arial", 9, "bold"), padx=8, pady=4, command=self.clear_all).pack(side=tk.LEFT, padx=2)
        tk.Button(btn_frame, text="💾 Guardar Cambios", bg="#0f52ba", fg="white", font=("Arial", 9, "bold"), padx=10, pady=4, command=self.save_and_close).pack(side=tk.RIGHT, padx=2)

    def populate_root(self):
        base = Path(BASE_PATH).resolve()
        if not base.exists():
            return
        
        is_checked = str(base) in self.checked_paths
        icon = "☑" if is_checked else "☐"
        
        root_id = self.tree.insert("", "end", text=f"{icon} {base.name or base}", open=True, values=[str(base)])
        self.node_states[root_id] = is_checked
        
        self.populate_children(root_id, base)

    def populate_children(self, parent_id, parent_path):
        # Limpiar hijos actuales para evitar duplicados
        for child in self.tree.get_children(parent_id):
            self.tree.delete(child)
            
        try:
            for entry in sorted(parent_path.iterdir()):
                if entry.is_dir():
                    # Omitir carpetas ocultas o de sistema pesadas si es necesario
                    if entry.name.startswith('.'):
                        continue
                        
                    entry_path_str = str(entry.resolve())
                    is_checked = entry_path_str in self.checked_paths
                    icon = "☑" if is_checked else "☐"
                    
                    child_id = self.tree.insert(parent_id, "end", text=f"{icon} {entry.name}", values=[entry_path_str])
                    self.node_states[child_id] = is_checked
                    
                    # Añadir un nodo dummy si tiene subdirectorios para permitir expandir
                    try:
                        if any(e.is_dir() for e in entry.iterdir() if not e.name.startswith('.')):
                            self.tree.insert(child_id, "end", text="Cargando...")
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
        region = self.tree.identify("region", event.x, event.y)
        if region == "tree":
            item_id = self.tree.identify_row(event.y)
            if item_id:
                # Cambiar estado del checkbox al hacer clic en el ícono/texto del árbol
                current_state = self.node_states.get(item_id, False)
                new_state = not current_state
                self.node_states[item_id] = new_state
                
                path_str = self.tree.item(item_id, "values")[0]
                if new_state:
                    self.checked_paths.add(path_str)
                else:
                    self.checked_paths.discard(path_str)
                    
                # Actualizar texto visual del nodo
                current_text = self.tree.item(item_id, "text")[2:] # Quitar el checkbox viejo
                icon = "☑" if new_state else "☐"
                self.tree.item(item_id, text=f"{icon} {current_text}")

    def clear_all(self):
        self.checked_paths.clear()
        for item_id in self.node_states:
            self.node_states[item_id] = False
            current_text = self.tree.item(item_id, "text")[2:]
            self.tree.item(item_id, text=f"☐ {current_text}")

    def save_and_close(self):
        save_rules(list(self.checked_paths))
        messagebox.showinfo("Éxito", "¡Reglas de sincronización actualizadas con éxito!")
        self.root.destroy()

def open_sync_gui():
    root = tk.Tk()
    app = CheckTreeviewGUI(root)
    root.mainloop()