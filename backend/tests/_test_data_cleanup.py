"""Keeps automated-test price books out of the working database.

Only names matching the exact test naming + ID patterns are ever touched.
"""
import json
from pathlib import Path
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
    if "DATABASE_URL" not in os.environ:  # standalone helper scripts
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
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


# ---------------- business records created during a test session ----------------
# Tracked by id: anything in these tables that did not exist when the session started was created by the run.
TRACKED = ("properties", "customers", "leads", "inspections", "measurement_sets", "estimates", "quotes",
           "jobs", "invoices", "purchase_orders", "materials", "suppliers", "visits",
           "territories", "canvass_sections", "import_jobs", "assemblies", "inventory_locations")


async def _business_ids():
    eng, maker = _session()
    async with maker() as s:
        out = {t: set((await s.execute(text(f"select id::text from {t}"))).scalars().all()) for t in TRACKED}
    await eng.dispose()
    return out


def business_snapshot():
    return asyncio.run(_business_ids())


async def _purge_business(start: dict) -> dict:
    """Delete the records a run created. Stock movements are only removed together with a material the run itself
    created; a job/PO whose movements touched pre-existing stock is kept so real on-hand and receiving history stay intact."""
    eng, maker = _session()
    out = {}
    async with maker() as s:
        async def q(sql, **kw):
            return set((await s.execute(text(sql), kw)).scalars().all())

        async def run(key, sql, ids):
            n = (await s.execute(text(sql), {"ids": list(ids)})).rowcount if ids else 0
            if n:
                out[key] = out.get(key, 0) + n

        new = {}
        for t in TRACKED:
            new[t] = list((await q(f"select id::text from {t}")) - start.get(t, set()))
        NJ, NP, NM = new["jobs"], new["purchase_orders"], new["materials"]

        async def held_materials(cands):
            """Run-created materials still referenced by rows that are staying."""
            if not cands:
                return set()
            h = set()
            h |= await q("select material_id::text from po_line_items where material_id::text = any(:m) and po_id::text <> all(:p)", m=cands, p=del_pos or ["-"])
            h |= await q("select material_id::text from job_materials where material_id::text = any(:m) and job_id::text <> all(:j)", m=cands, j=del_jobs or ["-"])
            for t in ("assembly_items", "abc_catalog_items", "price_book_entries"):
                h |= await q(f"select material_id::text from {t} where material_id::text = any(:m)", m=cands)
            h |= await q("select material_id::text from estimate_line_items where material_id::text = any(:m) and estimate_id::text <> all(:e)", m=cands, e=new["estimates"] or ["-"])
            h |= await q("select material_id::text from quote_line_items where material_id::text = any(:m) and quote_id::text <> all(:x)", m=cands, x=new["quotes"] or ["-"])
            return h

        del_jobs, del_pos = NJ, NP  # optimistic first pass for the material check
        test_mats = set(NM) - await held_materials(NM)
        tm = list(test_mats) or ["-"]
        # a job/PO is removable only if every stock movement it caused is on a run-created material
        keep_jobs = await q("select distinct job_id::text from inventory_txns where job_id::text = any(:j) and material_id::text <> all(:m)", j=NJ or ["-"], m=tm)
        keep_pos = await q("select distinct po_id::text from inventory_txns where po_id::text = any(:p) and material_id::text <> all(:m)", p=NP or ["-"], m=tm)
        del_jobs = [j for j in NJ if j not in keep_jobs]
        del_pos = [p for p in NP if p not in keep_pos]

        await run("abc_order_submissions", "delete from abc_order_submissions where purchase_order_id::text = any(:ids)", del_pos)
        await run("po_status_history", "delete from po_status_history where purchase_order_id::text = any(:ids)", del_pos)
        await run("inventory_txns", "delete from inventory_txns where po_id::text = any(:ids)", del_pos)
        await run("po_line_items", "delete from po_line_items where po_id::text = any(:ids)", del_pos)
        await run("purchase_orders", "delete from purchase_orders where id::text = any(:ids)", del_pos)
        await run("po_unlinked", "update purchase_orders set job_id = null where job_id::text = any(:ids)", del_jobs)
        await run("inventory_txns", "delete from inventory_txns where job_id::text = any(:ids)", del_jobs)

        await run("invoices", "delete from invoices where id::text = any(:ids)", new["invoices"])
        await s.execute(text("update invoices set job_id = null where job_id::text = any(:ids)"), {"ids": del_jobs or ["-"]})
        await run("photos", "delete from photos where record_type = 'job' and record_id::text = any(:ids)", del_jobs)
        await run("jobs", "delete from jobs where id::text = any(:ids)", del_jobs)

        kj = list(keep_jobs) or ["-"]
        quotes = [x for x in new["quotes"] if x not in await q("select quote_id::text from jobs where id::text = any(:k) and quote_id is not null", k=kj)]
        await run("quote_line_items", "delete from quote_line_items where quote_id::text = any(:ids)", quotes)
        await run("quote_packages", "delete from quote_packages where quote_id::text = any(:ids)", quotes)
        await run("quotes", "delete from quotes where id::text = any(:ids)", quotes)

        held_est = await q("select estimate_id::text from quotes where estimate_id is not null")
        estimates = [e for e in new["estimates"] if e not in held_est]
        await run("estimates", "delete from estimates where id::text = any(:ids)", estimates)

        held_ms = await q("select distinct r.set_id::text from measurement_revisions r join estimate_takeoffs t on t.measurement_revision_id = r.id")
        msets = [m for m in new["measurement_sets"] if m not in held_ms]
        await run("relay_outbox_events", "delete from relay_outbox_events where measurement_set_id::text = any(:ids)", msets)
        await run("measurement_sets", "delete from measurement_sets where id::text = any(:ids)", msets)
        await run("inspections", "delete from inspections where id::text = any(:ids) and id not in (select inspection_id from estimates where inspection_id is not null)", new["inspections"])

        held_leads = await q("select lead_id::text from quotes where lead_id is not null") | await q("select lead_id::text from estimates where lead_id is not null")
        leads = [x for x in new["leads"] if x not in held_leads]
        await run("relay_outbox_events", "delete from relay_outbox_events where lead_id::text = any(:ids)", leads)
        await run("leads", "delete from leads where id::text = any(:ids)", leads)

        held_c = set()
        for t in ("jobs", "invoices", "quotes", "estimates", "leads", "inspections"):
            held_c |= await q(f"select customer_id::text from {t} where customer_id is not null")
        await run("customers", "delete from customers where id::text = any(:ids)", [c for c in new["customers"] if c not in held_c])

        held_p = set()
        for t in ("jobs", "invoices", "quotes", "estimates", "leads", "inspections", "measurement_sets", "customer_properties"):
            held_p |= await q(f"select property_id::text from {t} where property_id is not null")
        held_v = await q("select source_visit_id::text from leads where source_visit_id is not null")
        await run("visits", "delete from visits where id::text = any(:ids)", [v for v in new["visits"] if v not in held_v])
        props = [x for x in new["properties"] if x not in held_p]
        await run("visits", "delete from visits where property_id::text = any(:ids)", props)
        await run("property_contacts", "delete from property_contacts where property_id::text = any(:ids)", props)
        await run("properties", "delete from properties where id::text = any(:ids)", props)

        held_a = set()
        for t in ("job_materials", "price_book_entries", "estimate_line_items", "takeoff_rules"):
            held_a |= await q(f"select assembly_id::text from {t} where assembly_id is not null")
        await run("assemblies", "delete from assemblies where id::text = any(:ids)", [x for x in new["assemblies"] if x not in held_a])

        mats = list(test_mats - await held_materials(list(test_mats)))  # re-check against what is staying
        await run("supplier_price_history", "delete from supplier_price_history where material_id::text = any(:ids)", mats)
        await run("supplier_materials", "delete from supplier_materials where material_id::text = any(:ids)", mats)
        await run("materials", "delete from materials where id::text = any(:ids)", mats)  # its own txns/balances cascade

        await run("canvass_sections", "delete from canvass_sections where id::text = any(:ids)", new["canvass_sections"])
        await run("import_jobs", "delete from import_jobs where id::text = any(:ids)", new["import_jobs"])
        held_t = await q("select territory_id::text from properties where territory_id is not null") | \
            await q("select territory_id::text from canvass_sections") | await q("select territory_id::text from import_jobs where territory_id is not null")
        await run("territories", "delete from territories where id::text = any(:ids)", [x for x in new["territories"] if x not in held_t])
        held_l = await q("select source_location_id::text from inventory_txns where source_location_id is not null") | \
            await q("select destination_location_id::text from inventory_txns where destination_location_id is not null") | \
            await q("select location_id::text from inventory_balances where quantity_on_hand <> 0")
        await run("inventory_locations", "delete from inventory_locations where id::text = any(:ids)", [x for x in new["inventory_locations"] if x not in held_l])

        held_s = (await q("select supplier_id::text from purchase_orders where supplier_id is not null")
                  | await q("select supplier_id::text from supplier_materials where supplier_id is not null")
                  | await q("select supplier_id::text from price_book_entries where supplier_id is not null")
                  | await q("select cost_source_supplier_id::text from estimate_line_items where cost_source_supplier_id is not null"))
        sups = [x for x in new["suppliers"] if x not in held_s]
        await run("supplier_price_history", "delete from supplier_price_history where supplier_id::text = any(:ids)", sups)
        await run("suppliers", "delete from suppliers where id::text = any(:ids)", sups)
        if keep_jobs or keep_pos:
            out["kept_jobs_with_real_stock_movements"] = len(keep_jobs)
            out["kept_pos_with_real_receiving"] = len(keep_pos)
        await s.commit()
    await eng.dispose()
    return out


