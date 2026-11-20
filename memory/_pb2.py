import asyncio, sys, re, collections
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv; load_dotenv("/app/backend/.env")
from sqlalchemy import text
import db as d
async def main():
    async with d.SessionLocal() as s:
        rows = (await s.execute(text("select name from price_books order by name"))).scalars().all()
        seen=set()
        for n in rows:
            k=n.split(" ")[0]
            if k not in seen: seen.add(k); print(repr(n))
        print((await s.execute(text("select conname, conrelid::regclass, confdeltype from pg_constraint where confrelid='price_books'::regclass"))).all())
asyncio.run(main())
