import base64
import hashlib
import importlib

from cryptography.fernet import Fernet


def test_ticket_secret_accepts_high_entropy_shared_secret(monkeypatch):
    """A production shared secret must never crash ticket minting just because it is not pre-encoded as Fernet."""
    monkeypatch.setenv("RELAY_TICKET_SECRET", "roofspan-production-shared-secret-0123456789abcdef")

    import relay.config as config
    import relay.tickets as tickets

    importlib.reload(config)
    importlib.reload(tickets)

    ticket, ttl = tickets.mint_ticket("installation-1", "device-1", "token-1")
    assert ttl > 0
    claims = tickets.read_ticket(ticket)
    assert claims["iid"] == "installation-1"
    assert claims["did"] == "device-1"


def test_valid_fernet_secret_remains_backward_compatible(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("RELAY_TICKET_SECRET", key)

    import relay.config as config
    import relay.tickets as tickets

    importlib.reload(config)
    importlib.reload(tickets)

    assert tickets._ticket_key() == key.encode()
