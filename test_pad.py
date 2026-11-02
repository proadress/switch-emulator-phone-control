"""One-command test for the phone pad server: python3 test_pad.py
Starts its own server on spare ports (Eden never sees these presses), acts as Eden over DSU and as the
phones over HTTP, and checks every button and stick of every player, cross-talk, ordering and release."""
import os, socket, struct, subprocess, sys, time, urllib.error, urllib.request, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
HTTP, DSU = 18765, 26761
TOKEN = "testtoken"
BITS = {"minus": 0x1, "L3": 0x2, "R3": 0x4, "plus": 0x8, "up": 0x10, "right": 0x20, "down": 0x40, "left": 0x80,
        "ZL": 0x100, "ZR": 0x200, "L": 0x400, "R": 0x800, "X": 0x1000, "A": 0x2000, "B": 0x4000, "Y": 0x8000}
fails = []


def check(ok, what):
    print(("✅ " if ok else "⚠️ ") + what)
    if not ok:
        fails.append(what)


def get(path):
    try:
        return urllib.request.urlopen(f"http://127.0.0.1:{HTTP}{path}", timeout=2).status
    except urllib.error.HTTPError as e:
        return e.code


n = 0
def state(p, b=0, lx=0, ly=0, rx=0, ry=0, seq=None):
    global n
    n += 1
    return get(f"/s?t={TOKEN}&p={p}&n={seq if seq is not None else n}&b={b}&lx={lx}&ly={ly}&rx={rx}&ry={ry}")


def valid(pkt):
    if pkt[:4] != b"DSUS" or struct.unpack_from("<H", pkt, 4)[0] != 1001:
        return False
    if struct.unpack_from("<H", pkt, 6)[0] != len(pkt) - 16:
        return False
    crc = struct.unpack_from("<I", pkt, 8)[0]
    return crc == zlib.crc32(pkt[:8] + b"\0\0\0\0" + pkt[12:])


def request(kind, body=b""):
    payload = struct.pack("<I", kind) + body
    head = struct.pack("<4sHHII", b"DSUC", 1001, len(payload), 0, 1)
    sock.sendto(head + payload, ("127.0.0.1", DSU))


def latest():
    """Latest pad packet per slot after letting the server send for a moment."""
    request(0x100002, bytes(8))
    time.sleep(0.15)
    pads = {}
    try:
        while True:
            pkt = sock.recv(256)
            if struct.unpack_from("<I", pkt, 16)[0] == 0x100002:
                pads[pkt[20]] = pkt
    except BlockingIOError:
        pass
    return pads


def decode(pkt):  # buttons, lx, ly, rx, ry, accel
    b, = struct.unpack_from("<H", pkt, 36)
    sticks = struct.unpack_from("<4B", pkt, 40)
    accel = struct.unpack_from("<3f", pkt, 76)
    return b, *sticks, accel


env = dict(os.environ, PAD_PORT=str(HTTP), PAD_DSU_PORT=str(DSU), PAD_TOKEN=TOKEN)
srv = subprocess.Popen([sys.executable, os.path.join(HERE, "server.py")], env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("127.0.0.1", 0))
try:
    for _ in range(50):
        try:
            get("/icon.png"); break
        except OSError:
            time.sleep(0.1)

    print("== 網址和 token ==")
    check(get("/") == 403, "沒帶 token 打不開手把頁")
    check(get(f"/?t={TOKEN}") == 200, "帶 token 可以打開手把頁")
    check(get("/manifest.json") == 403 and get(f"/manifest.json?t={TOKEN}") == 200, "manifest 要 token")
    check(get("/icon.png") == 200, "圖示不用 token")
    check(state(5) == 400 and state(1, b=0x10000) == 400 and state(1, lx=128) == 400, "超出範圍的輸入會被拒絕")

    print("== DSU 協定 ==")
    sock.setblocking(True); sock.settimeout(1)
    request(0x100000)
    check(valid(sock.recv(256)), "版本回應格式和校驗碼正確")
    request(0x100001, struct.pack("<i", 4) + bytes([0, 1, 2, 3]))
    infos = [sock.recv(256) for _ in range(4)]
    check(all(valid(p) and p[20] == i and p[21] == 2 for i, p in enumerate(infos)), "4 個手把位置都回報已連線")
    sock.setblocking(False)
    pads = latest()
    check(sorted(pads) == [0, 1, 2, 3] and all(len(p) == 100 and valid(p) for p in pads.values()),
          "手把資料封包 100 位元組、校驗碼正確")
    check(all(decode(p)[5] == (0.0, -1.0, 0.0) for p in pads.values()), "體感回報靜止(1G 重力),不是全 0")

    print("== 每位玩家每顆按鍵 ==")
    for p in (1, 2, 3, 4):
        bad = []
        for name, bit in BITS.items():
            state(p, b=bit)
            pads = latest()
            others = [decode(pads[s])[0] for s in range(4) if s != p - 1]
            if decode(pads[p - 1])[0] != bit or any(others):
                bad.append(name)
        state(p)
        check(not bad, f"P{p} 16 顆按鍵各自正確、不串到別人" + (f"(錯:{bad})" if bad else ""))

    print("== 搖桿 ==")
    for p in (1, 2, 3, 4):
        state(p, lx=127, ly=-127, rx=-127, ry=127)
        _, lx, ly, rx, ry, _ = decode(latest()[p - 1])
        state(p)
        _, *center, _ = decode(latest()[p - 1])
        check((lx, ly, rx, ry) == (255, 1, 1, 255) and center == [128] * 4, f"P{p} 兩支搖桿的最大值和中心點正確")

    print("== 防卡鍵 ==")
    state(1, b=BITS["A"], seq=10**15)
    state(1, b=BITS["B"], seq=10**15 - 1)
    check(decode(latest()[0])[0] == BITS["A"], "晚到的舊狀態不會蓋掉新狀態")
    time.sleep(3.3)
    check(decode(latest()[0])[0] == 0, "手機 3 秒沒消息就自動放開全部按鍵")
finally:
    srv.terminate()
    srv.wait()

print(f"\n{'全部通過' if not fails else f'{len(fails)} 項沒過'}")
sys.exit(1 if fails else 0)
