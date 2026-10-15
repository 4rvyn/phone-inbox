"""Receives photos and videos from the iPhone shortcut "Send to Laptop" while this window is open.

Files are saved as the original files, named by capture time, so sorting by name gives the order they
were taken in. On networks that wall devices off from each other (campus, office, guest Wi-Fi) the laptop turns
on its own Wi-Fi hotspot and shows a QR code to join it; closing the window turns it off again.

    python server.py          open the receiving window
    python server.py --info   print the address and token for the iPhone shortcut
"""
import ctypes
import json
import logging
import mimetypes
import msvcrt
import os
import re
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

try:
    import segno
except ImportError:
    sys.exit("  Missing the QR code library. Run setup.ps1, or:  py -3 -m pip install --user segno")

PORT = 8765
HOME = Path(__file__).resolve().parent
CONFIG_PATH = HOME / "config.json"
DATE_FORMAT = "%Y-%m-%d_%H-%M-%S"
CHUNK = 1024 * 1024
NOTIFY_DELAY_S = 5  # one notification per batch, sent this long after the last file
HOTSPOT_CHECK_S = 30  # Windows turns an unused hotspot off after a while; switch it back on
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
HOTSPOT_PREFIX = "192.168.137."  # Windows always gives its Mobile Hotspot network these addresses
MARKER = HOME / "hotspot-owned.txt"  # holds the window's process ID while it has the hotspot on
CONTENT_TYPES = {
    "image/heic": ".HEIC", "image/heif": ".HEIC", "image/jpeg": ".JPG", "image/png": ".PNG",
    "image/gif": ".GIF", "image/x-adobe-dng": ".DNG", "video/quicktime": ".MOV", "video/mp4": ".MP4",
}
EXIFTOOL = shutil.which("exiftool") or str(Path.home() / "AppData/Local/Programs/ExifTool/exiftool.exe")

log = logging.getLogger("phone-inbox")


def load_config():
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else {}
    config.setdefault("token", secrets.token_urlsafe(16))
    config.setdefault("folder", str(Path.home() / "Pictures" / "From iPhone"))
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config


# ---------- files ----------

def capture_date(path):
    """Reads when a photo or video was taken from the file itself, or None if it has no date."""
    try:
        result = subprocess.run(
            [EXIFTOOL, "-api", "QuickTimeUTC", "-d", DATE_FORMAT, "-s3",
             "-DateTimeOriginal", "-CreationDate", "-CreateDate", "-DateCreated", str(path)],
            capture_output=True, text=True, timeout=60, creationflags=NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("could not read date: %s", e)
        return None
    for line in result.stdout.splitlines():
        # Tags are listed in order of preference.
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}", line.strip()):
            return line.strip()
    return None


def sniff_extension(head):
    """Guesses a file extension from its first bytes, since the phone sends no file name."""
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"heic", b"heix", b"heim", b"heis", b"mif1", b"msf1", b"hevc"):
            return ".HEIC"
        if brand in (b"avif", b"avis"):
            return ".AVIF"
        return ".MOV" if brand == b"qt  " else ".MP4"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".WEBP"
    if head[:4] == b"%PDF":
        return ".PDF"
    if head[:3] == b"\xff\xd8\xff":
        return ".JPG"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return ".PNG"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return ".DNG"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return ".GIF"
    return ""


def clean_name(name):
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name[:80] or "file"


class Notifier:
    """Shows one Windows notification per batch of received files."""

    def __init__(self, folder):
        self.folder = folder
        self.count = 0
        self.timer = None
        self.lock = threading.Lock()

    def file_saved(self):
        with self.lock:
            self.count += 1
            if self.timer:
                self.timer.cancel()
            self.timer = threading.Timer(NOTIFY_DELAY_S, self._show)
            self.timer.daemon = True
            self.timer.start()

    def _show(self):
        with self.lock:
            count, self.count = self.count, 0
        text = f"{count} file{'s' if count != 1 else ''} received. Click to open the folder."
        print(f"\n  Batch done: {text.split('.')[0]}.\n")
        folder_url = "file:///" + quote(str(self.folder).replace("\\", "/"))
        xml = (
            f'<toast activationType="protocol" launch="{folder_url}">'
            f"<visual><binding template=\"ToastGeneric\"><text>From iPhone</text><text>{text}</text>"
            f"</binding></visual></toast>"
        )
        script = (
            "[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]>$null;"
            "[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom,ContentType=WindowsRuntime]>$null;"
            "$x=New-Object Windows.Data.Xml.Dom.XmlDocument;"
            f"$x.LoadXml('{xml}');"
            "$id='{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe';"
            "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($id).Show("
            "[Windows.UI.Notifications.ToastNotification]::new($x))"
        )
        try:
            subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                             creationflags=NO_WINDOW)
        except OSError as e:
            log.warning("notification failed: %s", e)


