import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv; load_dotenv()
import app.db.pocketbase as pbmod
pbmod._admin_client = None
pb = pbmod.get_admin_client()
print("Auth OK")
for col in ["users", "roles", "bicicletas", "estaciones", "tarifas", "bitacora_cambios", "auditoria"]:
    try:
        r = pb.list_records(col, per_page=1)
        print(f"  {col}: OK ({r.get('totalItems', '?')} items)")
    except Exception as e:
        print(f"  {col}: ERROR - {e}")
