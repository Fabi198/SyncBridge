import platform
from pathlib import Path

# Configuracion  estatica del cluster simetrico
NODES_CONFIG = {

    "DESKTOP-NU4MNUF": {
        "node_id": 0,
        "name": "Notebook",
        "base_path": Path(r"D:\\"),
        "mailbox": "Buzon_Notebook"
    },
    "DESKTOP-4045BGE": {
        "node_id": 1,
        "name": "PC",
        "base_path": Path(r"D:\\"),
        "mailbox": "Buzon_PC"
    }

}


def get_current_node() -> dict:
    """
    Identifica automáticamente el nodo actual comparando el hostname
    del sistema operativo con el registro del clúster.
    """
    hostname = platform.node()

    if hostname not in NODES_CONFIG:
        raise PermissionError(
            f"❌ Error de Autenticación: Este equipo (Hostname: '{hostname}') "
            f"no está autorizado en la configuración de Sync-Bridge."
        )

    node_data = NODES_CONFIG[hostname]
    return {
        "node_id": node_data["node_id"],
        "name": node_data["name"],
        "base_path": node_data["base_path"],
        "mailbox": node_data["mailbox"],
        "hostname": hostname
    }

# Instancia global de la configuración activa para el nodo actual
CURRENT_NODE = get_current_node()

if __name__ == "__main__":
    print("=" * 40)
    print(" 🚀 SYNC-BRIDGE: NODO INICIALIZADO ")
    print("=" * 40)
    print(f"• Dispositivo: {CURRENT_NODE['name']}")
    print(f"• ID de Nodo:  Node {CURRENT_NODE['node_id']}")
    print(f"• Hostname:    {CURRENT_NODE['hostname']}")
    print(f"• Ruta Base:   {CURRENT_NODE['base_path']}")
    print(f"• Buzón Nube:  {CURRENT_NODE['mailbox']}")
    print("=" * 40)