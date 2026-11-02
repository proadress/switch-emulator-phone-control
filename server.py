"""Phone-as-controller server: phones open a web page on the LAN and become four virtual controllers that
Eden reads over its built-in UDP input (DSU / cemuhook protocol). No keyboard events are involved."""
import json, os, secrets, socket, struct, subprocess, threading, time, zlib
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(HERE, ".token")
# Kept across restarts so a home-screen shortcut (its URL holds the token) keeps working.
TOKEN = os.environ.get("PAD_TOKEN") or (open(TOKEN_FILE).read().strip() if os.path.exists(TOKEN_FILE) else "")
if not TOKEN:
    TOKEN = secrets.token_hex(3)
    open(TOKEN_FILE, "w").write(TOKEN)
PORT = int(os.environ.get("PAD_PORT", "8765"))
DSU_PORT = int(os.environ.get("PAD_DSU_PORT", "26760"))  # Eden's default UDP input server is 127.0.0.1:26760
PAGE = open(os.path.join(HERE, "index.html"), "rb").read()
ICON = open(os.path.join(HERE, "icon.png"), "rb").read()
MANIFEST = json.dumps({
    "name": "手機手把", "short_name": "手把", "start_url": f"/?t={TOKEN}", "scope": "/",
    "display": "fullscreen", "orientation": "landscape", "background_color": "#0d0d10", "theme_color": "#0d0d10",
    "icons": [{"src": "/icon.png", "sizes": "512x512", "type": "image/png", "purpose": "any"}],
}, ensure_ascii=False).encode()

STALE = 3.0  # seconds without word from a phone before its pad lets go of everything (page beats every 1 s)
NEUTRAL = dict(b=0, lx=0, ly=0, rx=0, ry=0)
# Per player: latest state from the phone. b is the DSU button mask, sticks are -127..127 with +y up.
pads = {p: dict(NEUTRAL, n=0, t=0.0) for p in (1, 2, 3, 4)}
lock = threading.Lock()
SERVER_ID = secrets.randbits(32)


def packet(kind, body):
    payload = struct.pack("<I", kind) + body
    head = struct.pack("<4sHHII", b"DSUS", 1001, len(payload), 0, SERVER_ID)
    return head[:8] + struct.pack("<I", zlib.crc32(head + payload)) + head[12:] + payload


def slot_info(slot):  # slot, connected, full-gyro model, USB, MAC, battery full
    return struct.pack("<BBBB6sB", slot, 2, 2, 1, bytes([0, 0, 0, 0, 0, slot + 1]), 5)


def pad_data(slot, counter):
    with lock:
        s = pads[slot + 1]
        s = NEUTRAL if time.monotonic() - s["t"] > STALE else dict(s)
    sticks = (128 + s["lx"], 128 + s["ly"], 128 + s["rx"], 128 + s["ry"])
    body = slot_info(slot) + struct.pack("<BIHBB4B", 1, counter, s["b"], 0, 0, *sticks)
    body += bytes(24)  # analog button pressures and two touch points: unused
    # No gyro on the phone page, but report a resting pad (1 g of gravity, no rotation): an all-zero
    # accelerometer is not a state a real pad can be in and can make motion maths divide by zero.
    body += struct.pack("<Q6f", int(time.monotonic() * 1e6), 0, -1, 0, 0, 0, 0)
    return packet(0x100002, body)


def dsu():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", DSU_PORT))  # loopback only: Eden runs on this Mac
    sock.settimeout(1 / 60)
    clients, counter = {}, 0
    while True:
        try:
            data, addr = sock.recvfrom(1024)
            kind = struct.unpack_from("<I", data, 16)[0] if data[:4] == b"DSUC" and len(data) >= 20 else None
            if kind == 0x100000:  # protocol version
                sock.sendto(packet(kind, struct.pack("<H", 1001)), addr)
            elif kind == 0x100001 and len(data) >= 24:  # which slots exist
                count = max(0, min(struct.unpack_from("<i", data, 20)[0], 4))
                for slot in data[24:24 + count]:
                    if slot < 4:
                        sock.sendto(packet(kind, slot_info(slot) + b"\0"), addr)
            elif kind == 0x100002:  # subscribe to pad data; Eden renews this every few seconds
                clients[addr] = time.monotonic()
        except socket.timeout:
            pass
        now = time.monotonic()
        clients = {a: t for a, t in clients.items() if now - t < 5}
        counter = (counter + 1) & 0xFFFFFFFF
        for a in clients:
            for slot in range(4):
                sock.sendto(pad_data(slot, counter), a)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, code, body=b"", ctype="text/plain"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/icon.png":  # iOS fetches the home-screen icon without the token; it holds no secret
            return self.reply(200, ICON, "image/png")
        if q.get("t") != TOKEN:  # anyone on the network could otherwise play with these controllers
            return self.reply(403, b"bad token")
        if u.path == "/":
            return self.reply(200, PAGE, "text/html; charset=utf-8")
        if u.path == "/manifest.json":
            return self.reply(200, MANIFEST, "application/manifest+json")
        if u.path != "/s":
            return self.reply(404)
        try:
            p, n, b = int(q["p"]), int(q["n"]), int(q["b"])
            axes = {k: int(q[k]) for k in ("lx", "ly", "rx", "ry")}
            assert p in pads and 0 <= b <= 0xFFFF and all(-127 <= v <= 127 for v in axes.values())
        except (KeyError, ValueError, AssertionError):
            return self.reply(400)
        with lock:
            if n > pads[p]["n"]:  # the page sends whole states with a rising number; drop late arrivals
                pads[p].update(axes, b=b, n=n, t=time.monotonic())
            elif n == pads[p]["n"]:
                pads[p]["t"] = time.monotonic()
        self.reply(204)


def ips():
    out = subprocess.run(["ifconfig"], capture_output=True, text=True).stdout
    return [l.split()[1] for l in out.splitlines() if l.strip().startswith("inet ") and "127.0.0.1" not in l]


def qr_text(text):
    """QR code drawn with half blocks, two modules per character row. Colours are set explicitly
    (black on white) so it scans the same on dark and light terminal themes."""
    from qrcodegen import QrCode
    q = QrCode.encode_text(text, QrCode.Ecc.LOW)
    n, quiet = q.get_size(), 2
    dark = lambda x, y: 0 <= x < n and 0 <= y < n and q.get_module(x, y)
    colour = lambda d: 16 if d else 231  # xterm-256 black / white
    rows = []
    for y in range(-quiet, n + quiet, 2):
        cells = (f"\033[38;5;{colour(dark(x, y))}m\033[48;5;{colour(dark(x, y + 1))}m▀"
                 for x in range(-quiet, n + quiet))
        rows.append("".join(cells) + "\033[0m")
    return "\n".join(rows)


if __name__ == "__main__":
    threading.Thread(target=dsu, daemon=True).start()
    print("手機掃 QR code 或開網址(要和這台電腦在同一個網路):")
    for ip in ips():
        url = f"http://{ip}:{PORT}/?t={TOKEN}"
        print(f"\n{url}\n{qr_text(url)}")
    print("\nCtrl+C 結束")
    try:
        ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
    except KeyboardInterrupt:
        pass
