import asyncio, sys
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv; load_dotenv("/app/backend/.env")
import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from licensing import config as lc
API = open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split()[0].strip().strip('"') + "/api/control-plane"
def pem():
    k = Ed25519PrivateKey.generate()
    return k.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
def body(p, name="Acme Roofing Company"):
    return {"company_name": name, "requested_seats": 5, "installation_public_key": p,
            "software_version": lc.SOFTWARE_VERSION, "bootstrap_credential": lc.ACTIVATION_BOOTSTRAP_CREDENTIAL}
async def main():
    async with httpx.AsyncClient(timeout=60) as c:
        p = pem()
        rs = [await c.post(API + path, json=body(p)) for path in ("/activate", "/installation/register", "/activate")]
        print("sequential:", [r.status_code for r in rs], "companies:", {r.json()["company_id"] for r in rs})
        p2 = pem()
        rs = await asyncio.gather(*[c.post(API + ("/activate" if i % 2 else "/installation/register"), json=body(p2)) for i in range(6)])
        print("concurrent:", [r.status_code for r in rs], "companies:", {r.json()["company_id"] for r in rs})
        p3, p4 = pem(), pem()
        a = (await c.post(API + "/installation/register", json=body(p3))).json()["company_id"]
        b = (await c.post(API + "/installation/register", json=body(p4))).json()["company_id"]
        print("different offices -> different companies:", a != b)
asyncio.run(main())
