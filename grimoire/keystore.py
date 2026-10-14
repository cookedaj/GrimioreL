"""A minimal Secret Service client (org.freedesktop.secrets: KWallet on Plasma, GNOME Keyring elsewhere) for the
one secret Grimoire keeps: the GitHub sign-in token.

Why not python3-keyring: it isn't installed here (and pip isn't an option). Why not QtDBus: PySide6 can't marshal
the a{ss} attribute maps and (oayays) secret structs this API needs (it aborts the process). dbus-python
(python3-dbus) can, ships with Kubuntu and SystemL's alerts already use it.

Each call opens its own private bus connection and a "plain" session (the secret crosses the local session bus
unencrypted, like most clients do; it never touches a file). A locked collection is unlocked through the keyring's
own prompt; without a main loop to wait for the prompt's signal, the Locked property is polled instead.
Secret values never appear in exceptions or return values other than load().
"""
import time

LABEL = "Grimoire GitHub sign-in"
ATTRS = {"application": "grimoire", "service": "github"}
BUS_NAME, ROOT = "org.freedesktop.secrets", "/org/freedesktop/secrets"
SVC, COLL, ITEM, PROMPT = (f"org.freedesktop.Secret.{n}" for n in ("Service", "Collection", "Item", "Prompt"))
PROMPT_WAIT = 120                     # seconds to wait for the user to answer the keyring's unlock prompt


class KeyringError(RuntimeError):
    """Why the keyring couldn't be used, worded for the UI."""


class _Session:
    def __init__(self):
        try:
            import dbus
        except ImportError:
            raise KeyringError("Saving the sign-in needs python3-dbus (sudo apt install python3-dbus).") from None
        self.dbus = dbus
        try:
            self.bus = dbus.SessionBus(private=True)
            self.svc = dbus.Interface(self.bus.get_object(BUS_NAME, ROOT), SVC)
            _, self.path = self.svc.OpenSession("plain", dbus.String("", variant_level=1))
        except dbus.DBusException as e:
            raise KeyringError(f"No system keyring is available ({e.get_dbus_name()}).") from None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        try:
            self.dbus.Interface(self.bus.get_object(BUS_NAME, self.path), "org.freedesktop.Secret.Session").Close()
        except Exception:
            pass
        self.bus.close()

    def obj(self, path, iface):
        return self.dbus.Interface(self.bus.get_object(BUS_NAME, path), iface)

    def prop(self, path, iface, name):
        return self.obj(path, "org.freedesktop.DBus.Properties").Get(iface, name)

    def prompt(self, path, done) -> bool:
        """Show the keyring's prompt at path and wait until done() (polled), up to PROMPT_WAIT seconds."""
        if path == "/":
            return True
        self.obj(path, PROMPT).Prompt("")
        end = time.monotonic() + PROMPT_WAIT
        while time.monotonic() < end:
            if done():
                return True
            time.sleep(0.4)
        try:
            self.obj(path, PROMPT).Dismiss()
        except Exception:
            pass
        return False

    def unlock(self, paths: list):
        if not paths:
            return
        unlocked, prompt = self.svc.Unlock(self.dbus.Array(paths, signature="o"))
        if len(unlocked) == len(paths):
            return
        def locked(p):                 # .../collection/<name> is a collection, one level deeper an item
            return bool(self.prop(p, COLL if p.count("/") <= 5 else ITEM, "Locked"))
        if not self.prompt(prompt, lambda: not any(locked(p) for p in paths)):
            raise KeyringError("The keyring stayed locked, so the sign-in wasn't saved or read.")

    def default_collection(self) -> str:
        path = str(self.svc.ReadAlias("default"))
        if path == "/":
            raise KeyringError("The system keyring has no default wallet yet; open KWallet Manager to create one.")
        return path

    def search(self, attrs) -> list:
        unlocked, locked = self.svc.SearchItems(self.dbus.Dictionary(attrs, signature="ss"))
        return [str(p) for p in unlocked], [str(p) for p in locked]


def _guard(fn):
    """D-Bus errors become KeyringError with the error's name only (never its arguments)."""
    def run(*a, **kw):
        try:
            import dbus
        except ImportError:
            raise KeyringError("Saving the sign-in needs python3-dbus (sudo apt install python3-dbus).") from None
        try:
            return fn(*a, **kw)
        except dbus.DBusException as e:
            raise KeyringError(f"The keyring refused ({e.get_dbus_name() or 'unknown error'}).") from None
    return run


@_guard
def store(secret: str, attrs: dict = ATTRS, label: str = LABEL):
    """Save (or replace) the secret with these attributes in the default collection."""
    with _Session() as s:
        dbus = s.dbus
        coll = s.default_collection()
        if bool(s.prop(coll, COLL, "Locked")):
            s.unlock([coll])
        props = {f"{ITEM}.Label": dbus.String(label, variant_level=1),
                 f"{ITEM}.Attributes": dbus.Dictionary(attrs, signature="ss", variant_level=1)}
        value = dbus.Struct((dbus.ObjectPath(s.path), dbus.ByteArray(b""), dbus.ByteArray(secret.encode()),
                             dbus.String("text/plain")), signature="oayays")
        item, prompt = s.obj(coll, COLL).CreateItem(dbus.Dictionary(props, signature="sv"), value, True)
        if str(item) == "/" and not s.prompt(prompt, lambda: bool(s.search(attrs)[0])):
            raise KeyringError("The keyring didn't save the sign-in (the prompt was dismissed).")


@_guard
def load(attrs: dict = ATTRS) -> str | None:
    with _Session() as s:
        unlocked, locked = s.search(attrs)
        if not unlocked and locked:
            s.unlock(locked[:1])
            unlocked = locked[:1]
        if not unlocked:
            return None
        _, _, value, _ = s.obj(unlocked[0], ITEM).GetSecret(s.dbus.ObjectPath(s.path))
        return bytes(value).decode()


@_guard
def delete(attrs: dict = ATTRS) -> int:
    """Remove every item with these attributes; returns how many."""
    n = 0
    with _Session() as s:
        unlocked, locked = s.search(attrs)
        for path in unlocked + locked:
            prompt = s.obj(path, ITEM).Delete()
            if s.prompt(prompt, lambda p=path: p not in sum(s.search(attrs), [])):
                n += 1
    return n


@_guard
def available() -> bool:
    try:
        with _Session():
            return True
    except KeyringError:
        return False
