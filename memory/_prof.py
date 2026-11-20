import asyncio, sys, time
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv; load_dotenv("/app/backend/.env")
from sqlalchemy import select, event
import db as d
from models import Material
from services import inventory_core as ic, pricing as ps
async def main():
    cnt = {"n": 0}
    event.listen(d.engine.sync_engine, "before_cursor_execute", lambda *a, **k: cnt.__setitem__("n", cnt["n"] + 1))
    async with d.SessionLocal() as s:
        mats = (await s.execute(select(Material))).scalars().all()
        for name, fn in [("qty", ic.compute_quantities), ("pref", lambda s_, m: ic.preferred_supplier_material(s_, m.id)),
                         ("best", lambda s_, m: ic.best_known_supplier_material(s_, m.id)), ("count", lambda s_, m: ic.supplier_material_count(s_, m.id)),
                         ("pricing", ps.compute_material_pricing)]:
            cnt["n"] = 0; t = time.time()
            for m in mats: await fn(s, m)
            print(name, round(time.time() - t, 2), "s", cnt["n"], "queries")
asyncio.run(main())
