"""Screen recording, run as its own small process so recording survives closing the window and a hotkey can stop it.

Backend: the xdg-desktop-portal ScreenCast (KDE asks once which screen or window; "allow restoring" makes later
recordings start straight away) feeding PipeWire into GStreamer through python3-gi. GStreamer converts the frames
to a steady 30 fps and pipes them (y4m) to ffmpeg, which encodes H.264 on the NVIDIA card (h264_nvenc), else with
libx264, into an .mp4 that plays everywhere. Without ffmpeg, GStreamer alone writes VP8 .webm. Spectacle's own
recorder is the last resort: it records fine but only stops from its tray icon and saves to its own folder.

    python3 -m grimoire.spells.shotl.record toggle|start|stop|status [--sound] [--pointer] [--pick]
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from grimoire.spells.shotl import shots

STATE = shots.TEMP / "recording.json"        # {"pid", "path", "started"} while the recorder runs
LOG = shots.TEMP / "record.log"
FPS = 30
_cache: dict = {}


# ---------------------------------------------------------------- what this PC can do (no Qt, cheap after once)
def _gst_ok() -> bool:
    if "gst" not in _cache:
        try:
            import dbus  # noqa: F401
            import gi
            gi.require_version("Gst", "1.0")
            from gi.repository import Gst
            Gst.init(None)
            _cache["gst"] = all(Gst.ElementFactory.find(e) for e in
                                ("pipewiresrc", "videoconvert", "videoscale", "videorate"))
        except (ImportError, ValueError):
            _cache["gst"] = False
    return _cache["gst"]


def backend() -> str:
    """'portal' (ours), 'spectacle' (its own UI), or '' when nothing can record."""
    if _gst_ok():
        return "portal"
    return "spectacle" if shutil.which("spectacle") else ""


def encoder() -> str:
    """'nvenc', 'x264' or 'vp8'. NVENC is probed with one tiny frame: the driver may be missing or busy."""
    if "enc" not in _cache:
        enc = "vp8"
        if shutil.which("ffmpeg"):
            try:
                probe = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                                        "color=s=256x256:d=0.1", "-frames:v", "1", "-c:v", "h264_nvenc", "-f", "null",
                                        "-"], capture_output=True, timeout=15)
                encs = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True,
                                      timeout=15).stdout
                enc = "nvenc" if probe.returncode == 0 else "x264" if " libx264 " in encs else "vp8"
            except (OSError, subprocess.TimeoutExpired):
                pass
        _cache["enc"] = enc
    return _cache["enc"]


def describe() -> str:
    """One line for the page: how recordings are made here."""
    how = backend()
    if how == "portal":
        return {"nvenc": "MP4, H.264 on the graphics card", "x264": "MP4, H.264 on the CPU",
                "vp8": "WebM, VP8 (install ffmpeg for MP4)"}[encoder()]
    if how == "spectacle":
        return "with Spectacle (install python3-gi and gstreamer1.0-pipewire for ShotL's own recorder)"
    return "unavailable: install gstreamer1.0-pipewire and python3-gi, or Spectacle"


# ---------------------------------------------------------------- control (used by the page and the CLI)
def state() -> dict | None:
    """The running recording, or None. A state file left by a crashed recorder doesn't count."""
    try:
        st = json.loads(STATE.read_text())
        cmd = Path(f"/proc/{int(st['pid'])}/cmdline").read_bytes()
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return st if b"grimoire.spells.shotl.record" in cmd else None


