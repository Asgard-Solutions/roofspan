import asyncio, sys, time
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv; load_dotenv("/app/backend/.env")
from sqlalchemy import select
import db as d
from models import PurchaseOrder
from routers.purchasing import _out, list_pos
async def main():
    async with d.SessionLocal() as s:
        pos = (await s.execute(select(PurchaseOrder).order_by(PurchaseOrder.created_at.desc()))).scalars().all()
        t=time.time(); old=[(await _out(s, p)).model_dump() for p in pos]; t1=time.time()-t
        t=time.time(); new=[x.model_dump() for x in await list_pos(None, None, None, s)]; t2=time.time()-t
        print("pos", len(pos), "per-row", round(t1,2), "batched", round(t2,2), "equal", old==new)
asyncio.run(main())
