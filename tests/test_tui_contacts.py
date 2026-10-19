"""The address book (c) and writing a private post to a contact by name (UN-RFC 0028)."""

from unseenet.client.session import Session
from unseenet.client.tui import ContactsDialog, UnseenetApp
from unseenet.core import crypto
from unseenet.core.vault import Vault

from tuihelp import app_ready, stack, wait_for

KDF = {"ops": 1, "mem": 8192 * 1024}


async def test_contacts_and_recipient_by_name(tmp_path, monkeypatch):
    s = Session(Vault.open(tmp_path / "me.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("me", "Me")
    s.add_node("127.0.0.1:1")      # without a node the first-run setup dialog opens on top
    sonia, mikkel, mia = (crypto.Identity.generate().key_text for _ in range(3))
    s.add_contact(sonia, "Sonia"); s.add_contact(mikkel, "Mikkel"); s.add_contact(mia, "Mia")
    s.save()
    monkeypatch.setenv("UNSEENET_PASSPHRASE", "pw")
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    app = UnseenetApp(tmp_path / "me.vault")
    async with app.run_test(size=(120, 36)) as pilot:
        assert await app_ready(pilot, app), stack(app)
        assert app._recipient("sonia") == sonia                 # a name, any case
        assert app._recipient("Mik") == mikkel                  # the start of one
        assert app._recipient("Mi") is None                     # Mikkel and Mia: say which
        assert app._recipient("nobody") is None
        assert app._recipient(mia) == mia                       # a key still works
        app.action_contacts()
        assert await wait_for(pilot, lambda: isinstance(app.screen, ContactsDialog)), stack(app)
        await pilot.press("escape")
        await pilot.press("q")