def start(sound=False, pointer=True, pick=False) -> str:
    """Launch the recorder in the background. Returns '' or a message for the user."""
    if state():
        return "Already recording"
    how = backend()
    if how == "spectacle":
        subprocess.Popen(["spectacle", "--record", "screen"], start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "Recording with Spectacle: stop it from its icon in the system tray"
    if not how:
        return "Recording isn't available: " + describe().split(": ", 1)[-1]
    root = Path(__file__).resolve().parents[3]
    env = dict(os.environ, PYTHONPATH=str(root) + (":" + os.environ["PYTHONPATH"] if "PYTHONPATH" in os.environ else ""))
    args = [sys.executable, "-m", "grimoire.spells.shotl.record", "run"] + ["--sound"] * sound \
        + ["--pointer"] * pointer + ["--pick"] * pick
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as log:
        subprocess.Popen(args, env=env, cwd=root, start_new_session=True, stdin=subprocess.DEVNULL, stdout=log,
                         stderr=log)
    return ""


def stop() -> bool:
    st = state()
    if st:
        os.kill(int(st["pid"]), signal.SIGINT)
    return bool(st)


# ---------------------------------------------------------------- the recorder process
def _notify(title: str, body: str):
    try:
        import dbus
        from grimoire.spells.shotl.portal import bus
        n = bus().get_object("org.freedesktop.Notifications", "/org/freedesktop/Notifications")
        n.Notify("ShotL", dbus.UInt32(0), "grimoire-shotl", title, body, dbus.Array([], signature="s"),
                 {"desktop-entry": "grimoire-shotl"}, -1, dbus_interface="org.freedesktop.Notifications", timeout=5)
    except Exception as e:
        print(f"notify failed: {e}", flush=True)


def _monitor_source() -> str:
    """What's playing: the default output's monitor."""
    try:
        sink = subprocess.run(["pactl", "get-default-sink"], capture_output=True, text=True, timeout=5).stdout.strip()
        return f"{sink}.monitor" if sink else "default"
    except (OSError, subprocess.TimeoutExpired):
        return "default"


def pipeline(src: str, out: Path, enc: str, size, sound: bool, fd_out: int | None) -> tuple[str, list | None]:
    """(GStreamer pipeline, ffmpeg command or None). src is the pipewiresrc (or a test source) element text."""
    caps = f"video/x-raw,format=I420,framerate={FPS}/1"
    if size:
        w, h = (max(2, v - v % 2) for v in size)          # 4:2:0 needs even sizes
        caps += f",width={w},height={h},pixel-aspect-ratio=1/1"
    video = f"{src} ! videoconvert ! videoscale add-borders=true ! videorate ! {caps}"
    if enc == "vp8":
        desc = (f"{video} ! queue ! vp8enc deadline=1 cpu-used=8 threads={os.cpu_count() or 4} "
                f"target-bitrate=12000000 keyframe-max-dist=120 ! queue ! webmmux name=mux ! "
                f"filesink location=\"{out}\"")
        if sound:
            desc += f" pulsesrc device=\"{_monitor_source()}\" ! queue ! audioconvert ! audioresample ! opusenc ! queue ! mux."
        return desc, None
    desc = f"{video} ! queue max-size-buffers=8 ! y4menc ! fdsink fd={fd_out} sync=false"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-thread_queue_size", "64",
           "-f", "yuv4mpegpipe", "-i", "pipe:0"]
    if sound:
        cmd += ["-thread_queue_size", "1024", "-f", "pulse", "-i", _monitor_source()]
    cmd += (["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "23", "-b:v", "0"] if enc == "nvenc"
            else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"])
    cmd += ["-pix_fmt", "yuv420p"] + (["-c:a", "aac", "-b:a", "160k", "-shortest"] if sound else []) \
        + ["-movflags", "+faststart", str(out)]
    return desc, cmd


def encode(src: str, out: Path, size=None, sound=False, on_ready=None, stop_after: float = 0) -> bool:
    """Run src through the pipeline into out until SIGINT/SIGTERM (or stop_after seconds, for tests)."""
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import GLib, Gst
    Gst.init(None)
    enc = encoder()
    r = w = None
    if enc != "vp8":
        r, w = os.pipe()
    desc, cmd = pipeline(src, out, enc, size, sound, w)
    ff = None
    if cmd:
        ff = subprocess.Popen(cmd, stdin=r, stdout=subprocess.DEVNULL)
        os.close(r)
    pipe = Gst.parse_launch(desc)
    loop = GLib.MainLoop()
    ok = {"err": ""}

    def on_msg(_bus, m):
        if m.type == Gst.MessageType.EOS:
            loop.quit()
        elif m.type == Gst.MessageType.ERROR:
            err, dbg = m.parse_error()
            ok["err"] = err.message
            print(f"gstreamer: {err.message} {dbg}", flush=True)
            loop.quit()

    stopping = {"n": 0}

    def finish(*_):
        stopping["n"] += 1
        if stopping["n"] == 1:
            pipe.send_event(Gst.Event.new_eos())          # flushes the last frames into the file
            GLib.timeout_add_seconds(6, lambda: loop.quit() or False)
        else:
            loop.quit()
        return True

    b = pipe.get_bus()
    b.add_signal_watch()
    b.connect("message", on_msg)
    try:
        gi.require_version("GLibUnix", "2.0")
        from gi.repository import GLibUnix
        signal_add = GLibUnix.signal_add
    except (ImportError, ValueError):                                     # older PyGObject
        signal_add = GLib.unix_signal_add
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal_add(GLib.PRIORITY_DEFAULT, sig, finish)
    if stop_after:
        GLib.timeout_add(int(stop_after * 1000), lambda: finish() and False)
    if on_ready:
        on_ready(finish)
    pipe.set_state(Gst.State.PLAYING)
    loop.run()
    pipe.set_state(Gst.State.NULL)
    if ff:
        os.close(w)                                         # EOF: ffmpeg writes the index and exits
        try:
            ff.wait(30)
        except subprocess.TimeoutExpired:
            ff.send_signal(signal.SIGINT)
            try:
                ff.wait(10)
            except subprocess.TimeoutExpired:
                ff.kill()
    return out.is_file() and out.stat().st_size > 0


def run(argv: list[str]) -> int:
    from grimoire.spells.shotl import portal
    if state():
        print("already recording", flush=True)
        return 1
    settings = shots.load()
    token = "" if "--pick" in argv else settings["restore_token"]
    try:
        try:
            sess, fd, node, size, new = portal.screencast(token, pointer="--pointer" in argv)
        except portal.PortalError as e:
            if not token or str(e) == "cancelled":
                raise
            sess, fd, node, size, new = portal.screencast("", pointer="--pointer" in argv)    # stale token
    except portal.PortalError as e:
        if str(e) != "cancelled":
            _notify("Recording didn't start", str(e))
        print(f"portal: {e}", flush=True)
        return 1
    if new:
        shots.update(restore_token=new)
    out = shots.new_path(video=True, ext=".webm" if encoder() == "vp8" else ".mp4")
    STATE.write_text(json.dumps({"pid": os.getpid(), "path": str(out), "started": time.time()}))
    src = (f"pipewiresrc fd={fd} path={node} do-timestamp=true keepalive-time=1000 on-disconnect=eos "
           f"client-name=ShotL")
    try:
        saved = encode(src, out, size, "--sound" in argv, on_ready=lambda fin: portal.on_closed(sess, fin))
    finally:
        portal.close(sess)
        STATE.unlink(missing_ok=True)                       # our own marker file
    if saved:
        shots.add(out)
        from grimoire.fsutil import tilde
        _notify("Recording saved", tilde(out))
        return 0
    _notify("Recording failed", f"Nothing was written; see {LOG}")
    return 1


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "toggle"
    rest = argv[1:]
    if cmd == "run":
        return run(rest)
    if cmd == "status":
        st = state()
        print(f"recording to {st['path']} for {time.time() - st['started']:.0f} s" if st else
              f"not recording; recordings are {describe()}")
        return 0
    if cmd == "stop" or (cmd == "toggle" and state()):
        print("stopping" if stop() else "not recording")
        return 0
    if cmd in ("start", "toggle"):
        s = shots.load()
        msg = start(sound="--sound" in rest or s["sound"], pointer="--no-pointer" not in rest, pick="--pick" in rest)
        print(msg or "recording: pick a screen or window if KDE asks; run it again to stop")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
