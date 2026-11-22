"""Keeps automated-test price books out of the working database.

Only names matching the exact test naming + ID patterns are ever touched.
"""
import asyncio
import re

from sqlalchemy import text

TEST_PRICE_BOOK_RE = r"^(QA PB [0-9a-f]{6}|MP Default [0-9a-f]{8}|LA [0-9a-f]{8}|NonDefault [0-9a-f]{8}|Builder [0-9]{6})$"
_RX = re.compile(TEST_PRICE_BOOK_RE)


def is_test_price_book(name: str) -> bool:
    return bool(_RX.match(name or ""))


def _session():
    # Fresh engine per call: each asyncio.run() gets its own loop, so never reuse a pooled engine across loops.
    import os
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from sqlalchemy.pool import NullPool
    eng = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    return eng, async_sessionmaker(eng, expire_on_commit=False, class_=AsyncSession)


async def _snapshot():
    eng, maker = _session()
    async with maker() as s:
        ids = set((await s.execute(text("select id::text from price_books"))).scalars().all())
        default = (await s.execute(text("select id::text from price_books where is_default"))).scalars().first()
    await eng.dispose()
    return ids, default


async def _purge(only_new_since: set | None, restore_default: str | None) -> int:
    eng, maker = _session()
    async with maker() as s:
        rows = (await s.execute(text("select id::text, name from price_books where name ~ :rx"), {"rx": TEST_PRICE_BOOK_RE})).all()
        ids = [i for i, n in rows if is_test_price_book(n) and (only_new_since is None or i not in only_new_since)]
        if ids:
            await s.execute(text("update estimate_line_items set applied_price_book_id = null where applied_price_book_id::text = any(:ids)"), {"ids": ids})
            await s.execute(text("delete from price_book_entries where price_book_id::text = any(:ids)"), {"ids": ids})
            await s.execute(text("delete from price_books where id::text = any(:ids)"), {"ids": ids})  # estimates.price_book_id FK is ON DELETE SET NULL
        if restore_default:
            still = (await s.execute(text("select 1 from price_books where id::text = :i"), {"i": restore_default})).scalar()
            if still:
                await s.execute(text("update price_books set is_default = (id::text = :i)"), {"i": restore_default})
        await s.commit()
    await eng.dispose()
    return len(ids)


def snapshot():
    return asyncio.run(_snapshot())


def purge(only_new_since=None, restore_default=None) -> int:
    return asyncio.run(_purge(only_new_since, restore_default))


# ---------------- automated-test users ----------------
# Strict: known test prefixes + a random hex/number suffix at the test-only domains.
TEST_USER_RE = (
    r"^(qa_sales|test_sales|assign_sales|test_sales_p[0-9]+|seat[0-9]*|sales[0-9]+|cvrep[0-9]*|cvown|test_p[0-9]+_disable|"
    r"lic_sales|inactive|deactivate_test|test_admin|test_dup|test_reset|mrepA|mrepB|test_office|mown|audit_test|test_promo|"
    r"salesmp|mapown|maprep|mapzero|sales_e[0-9]+e|mapother|arearep|areaoth|areaown|mo|repA|repB|repC|sales_qa|sales_t[0-9]+|"
    r"test_office_crews|uirep|[a-z]+_test|test_[a-z0-9_]+)_?[0-9a-f]{3,}@(example\.com|t\.io)$"
)
KEEP_USERS = ("sales_bk@example.com", "sales1_38f545f9@example.com", "sales2_7ad4f5cd@example.com")
_URX = re.compile(TEST_USER_RE, re.I)


def is_test_user(email: str) -> bool:
    e = (email or "").lower()
    return e not in KEEP_USERS and bool(_URX.match(e))


async def _user_ids():
    eng, maker = _session()
    async with maker() as s:
        ids = set((await s.execute(text("select id::text from users"))).scalars().all())
    await eng.dispose()
    return ids


async def _purge_users(only_new_since: set | None) -> int:
    eng, maker = _session()
    async with maker() as s:
        rows = (await s.execute(text("select id::text, email from users where role <> 'owner' or email like '%@t.io' or email like '%@example.com'"))).all()
        ids = [i for i, e in rows if is_test_user(e) and (only_new_since is None or i not in only_new_since)]
        if ids:
            # jobs/leads/canvass_sections.assigned_user_id are ON DELETE SET NULL; audit_logs keep user_email history
            await s.execute(text("delete from refresh_tokens where user_id::text = any(:ids)"), {"ids": ids})
            await s.execute(text("update visits set user_id = null where user_id::text = any(:ids)"), {"ids": ids})
            await s.execute(text("delete from users where id::text = any(:ids)"), {"ids": ids})
        await s.commit()
    await eng.dispose()
    return len(ids)


def user_snapshot():
    return asyncio.run(_user_ids())


def purge_users(only_new_since=None) -> int:
    return asyncio.run(_purge_users(only_new_since))