class ExclusiveServer(ThreadingHTTPServer):
    """On Windows the default "reuse address" option lets a second program take the same port, which
    would let two windows run at once. This claims the port exclusively instead."""
    allow_reuse_address = False

    def server_bind(self):
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Handler(BaseHTTPRequestHandler):
    server_version = "phone-inbox"
    timeout = 120  # seconds of silence before a stalled upload is dropped

    def log_message(self, fmt, *args):
        log.info("%s %s", self.client_address[0], fmt % args)

    def reply(self, code, text):
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        query = parse_qs(urlparse(self.path).query)
        token = self.headers.get("X-Token") or query.get("token", [""])[0]
        if secrets.compare_digest(token, self.server.config["token"]):
            return True
        self.reply(403, "wrong token")
        return False

    def do_GET(self):
        if self.authorized():
            self.reply(200, "ok") if urlparse(self.path).path == "/ping" else self.reply(404, "not found")

    def do_POST(self):
        if not self.authorized():
            return
        url = urlparse(self.path)
        if url.path != "/upload":
            self.reply(404, "not found")
            return
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        for key in ("name", "date"):
            if self.headers.get(f"X-{key}"):
                query[key] = self.headers[f"X-{key}"].strip()
        folder = Path(self.server.config["folder"])
        folder.mkdir(parents=True, exist_ok=True)
        part = folder / f".incoming-{os.getpid()}-{secrets.token_hex(6)}.part"
        try:
            size = self.receive_body(part)
        except ValueError as e:
            part.unlink(missing_ok=True)
            log.warning("malformed upload rejected: %s", e)
            self.reply(400, "malformed upload")
            return
        except Exception as e:
            part.unlink(missing_ok=True)
            log.warning("upload failed: %s", e)
            print(f"  ! An upload broke off ({e}). Send that item again.")
            return
        if size == 0:
            part.unlink(missing_ok=True)
            self.reply(400, "empty file")
            return
        self.server.session.record_arrival(self.client_address[0])

        date = query.get("date", "")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}", date):
            date = capture_date(part) or datetime.now().strftime(DATE_FORMAT)
        # Without a name from the phone the file is called just by its capture time.
        name = Path(clean_name(query["name"])) if query.get("name") else Path("")
        suffix = name.suffix
        if not suffix:
            with open(part, "rb") as f:
                head = f.read(16)
            content_type = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
            suffix = (sniff_extension(head) or CONTENT_TYPES.get(content_type)
                      or (mimetypes.guess_extension(content_type) or "").upper())
            if not suffix:
                log.info("unknown file type: Content-Type %r, first bytes %s", content_type, head.hex(" "))
        stem = f"{date}_{name.stem}" if name.stem else date
        target = folder / f"{stem}{suffix}"
        n = 2
        while target.exists():
            if target.stat().st_size == size:
                part.unlink()
                print(f"  = {target.name} (already there, skipped)")
                self.reply(200, f"already there: {target.name}")
                return
            target = folder / f"{stem}-{n}{suffix}"
            n += 1
        part.replace(target)
        stamp = time.mktime(datetime.strptime(date, DATE_FORMAT).timetuple())
        os.utime(target, (stamp, stamp))

        self.server.notifier.file_saved()
        log.info("saved %s (%.1f MB)", target.name, size / 1e6)
        print(f"  + {target.name}  ({size / 1e6:.1f} MB)")
        self.reply(200, f"saved {target.name}")

    def receive_body(self, part):
        """Streams the request body to disk; supports fixed length and chunked uploads."""
        size = 0
        with open(part, "wb") as out:
            if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
                while True:
                    length = int(self.rfile.readline(1024).strip().split(b";")[0], 16)
                    if length < 0:
                        raise ValueError("negative chunk size")
                    if length == 0:
                        self.rfile.readline()
                        break
                    remaining = length
                    while remaining:
                        block = self.rfile.read(min(CHUNK, remaining))
                        if not block:
                            raise ConnectionError("connection closed mid-chunk")
                        out.write(block)
                        remaining -= len(block)
                    size += length
                    self.rfile.readline()
            else:
                remaining = int(self.headers.get("Content-Length", "0"))
                if remaining < 0:
                    raise ValueError("negative Content-Length")
                while remaining:
                    block = self.rfile.read(min(CHUNK, remaining))
                    if not block:
                        raise ConnectionError("connection closed before the file was complete")
                    out.write(block)
                    remaining -= len(block)
                    size += len(block)
        return size


