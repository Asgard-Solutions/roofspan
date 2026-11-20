import asyncio, sys, time, json
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv; load_dotenv("/app/backend/.env")
from sqlalchemy import select
import db as d
from models import Material
from routers.operations import _mat_list_item
from services import inventory_core as ic, pricing as ps
async def main():
    async with d.SessionLocal() as s:
        mats = (await s.execute(select(Material).order_by(Material.name))).scalars().all()
        t = time.time(); old = [ (await _mat_list_item(s, m)).model_dump() for m in mats ]; t1 = time.time() - t
        t = time.time()
        pf = await ps.pricing_prefetch(s, [m.id for m in mats]); qs = await ic.batch_quantities(s, mats)
        new = [ (await _mat_list_item(s, m, pf, qs[m.id])).model_dump() for m in mats ]; t2 = time.time() - t
        diff = [(o["name"], k, o[k], n[k]) for o, n in zip(old, new) for k in o if o[k] != n[k]]
        print("per-row", round(t1,2), "batched", round(t2,2), "materials", len(mats), "diffs", len(diff), diff[:5])
asyncio.run(main())
