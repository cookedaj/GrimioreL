"""xdg-desktop-portal calls: Screenshot (the fallback when Spectacle is missing) and ScreenCast (what the recorder
records). Each portal call returns a Request whose Response signal carries the answer, so these helpers wait for it
on a private GLib loop and read synchronously."""
import secrets
import shutil
from pathlib import Path
from urllib.parse import unquote, urlparse

BUS = "org.freedesktop.portal.Desktop"
PATH = "/org/freedesktop/portal/desktop"
SCREENCAST = "org.freedesktop.portal.ScreenCast"
MONITOR, WINDOW = 1, 2                 # ScreenCast source types
HIDDEN, EMBEDDED = 1, 2                # cursor modes

_bus = None


class PortalError(RuntimeError):
    pass


def bus():
    global _bus
    if _bus is None:
        import dbus
        from dbus.mainloop.glib import DBusGMainLoop
        DBusGMainLoop(set_as_default=True)            # signals are delivered through GLib's loop
        _bus = dbus.SessionBus()
    return _bus


def _token() -> str:
    return "grimoire_" + secrets.token_hex(6)


def request(iface: str, method: str, *args, options: dict | None = None, timeout=300) -> dict:
    """Call a portal method and wait for its Response; raises PortalError when cancelled or failed."""
    import dbus
    from gi.repository import GLib
    b = bus()
    token = _token()
    handle = f"{PATH}/request/{b.get_unique_name()[1:].replace('.', '_')}/{token}"
    answer: dict = {}
    loop = GLib.MainLoop()

    def got(code, results):
        answer.update(code=int(code), results=results)
        loop.quit()

    match = b.add_signal_receiver(got, "Response", "org.freedesktop.portal.Request", BUS, handle)
    try:
        opts = dbus.Dictionary(dict(options or {}, handle_token=token), signature="sv")
        getattr(b.get_object(BUS, PATH), method)(*args, opts, dbus_interface=iface)
        GLib.timeout_add_seconds(timeout, loop.quit)
        loop.run()
    except dbus.DBusException as e:
        raise PortalError(e.get_dbus_message() or str(e))
    finally:
        match.remove()
    if "code" not in answer:
        raise PortalError("the portal didn't answer")
    if answer["code"] == 1:
        raise PortalError("cancelled")
    if answer["code"]:
        raise PortalError("the portal refused")
    return answer["results"]


def screenshot(out: Path):
    """Whole desktop, no dialog; the portal writes a file somewhere, we copy it to out."""
    res = request("org.freedesktop.portal.Screenshot", "Screenshot", "", options={"interactive": False})
    src = Path(unquote(urlparse(str(res.get("uri", ""))).path))
    if not src.is_file():
        raise PortalError("the portal returned no image")
    shutil.copyfile(src, out)


def screencast(restore_token="", pointer=True, types=MONITOR | WINDOW):
    """Ask for one screen or window to record. Returns (session path, pipewire fd, node id, (w, h) or None, new
    restore token). With a restore token KDE reuses the last choice without asking."""
    import dbus
    b = bus()
    sess = request(SCREENCAST, "CreateSession", options={"session_handle_token": _token()})["session_handle"]
    opts = {"types": dbus.UInt32(types), "multiple": False, "persist_mode": dbus.UInt32(2),
            "cursor_mode": dbus.UInt32(EMBEDDED if pointer else HIDDEN)}
    if restore_token:
        opts["restore_token"] = restore_token
    request(SCREENCAST, "SelectSources", dbus.ObjectPath(sess), options=opts)
    res = request(SCREENCAST, "Start", dbus.ObjectPath(sess), "")
    streams = res.get("streams") or []
    if not streams:
        raise PortalError("nothing was picked to record")
    node, props = streams[0]
    size = tuple(int(x) for x in props["size"]) if "size" in props else None
    fd = b.get_object(BUS, PATH).OpenPipeWireRemote(dbus.ObjectPath(sess), dbus.Dictionary({}, signature="sv"),
                                                     dbus_interface=SCREENCAST)
    return str(sess), fd.take(), int(node), size, str(res.get("restore_token", ""))


def close(session: str):
    try:
        bus().get_object(BUS, session).Close(dbus_interface="org.freedesktop.portal.Session")
    except Exception:
        pass                                          # already closed (the user stopped sharing)


def on_closed(session: str, callback):
    """Run callback when the user ends the screencast from KDE's tray indicator."""
    bus().add_signal_receiver(lambda *_: callback(), "Closed", "org.freedesktop.portal.Session", BUS, session)
