import asyncio, sys, re
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv; load_dotenv("/app/backend/.env")
from sqlalchemy import text
import db as d
async def main():
    async with d.SessionLocal() as s:
        rows = (await s.execute(text("select name from price_books"))).scalars().all()
        import collections
        print(collections.Counter((n.split(" ")[0], len(n.split(" ")[-1])) for n in rows))
        print((await s.execute(text("select count(*) from estimates where price_book_id in (select id from price_books where name <> 'Standard')"))).scalar())
        print((await s.execute(text("select table_name from information_schema.columns where column_name like '%price_book_id%'"))).scalars().all())
asyncio.run(main())
