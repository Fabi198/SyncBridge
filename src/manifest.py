import sys
import json
from pathlib import Path

MANIFEST_PATH = Path("sync_manifest.json")
RULES_PATH = Path("sync_rules.json")

def load_sync_rules():
    """Carga las reglas de carpetas permitidas definidas por el usuario"""
    if RULES_PATH.exists():
        try:
            with open(RULES_PATH, 'r', encoding='utf-8') as f:
                return json.load(f).get("included_paths", [])
        except Exception:
            pass
    return [] # Si no hay reglas definidas, por defecto sincroniza todo

def should_ignore(path, base_path):
    """Determina si un archivo o carpeta debe ser ignorado según las reglas dinámicas"""
    path_obj = Path(path).resolve()
    base_obj = Path(base_path).resolve()
    
    try:
        rel_path = path_obj.relative_to(base_obj)
    except ValueError:
        return True

    included_paths = load_sync_rules()
    
    # Si el usuario configuró rutas específicas a incluir mediante la GUI/reglas:
    if included_paths:
        is_allowed = False
        for inc in included_paths:
            inc_path = Path(inc).resolve()
            # Permitir si el archivo es la misma ruta permitida o está dentro de ella
            if path_obj == inc_path or inc_path in path_obj.parents:
                is_allowed = True
                break
        if not is_allowed:
            return True # Ignorar por completo si no está en la lista blanca
            
    return False

def generate_initial_scan(base_path, node_name, on_progress=None):
    """Escanea el disco base reportando el progreso mediante callback o consola"""
    base = Path(base_path)
    manifest = {
        "node_name": node_name,
        "files": {}
    }
    
    if not base.exists():
        print(f"❌ La ruta base {base_path} no existe.")
        return manifest
        
    print(f"\n🔍 Iniciando escaneo inicial de: {base_path}")
    
    count = 0
    
    try:
        for path in base.rglob('*'):
            if path.is_file():
                if should_ignore(path, base):
                    continue
                    
                try:
                    rel_path = str(path.relative_to(base))
                    stat = path.stat()
                    
                    manifest["files"][rel_path] = {
                        "mtime": stat.st_mtime,
                        "size": stat.st_size
                    }
                    
                    count += 1
                    
                    # 🚀 Reportar a la GUI gráfica (si existe) o mantener fallback en consola
                    if on_progress:
                        on_progress(rel_path)
                    else:
                        file_display = (rel_path[:45] + '...') if len(rel_path) > 48 else rel_path
                        sys.stdout.write(f"\r📁 Archivos indexados: {count:,} | Procesando: {file_display:<50}")
                        sys.stdout.flush()
                        
                except (PermissionError, FileNotFoundError):
                    continue
                    
    except KeyboardInterrupt:
        print("\n\n⚠️ Escaneo interrumpido por el usuario.")
        return manifest
        
    print(f"\n\n✅ ¡Escaneo inicial finalizado! Total de archivos indexados: {count:,}")
    save_manifest(manifest)
    return manifest

def load_or_create_manifest(base_path, node_name, on_progress=None):
    """Carga el manifiesto local instantáneamente si existe; si no, ejecuta el escaneo inicial"""
    if MANIFEST_PATH.exists():
        try:
            with open(MANIFEST_PATH, 'r', encoding='utf-8') as f:
                print("⚡ Manifiesto local cargado instantáneamente desde caché.")
                return json.load(f)
        except Exception:
            pass
            
    return generate_initial_scan(base_path, node_name, on_progress=on_progress)

def save_manifest(manifest_data):
    """Guarda el manifiesto actualizado en el disco local"""
    with open(MANIFEST_PATH, 'w', encoding='utf-8') as f:
        json.dump(manifest_data, f, indent=4)