# ---------- network situation ----------

def current_network():
    """Returns (network name, laptop address, prefix length, router address, login type) of the main
    connection. The login type is how Windows' network API names it (e.g. "RsnaPsk" for a WPA2 shared
    password, "Rsna" for a WPA2 personal login), the same in every Windows language; "Wired" for cables."""
    script = (
        "$c = Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' }"
        " | Select-Object -First 1;"
        "$null = [Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime];"
        "$p = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile();"
        "$login = if ($p -and $p.IsWlanConnectionProfile) { $p.NetworkSecuritySettings.NetworkAuthenticationType } else { 'Wired' };"
        "if ($c) { '{0}|{1}|{2}|{3}|{4}' -f $c.NetProfile.Name, $c.IPv4Address[0].IPAddress,"
        " $c.IPv4Address[0].PrefixLength, $c.IPv4DefaultGateway[0].NextHop, $login }"
    )
    out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                         capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW).stdout.strip()
    if out.count("|") != 4:
        return None
    name, ip, prefix, router, login = out.split("|")
    return name, ip, int(prefix), router, login


def arp(ip, source):
    """Asks the local network which device has this address; returns its hardware address or None."""
    mac = (ctypes.c_ubyte * 8)()
    length = ctypes.c_ulong(8)
    to_int = lambda a: struct.unpack("<I", socket.inet_aton(a))[0]
    if ctypes.windll.iphlpapi.SendARP(to_int(ip), to_int(source), mac, ctypes.byref(length)) != 0:
        return None
    return bytes(mac[:length.value])


SHARED_PASSWORD = {"WpaPsk", "RsnaPsk", "Wpa3Sae", "SharedKey80211"}
PERSONAL_LOGIN = {"Wpa", "Rsna", "Wpa3", "Wpa3Enterprise", "Wpa3Enterprise192Bits"}


def describe_login(login):
    if login in SHARED_PASSWORD:
        return "shared password"
    if login in PERSONAL_LOGIN:
        return "personal login"
    return "cable connection" if login == "Wired" else "open network"


def probably_walled_off(login):
    """Rule of thumb when a network is new: networks with one shared password (home, family) let devices
    reach each other; networks with a personal login (campus, office), open guest networks and cable
    connections almost always don't. What actually works is learned afterwards and overrides this."""
    return login not in SHARED_PASSWORD


def network_key(name, ip, router):
    """Identifies a network by its name and its router, so two networks both called eduroam differ."""
    mac = arp(router, ip)
    return f"{name} / {mac.hex('-') if mac else router}"


def hotspot(mode):
    """Runs hotspot.ps1 with on, off or name; returns its output."""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(HOME / "hotspot.ps1"), mode],
        capture_output=True, text=True, timeout=90, creationflags=NO_WINDOW,
    )
    return (result.stdout + result.stderr).strip()


def print_join_qr():
    """Prints the hotspot as a Wi-Fi QR code (like Windows Settings shows), for the iPhone camera.
    The password goes only into the QR code on screen, never into the log."""
    lines = hotspot("wifi").splitlines()
    if len(lines) < 2:
        return False
    escape = lambda s: re.sub(r'([\\;,:"])', r"\\\1", s)
    qr = segno.make(f"WIFI:T:WPA;S:{escape(lines[0])};P:{escape(lines[1])};;", error="m")
    rows = [list(row) for row in qr.matrix_iter(border=2)]
    if len(rows) % 2:
        rows.append([0] * len(rows[0]))
    # Light modules are drawn as white blocks on black, two rows per text line so modules stay square.
    blocks = {(0, 0): "█", (0, 1): "▀", (1, 0): "▄", (1, 1): " "}
    print()
    for top, bottom in zip(rows[0::2], rows[1::2]):
        print("  \x1b[97;40m" + "".join(blocks[(t, b)] for t, b in zip(top, bottom)) + "\x1b[0m")
    return True


