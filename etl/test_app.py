import requests, time

s = requests.Session()
s.post("http://127.0.0.1:8002/auth/login",
    data={"email": "admin@urbanbike.com", "password": "Urbanbike123!", "next": "/dashboard"},
    allow_redirects=False, timeout=15)

r = s.get("http://127.0.0.1:8002/admin/usuarios", timeout=15)
print("Status:", r.status_code)
# Buscar datos en la tabla
import re
rows = re.findall(r"<tr[^>]*>(.*?)</tr>", r.text, re.DOTALL)
print("Filas en tabla:", len(rows))
# Buscar emails de usuarios
emails = re.findall(r"[\w\.-]+@[\w\.-]+", r.text)
print("Emails encontrados:", emails[:5])
# Ver si hay mensaje de error
if "pb_ok" in r.text or "Error" in r.text:
    print("Posible error en template")
