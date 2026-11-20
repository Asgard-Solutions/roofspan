import asyncio, sys
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv; load_dotenv("/app/backend/.env")
from sqlalchemy import text
import db as d
async def main():
    async with d.SessionLocal() as s:
        print((await s.execute(text("select name, is_default, active, created_at from price_books where is_default or name='Standard'"))).all())
        print((await s.execute(text("select count(*) from estimates e where price_book_id in (select id from price_books where name ~ '^(QA PB [0-9a-f]{6}|MP Default [0-9a-f]{8}|LA [0-9a-f]{8}|NonDefault [0-9a-f]{8}|Builder [0-9]{6})$') and (e.notes is null or e.notes not like '%TEST%')"))).scalar())
asyncio.run(main())