def remove_partial_files(folder, pid=None):
    """Deletes half-received uploads (of one window process, or all of them)."""
    pattern = f".incoming-{pid}-*.part" if pid else ".incoming-*.part"
    for part in Path(folder).glob(pattern):
        try:
            part.unlink()
        except OSError:
            pass


def clean_up_previous_run(folder):
    """Undoes what an earlier window left behind if it could not clean up (e.g. power loss)."""
    if MARKER.exists():
        print("  Cleaning up after the last window, which did not close normally...")
        log.info("previous run left the hotspot on: %s", hotspot("off"))
        MARKER.unlink(missing_ok=True)
    remove_partial_files(folder)


def start_guard(folder):
    """Starts guard.ps1, a hidden helper that outlives this window: once this process has ended in any
    way (closed, crashed, killed), it turns the hotspot off if this window had turned it on and deletes
    half-received files."""
    args = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", str(HOME / "guard.ps1"), "-ParentPid", str(os.getpid()), "-Folder", str(folder)]
    # Its own invisible console, so closing this window doesn't reach it. (With no console at all,
    # PowerShell quits immediately.)
    own_console = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen(args, creationflags=own_console | subprocess.CREATE_BREAKAWAY_FROM_JOB)
    except OSError:  # the terminal does not allow leaving its job; then start it normally
        subprocess.Popen(args, creationflags=own_console)


class Session:
    """Tracks whether this window turned the hotspot on, so closing it can undo exactly that, and
    learns per network whether the phone reached the laptop directly or over the laptop's hotspot."""

    def __init__(self, config):
        self.config = config
        self.network = None
        self.hotspot_name = None
        self.hotspot_ours = False
        self.cleaned = False
        self.lock = threading.Lock()
        self.hotspot_lock = threading.Lock()  # switching on and off never overlap
        self.cleanup_lock = threading.Lock()
        self.cleanup_done = False

    def record_arrival(self, client_ip):
        if not self.network:
            return
        way = "hotspot" if client_ip.startswith(HOTSPOT_PREFIX) else "direct"
        with self.lock:
            networks = self.config.setdefault("networks", {})
            # A direct arrival proves the network lets devices talk; a send over the hotspot proves
            # nothing about the network (you may just have pressed H), so it never overrides that proof.
            if networks.get(self.network) == way or (way == "hotspot" and networks.get(self.network) == "direct"):
                return
            networks[self.network] = way
            CONFIG_PATH.write_text(json.dumps(self.config, indent=2), encoding="utf-8")
        log.info("learned: %s -> %s", self.network, way)
        how = "directly" if way == "direct" else "over the laptop's own network"
        print(f"  (Remembered: on this network the phone reaches the laptop {how}.)")

    def start_hotspot(self):
        print("  Turning on the laptop's own Wi-Fi network...")
        with self.hotspot_lock:
            if self.cleaned:
                return False
            # Written before switching on, so the guard also undoes a switch-on cut off halfway.
            MARKER.write_text(str(os.getpid()))
            message = hotspot("on")
            log.info("hotspot on: %s", message)
            if "Success" in message:
                self.hotspot_ours = True
            else:
                MARKER.unlink(missing_ok=True)  # failed, or someone else had it on already: not ours to undo
        if "Success" not in message and "already" not in message:
            print(f"  ! Could not turn it on: {message}")
            print("    Settings > Network & internet > Mobile hotspot shows the reason.")
            return False
        self.hotspot_name = hotspot("name")
        return True

    def keep_hotspot_on(self):
        with self.hotspot_lock:
            if self.hotspot_ours and not self.cleaned:
                if "Success" in hotspot("on"):
                    log.info("hotspot switched back on")

    def cleanup(self):
        """Runs once, however the window ends; a second caller waits until it is done. Anything it
        can't finish (e.g. the process is killed), the guard finishes."""
        self.cleaned = True  # stops any further switching on
        with self.cleanup_lock:
            if self.cleanup_done:
                return
            self._undo()
            self.cleanup_done = True

    def _undo(self):
        with self.hotspot_lock:
            if self.hotspot_ours:
                print("  Turning the laptop's own Wi-Fi network off...")
                message = hotspot("off")
                log.info("hotspot off: %s", message)
                if "Success" in message or "already" in message:
                    MARKER.unlink(missing_ok=True)
        remove_partial_files(self.config["folder"], os.getpid())


