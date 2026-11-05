import asyncio, json, os, time, uuid, sys
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv; load_dotenv("/app/backend/.env")
import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from licensing import reqsig, config as lc
API = open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split()[0].strip().strip('"') + "/api/control-plane"
k = Ed25519PrivateKey.generate()
pem = k.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
async def signed(c, iid, path, payload):
    body = json.dumps(payload).encode(); ts = str(int(time.time())); n = uuid.uuid4().hex
    sig = reqsig.sign_request(k, installation_id=iid, timestamp=ts, nonce=n, body=body)
    h = {reqsig.H_INSTALLATION: iid, reqsig.H_TIMESTAMP: ts, reqsig.H_NONCE: n, reqsig.H_SIGNATURE: sig, "content-type": "application/json"}
    return await c.post(API + path, content=body, headers=h)
async def main():
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(API + "/installation/register", json={"company_name": "Acme Roofing Company", "requested_seats": 5,
            "installation_public_key": pem, "software_version": lc.SOFTWARE_VERSION, "bootstrap_credential": lc.ACTIVATION_BOOTSTRAP_CREDENTIAL})
        print("register", r.status_code); d = r.json(); iid = d["installation_id"]
        r = await signed(c, iid, "/installation/company", {"name": "Acme Roofing Company, LLC"}); print("rename", r.status_code, r.json())
        r = await signed(c, iid, "/installation/company", {"name": "   "}); print("blank", r.status_code)
        r = await c.post(API + "/installation/company", json={"name": "x"}); print("unsigned", r.status_code)
    from control_plane.db import SessionLocal
    from control_plane.models import Company
    async with SessionLocal() as db:
        co = await db.get(Company, uuid.UUID(d["company_id"])); print("db name:", repr(co.name))
asyncio.run(main())