def purge_business(start: dict) -> dict:
    return asyncio.run(_purge_business(start))


# ---------------- company default price book (shared singleton) ----------------
async def _default_pb():
    eng, maker = _session()
    async with maker() as s:
        v = (await s.execute(text("select id::text from price_books where is_default"))).scalars().first()
    await eng.dispose()
    return v


async def _set_default_pb(pb_id):
    eng, maker = _session()
    async with maker() as s:
        if (await s.execute(text("select 1 from price_books where id::text = :i"), {"i": pb_id})).first():
            await s.execute(text("update price_books set is_default = (id::text = :i)"), {"i": pb_id})
            await s.commit()
    await eng.dispose()


def default_price_book():
    return asyncio.run(_default_pb())


def restore_default_price_book(pb_id):
    if pb_id:
        asyncio.run(_set_default_pb(pb_id))


# ---------------- manual / one-off helper sessions (outside pytest) ----------------
# One-off setup scripts and testing-agent probes create data for UI checks, so it cannot vanish when the
# script exits. They call manual_begin() (records a snapshot once); after the manual/UI testing, run
#   python tests/_test_data_cleanup.py end
# to remove everything created since the snapshot (same rules as the pytest session cleanup).
MANUAL_SNAPSHOT = Path("/app/memory/.manual_test_snapshot.json")


def manual_begin() -> None:
    if MANUAL_SNAPSHOT.exists():
        return
    biz = {t: sorted(v) for t, v in business_snapshot().items()}
    MANUAL_SNAPSHOT.write_text(json.dumps({"business": biz, "users": sorted(user_snapshot())}))
    print(f"[manual test data] snapshot recorded -> run `python tests/_test_data_cleanup.py end` when finished")


def manual_end() -> dict:
    if not MANUAL_SNAPSHOT.exists():
        return {}
    snap = json.loads(MANUAL_SNAPSHOT.read_text())
    out = purge_business({t: set(v) for t, v in snap["business"].items()})
    out["users"] = purge_users(only_new_since=set(snap["users"]))
    MANUAL_SNAPSHOT.unlink()
    return out


if __name__ == "__main__":
    import sys as _sys
    cmd = _sys.argv[1] if len(_sys.argv) > 1 else "status"
    if cmd == "begin":
        manual_begin()
    elif cmd == "end":
        print(manual_end() or "no manual snapshot open")
    else:
        print("manual snapshot open" if MANUAL_SNAPSHOT.exists() else "no manual snapshot open")