def describe_situation(session):
    network = current_network()
    if not network:
        print("  Laptop has no network connection. Connect it to Wi-Fi and start this again.")
        return
    name, ip, _, router, login = network
    session.network = network_key(name, ip, router)
    known = session.config.get("networks", {}).get(session.network)
    print(f"  Laptop is on  {name}")

    if known == "direct":
        print("  Known network: the phone reaches the laptop directly here.")
    elif known == "hotspot":
        print("  Known network: devices are walled off from each other here.")
    elif probably_walled_off(login):
        print(f"  New network ({describe_login(login)}): networks like this wall devices off from each other.")
    else:
        print(f"  New network ({describe_login(login)}): home-type Wi-Fi, devices can reach each other.")

    if known == "direct" or (known is None and not probably_walled_off(login)):
        print(f"\n  On the iPhone: be on the same Wi-Fi ({name}), then run Send to Laptop.")
        print("\n  (If the phone can't connect anyway, press H for the laptop's own network.)")
        return
    if not session.start_hotspot():
        print(f"\n  On the iPhone: be on the same Wi-Fi ({name}) and try Send to Laptop.")
        return
    print_hotspot_instructions(session, name)


def print_hotspot_instructions(session, normal_network):
    if print_join_qr():
        print(f"\n  On the iPhone: open the Camera, point it at this code, tap \"Join\".")
        print(f"  (Or Settings > Wi-Fi > tap  {session.hotspot_name})")
    else:
        print(f"\n  On the iPhone: Settings > Wi-Fi > tap  {session.hotspot_name}")
    print(f"  Then run Send to Laptop. Afterwards tap {normal_network} again.")


def main():
    config = load_config()
    if "--info" in sys.argv:
        host = os.environ.get("COMPUTERNAME", "localhost")
        print(f"\n  URL for the shortcut's \"Get Contents of URL\" action:\n")
        print(f"    http://{host}.local:{PORT}/upload?token={config['token']}\n")
        print(f"  Files are saved to {config['folder']}\n")
        return

    handler = RotatingFileHandler(HOME / "inbox.log", maxBytes=1_000_000, backupCount=1, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(message)s")
    ctypes.windll.kernel32.SetConsoleTitleW("Receive photos from iPhone")
    sys.stdout.reconfigure(encoding="utf-8")  # block characters of the QR code
    os.system("")  # lets the classic Windows console understand the QR code's colour codes

    try:
        server = ExclusiveServer(("0.0.0.0", PORT), Handler)
    except OSError:
        print("  This is already open in another window. Use that one.")
        input("\n  Press Enter to close.")
        return
    # Only one window can get this far (the port is taken), so leftovers belong to an earlier run.
    log.info("window opened, saving to %s", config["folder"])
    clean_up_previous_run(config["folder"])
    start_guard(config["folder"])

    session = Session(config)
    server.config = config
    server.session = session
    server.notifier = Notifier(config["folder"])
    threading.Thread(target=server.serve_forever, daemon=True).start()

    # Closing the window (X), Ctrl+C, logging off: Windows allows a few seconds to clean up, and the
    # guard finishes whatever doesn't fit in them.
    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)
    def on_console_event(event):
        log.info("window closing (console event %d)", event)
        session.cleanup()
        return False

    ctypes.windll.kernel32.SetConsoleCtrlHandler(on_console_event, True)

    try:
        print("\n  Receive photos from iPhone")
        print("  " + "-" * 40)
        describe_situation(session)
        if not Path(EXIFTOOL).exists():
            print("\n  ! ExifTool is missing, so files get the arrival time instead of the capture time.")
            print("    Run setup.ps1 to install it.")
        print(f"\n  Files go to {config['folder']}")
        print("  Close this window (or press Q) when you're done.\n")

        last_check = time.monotonic()
        while True:
            if not ctypes.windll.kernel32.GetConsoleWindow():
                log.info("window disappeared without closing normally")
                break
            if msvcrt.kbhit():
                key = msvcrt.getwch().lower()
                if key == "q":
                    break
                if key == "h" and not session.hotspot_ours and session.start_hotspot():
                    print_hotspot_instructions(session, "your normal Wi-Fi")
                    print()
            if time.monotonic() - last_check > HOTSPOT_CHECK_S:
                session.keep_hotspot_on()
                last_check = time.monotonic()
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    except Exception:
        log.exception("window stopped by an error")
        raise
    finally:
        session.cleanup()
        server.shutdown()
        server.server_close()
        log.info("window closed")


if __name__ == "__main__":
    main()
