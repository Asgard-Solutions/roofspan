import asyncio, sys, re, collections
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv; load_dotenv("/app/backend/.env")
from sqlalchemy import text
import db as d
async def main():
    async with d.SessionLocal() as s:
        rows = (await s.execute(text("select name, created_by, is_default, active from price_books"))).all()
        print(len(rows))
        c = collections.Counter(re.sub(r"[0-9a-f]{6,}.*$", "*", r[0]) for r in rows)
        print(c.most_common(30))
        print(collections.Counter(r[1] for r in rows).most_common(10))
asyncio.run(main())
