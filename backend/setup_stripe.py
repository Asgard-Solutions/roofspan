"""Idempotent Stripe catalog setup for RoofSpan.

Creates ONE commercial product — "RoofSpan Seat" — with a single recurring monthly per-unit price
($49.00/seat/month). Seat count is the Stripe subscription item QUANTITY (min 5, max 50). There are
NO +1/+5/+10 bundle products — those are UI actions that change the same subscription item quantity.

Run:  cd /app/backend && python setup_stripe.py
Safe to re-run: dedupes the product by metadata.emergent_product_id and the price by lookup_key.
"""
import os

import stripe
from dotenv import load_dotenv

load_dotenv()

stripe.api_key = os.environ["STRIPE_SECRET_KEY"]

SEAT_LOOKUP_KEY = os.environ.get("STRIPE_SEAT_LOOKUP_KEY", "roofspan_seat_monthly")
SEAT_AMOUNT_CENTS = 4900          # $49.00 per seat / month
SEAT_TAX_CODE = "txcd_10103001"   # Software as a service (SaaS)

CATALOG = {
    "emergent_product_id": "roofspan_seat",
    "name": "RoofSpan Seat",
    "description": "RoofSpan licensed user seat — $49/seat/month. Quantity = licensed seats (min 5, max 50).",
    "tax_code": SEAT_TAX_CODE,
    "price": {"lookup_key": SEAT_LOOKUP_KEY, "amount": SEAT_AMOUNT_CENTS, "currency": "usd", "interval": "month"},
}


def get_or_create_product(entry):
    for p in stripe.Product.list(active=True, limit=100).auto_paging_iter():
        if p.to_dict().get("metadata", {}).get("emergent_product_id") == entry["emergent_product_id"]:
            return p
    return stripe.Product.create(
        name=entry["name"], description=entry["description"], tax_code=entry.get("tax_code"),
        metadata={"managed_by": "emergent", "emergent_product_id": entry["emergent_product_id"]},
    )


def ensure_price(product, price):
    existing = stripe.Price.list(lookup_keys=[price["lookup_key"]], active=True, limit=1).data
    if existing and (existing[0].unit_amount != price["amount"] or existing[0].currency != price["currency"]):
        stripe.Price.modify(existing[0].id, active=False)
        existing = []
    if existing:
        return existing[0]
    return stripe.Price.create(
        product=product.id, unit_amount=price["amount"], currency=price["currency"],
        lookup_key=price["lookup_key"], transfer_lookup_key=True,
        recurring={"interval": price["interval"], "usage_type": "licensed"},
    )


def main():
    product = get_or_create_product(CATALOG)
    price = ensure_price(product, CATALOG["price"])
    print("Product:", product.id, "-", product.name)
    print("Price:  ", price.id, "lookup_key=", price.lookup_key, "amount=", price.unit_amount, price.currency,
          "interval=", price.recurring["interval"])
    print("Account:", stripe.Account.retrieve().id, "country=", stripe.Account.retrieve().country)


if __name__ == "__main__":
    main()
