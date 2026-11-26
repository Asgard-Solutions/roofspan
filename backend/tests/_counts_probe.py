import asyncio, os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
T=["territories","canvass_sections","import_jobs","assemblies","inventory_locations","price_books","crews","materials","suppliers","customers","leads","properties","estimates","quotes","jobs","invoices","inspections","measurement_sets","purchase_orders","job_materials","inventory_txns","po_status_history","audit_logs","users","visits"]
async def m():
    e=create_async_engine(os.environ["DATABASE_URL"],poolclass=NullPool)
    async with e.connect() as c:
        print({t:(await c.execute(text(f"select count(*) from {t}"))).scalar() for t in T}, "sum_delta", (await c.execute(text("select sum(delta) from inventory_txns"))).scalar(), "onhand", (await c.execute(text("select sum(quantity_on_hand) from materials"))).scalar())
    await e.dispose()
asyncio.run(m())
