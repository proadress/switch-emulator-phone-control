# switch-emulator-phone-control

把手機(iPhone、Android 都可以,只要有瀏覽器)變成 Switch 模擬器的手把。最多 4 支手機，各自當 P1 到 P4。

手機用瀏覽器打開一個網頁就是手把；電腦上的伺服器把按鍵轉成 **DSU（cemuhook）UDP 手把**，
支援 DSU 的模擬器（例如 Eden、Cemu、Dolphin）直接讀得到。完全不經過鍵盤，
所以不會碰到快捷鍵、輸入法或視窗焦點的問題。

## 功能

- 4 位玩家按鍵完全一樣：ABXY、L/R、ZL/ZR、+/−、十字鍵、兩支類比搖桿、L3/R3
- 左搖桿是浮動式：手指按在左半邊哪裡，搖桿就從哪裡開始推
- 啟動時在終端機印出 QR code，手機掃了就能用
- 4 種外觀可以切換（中間的數字鈕），淺色、深色主題（中間最上面的鈕），選擇會記住
- 可以加到 iPhone 主畫面，像 App 一樣全螢幕開啟
- 防卡鍵：手機鎖螢幕、切 App 或斷線 3 秒，該玩家的按鍵全部放開
- 只用 Python 標準函式庫，不用另外安裝套件

## 需求

- Python 3（測試環境：macOS 27、Python 3.14）
- 手機和電腦在同一個網路（同一個 Wi-Fi，或電腦開網路分享給手機）

## 使用

```bash
python3 server.py
```

終端機會列出這台電腦的每個網路位址，每個位址附一個 QR code。手機掃描後把手機轉成橫的，
在中間選 P1 到 P4。按 Ctrl+C 結束。

### 加到 iPhone 主畫面

Safari 打開手把網頁 → 分享 → 加入主畫面。網址裡的 token 會存在 `.token`，
伺服器重開後不會變，所以主畫面的捷徑可以一直用。電腦的 IP 變了就要重新加。

## 接上模擬器

伺服器在 `127.0.0.1:26760` 提供 4 支 DSU 手把（slot 0 到 3 對應 P1 到 P4），
這也是大多數模擬器預設的 DSU 位址。

**Eden（yuzu 系列，在 Eden v0.2.1 macOS 版實測）**

先關掉 Eden（它結束時會把設定寫回去），再改 `~/.config/eden/qt-config.ini` 的 `[Controls]`：

```ini
enable_udp_controller=true
player_0_button_a="engine:cemuhookudp,guid:00000000-0000-0000-0000-00007f000001,port:26760,pad:0,button:8192"
player_0_lstick="engine:cemuhookudp,guid:00000000-0000-0000-0000-00007f000001,port:26760,pad:0,axis_x:0,axis_y:1,deadzone:0.100000,range:1.000000"
```

- `pad` 是第幾支手把（P1 = 0）；`guid` 是伺服器 IP 的寫法（`127.0.0.1` = `7f000001`）
- `button` 填下表的數字，右搖桿用 `axis_x:2,axis_y:3`
- 每個 `player_N_xxx` 都要再加一行 `player_N_xxx\default=false`，Eden 才會用你寫的值
- 體感來源要有東西，例如 `player_0_motionleft="engine:keyboard,code:0,toggle:0"`（等於永遠靜止），
  不能空著

按鍵對照（DSU 沿用 PlayStation 的名稱）：

| Switch | DSU | `button` |
|---|---|---|
| A / B / X / Y | ○ / × / △ / □ | 8192 / 16384 / 4096 / 32768 |
| L / R / ZL / ZR | L1 / R1 / L2 / R2 | 1024 / 2048 / 256 / 512 |
| + / − | Options / Share | 8 / 1 |
| 十字鍵 上 / 右 / 下 / 左 | | 16 / 32 / 64 / 128 |
| L3 / R3 | | 2 / 4 |

## 設定

用環境變數調整：

| 變數 | 預設 | 用途 |
|---|---|---|
| `PAD_PORT` | `8765` | 手把網頁的埠 |
| `PAD_DSU_PORT` | `26760` | 給模擬器的 DSU 埠 |
| `PAD_TOKEN` | 自動產生，存在 `.token` | 網址裡的通行碼 |

## 測試

```bash
python3 test_pad.py
```

會用另一組埠啟動一份獨立的伺服器（不影響正在跑的模擬器），檢查網址保護、DSU 封包格式、
4 位玩家每顆按鍵和搖桿、防卡鍵，共 20 項。

## 限制和安全

- 網頁走區域網路的 HTTP。同一個網路裡，拿到完整網址（含 token）的人就能操作手把，網址不要外傳。
- DSU 埠只開在本機（`127.0.0.1`），網路上的其他裝置連不到。
- 沒有體感：iPhone 的網頁要讀陀螺儀必須是 HTTPS。伺服器回報的是「手把靜止」（1G 重力），
  不是全 0，因為真的手把不會出現全 0 的加速度。

## 授權

MIT，見 `LICENSE`。QR code 產生器 `qrcodegen.py` 來自 [Project Nayuki](https://www.nayuki.io/page/qr-code-generator-library)，MIT 授權。
