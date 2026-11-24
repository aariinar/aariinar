#!/usr/bin/env python3
"""
winter_night.py - animated ASCII winter forest with a campfire.

Snow falls, the fire flickers, trees sway in the wind, sparks fly up,
fireflies blink and the fire light glows on everything around it.

Run:      python3 winter_night.py
Preview:  python3 winter_night.py --preview   (prints a single colored frame)

Keys:
  q / Esc     quit                 space   pause
  + / -       speed                h       help
  <- / ->     wind  (or a / d)     g       glow on/off
  up / down   snow  (or w / s)     m       moon on/off
  [ / ]       fire                 p       sparks on/off
                                   l       fireflies on/off
"""
import argparse
import curses
import math
import random
import shutil
import sys
import time

# ---------------------------------------------------------------- palettes
FIRE_RAMP = [52, 88, 124, 160, 196, 202, 208, 214, 220, 226, 228, 229, 230, 231]
FIRE_CHARS = " .,:;=+*oxX#%@"
GLOW_RAMP = [94, 130, 136, 172, 178, 214, 220, 221, 222, 223]
SPARK_RAMP = [88, 124, 160, 202, 208, 214, 220, 226]

LAYERS = {
    #         body  edge  snow  trunk  fill chars          sparse  sway
    "back":  (237,  240,  246,  236,   "^'.:",              0.45,   0.8),
    "mid":   (65,   102,  252,  94,    "/\\^Am*",           0.15,   1.3),
    "front": (108,  145,  255,  130,   "#%&AmH#m",          0.04,   2.2),
}


def h32(*vals):
    """Small deterministic hash -> int, so tree texture doesn't flicker."""
    x = 2166136261
    for v in vals:
        x ^= v & 0xFFFFFFFF
        x = (x * 16777619) & 0xFFFFFFFF
    x ^= x >> 13
    x = (x * 0x5BD1E995) & 0xFFFFFFFF
    x ^= x >> 15
    return x


# ---------------------------------------------------------------- objects
class Tree:
    def __init__(self, x, base, height, layer, rng):
        self.x, self.base, self.h, self.layer = x, base, height, layer
        self.phase = rng.random() * math.tau
        self.freq = rng.uniform(0.55, 1.05)
        self.slope = rng.uniform(0.85, 1.2)
        self.seed = rng.randrange(1 << 30)


class Fire:
    """Classic 'doom fire' heat propagation, shaped into a campfire cone."""

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.g = [[0.0] * w for _ in range(h)]

    def step(self, intensity, wind):
        w, h, g = self.w, self.h, self.g
        cx = (w - 1) / 2
        power = min(1.0, intensity / 1.4)
        for x in range(w):
            fall = max(0.0, 1 - (abs(x - cx) / (w / 2)) ** 1.6)
            g[h - 1][x] = min(1.0, fall * power * random.uniform(0.7, 1.15))
        decay = 1.5 / (h * max(0.35, min(1.6, intensity / 1.5)))
        lean = max(-0.9, min(0.9, wind / 5))
        for y in range(h - 1):
            row, below = g[y], g[y + 1]
            for x in range(w):
                sx = x + random.randint(-1, 1)
                if random.random() < abs(lean):
                    sx -= 1 if lean > 0 else -1
                sx = 0 if sx < 0 else (w - 1 if sx >= w else sx)
                v = below[sx] - random.random() * decay
                row[x] = v if v > 0 else 0.0

    def heat_sum(self):
        return sum(self.g[self.h - 1]) / self.w


# ---------------------------------------------------------------- scene
class Scene:
    def __init__(self, W, H, seed=None):
        self.W, self.H = W, H          # H excludes the status line
        self.rng = random.Random(seed)
        self.t = 0.0
        self.speed, self.wind, self.snow, self.fire_lvl = 1.0, 2.4, 1.6, 1.7
        self.glow_on = self.moon_on = self.sparks_on = self.flies_on = True
        self.build()

    # ------------------------------------------------ layout
    def build(self):
        W, H, rng = self.W, self.H, self.rng
        self.horizon = int(H * 0.56)

        fw = max(12, min(30, W // 7))
        fh = max(7, min(20, H // 3))
        self.fire = Fire(fw, fh)
        self.fire_x0 = W // 2 - fw // 2
        self.fire_base = H - 3                     # bottom row of flames
        self.glow_c = (W / 2, self.fire_base - 1)
        self.glow_r = max(8.0, H * 0.55)

        self.trees = {"back": [], "mid": [], "front": []}
        for _ in range(max(6, W // 6)):
            self.trees["back"].append(Tree(
                rng.randrange(W), self.horizon + rng.randint(0, 1),
                rng.randint(max(3, int(H * .10)), max(4, int(H * .22))), "back", rng))
        for _ in range(max(3, W // 13)):
            x = rng.randrange(W)
            if abs(x - W / 2) < fw * 0.8:
                x = int(W / 2 + (fw * 1.2 if x >= W / 2 else -fw * 1.2))
            self.trees["mid"].append(Tree(
                x, self.horizon + rng.randint(2, max(3, int(H * .14))),
                rng.randint(max(5, int(H * .24)), max(6, int(H * .40))), "mid", rng))
        side = max(2, W // 45)
        for i in range(side):
            for lo, hi in ((0, .22), (.78, 1.0)):
                x = int(rng.uniform(lo, hi) * W)
                self.trees["front"].append(Tree(
                    x, H - rng.randint(1, 3),
                    rng.randint(int(H * .50), max(int(H * .5) + 1, int(H * .82))), "front", rng))
        for lst in self.trees.values():
            lst.sort(key=lambda tr: tr.base)

        self.stars = [(rng.randrange(W), rng.randrange(max(1, self.horizon - 2)),
                       rng.random() * math.tau, rng.uniform(0.6, 3.0))
                      for _ in range(W * self.horizon // 28)]
        self.moon = (int(W * 0.8), max(4, int(H * 0.14)), max(2, min(5, H // 12)))

        self.flakes = []
        self.sparks = []
        self.flies = [[rng.uniform(0, W), rng.uniform(self.horizon - 4, H - 4),
                       rng.random() * math.tau, rng.uniform(0.5, 1.5)]
                      for _ in range(max(4, W // 18))]
        self.adjust_snow()

    def adjust_snow(self):
        target = int(self.W * self.H * 0.012 * self.snow)
        while len(self.flakes) < target:
            self.flakes.append(self.new_flake(top=False))
        del self.flakes[target:]

    def new_flake(self, top=True):
        r = self.rng
        return [r.uniform(0, self.W), -1.0 if top else r.uniform(0, self.H),
                r.random(), r.random() * math.tau]

    # ------------------------------------------------ simulation
    def update(self, dt):
        dt *= self.speed
        self.t += dt
        t, W, H, r = self.t, self.W, self.H, self.rng

        self._fire_acc = getattr(self, "_fire_acc", 0.0) + dt * 22
        while self._fire_acc >= 1:
            self._fire_acc -= 1
            self.fire.step(self.fire_lvl, self.wind)

        for f in self.flakes:
            z = f[2]
            f[1] += (2.0 + z * 5.0) * dt
            f[0] += (self.wind * (0.6 + z) + math.sin(t * 1.7 + f[3]) * 0.8) * dt
            if f[1] >= H or (z > 0.5 and f[1] >= H - 2):
                f[:] = self.new_flake()
            f[0] %= W

        if self.sparks_on:
            rate = self.fire_lvl * 9 * dt
            while rate > 0:
                if r.random() < rate:
                    self.sparks.append([
                        self.W / 2 + r.uniform(-1, 1) * self.fire.w * 0.25,
                        self.fire_base - self.fire.h * 0.5,
                        self.wind * 0.8 + r.uniform(-1.5, 1.5),
                        -r.uniform(4, 10), r.uniform(0.8, 2.2)])
                rate -= 1
        alive = []
        for s in self.sparks:
            s[0] += (s[2] + math.sin(t * 9 + s[4] * 7) * 1.5) * dt
            s[1] += s[3] * dt
            s[3] *= 1 - 0.4 * dt
            s[4] -= dt
            if s[4] > 0 and s[1] > 0:
                alive.append(s)
        self.sparks = alive

        for fl in self.flies:
            fl[2] += dt * fl[3]
            fl[0] = (fl[0] + math.cos(fl[2] * 1.3) * 2.2 * dt + self.wind * 0.1 * dt) % W
            fl[1] += math.sin(fl[2] * 0.9) * 1.1 * dt
            fl[1] = max(self.horizon - 6, min(H - 3, fl[1]))

    # ------------------------------------------------ rendering
    def render(self):
        W, H, t = self.W, self.H, self.t
        ch = [[" "] * W for _ in range(H)]
        co = [[16] * W for _ in range(H)]

        gx, gy = self.glow_c
        gr = self.glow_r * (0.6 + 0.25 * self.fire_lvl)
        flick = 0.85 + 0.1 * math.sin(t * 13.1) * math.sin(t * 7.3) + 0.25 * self.fire.heat_sum()
        glow_on = self.glow_on and self.fire_lvl > 0.05

        def put(x, y, c, col, glow=True):
            if 0 <= x < W and 0 <= y < H:
                if glow and glow_on:
                    dx, dy = (x - gx) * 0.5, y - gy
                    d = math.sqrt(dx * dx + dy * dy)
                    i = (1 - d / gr) * flick
                    if i > 0.12:
                        col = GLOW_RAMP[min(len(GLOW_RAMP) - 1, int((i - 0.12) * 1.25 * len(GLOW_RAMP)))]
                ch[y][x] = c
                co[y][x] = col

        # stars
        for x, y, ph, sp in self.stars:
            b = math.sin(t * sp + ph)
            if b > 0.75:
                put(x, y, "*", 255, False)
            elif b > 0.1:
                put(x, y, "+" if b > 0.5 else ".", 250, False)
            elif b > -0.5:
                put(x, y, ".", 241, False)

        # moon
        if self.moon_on:
            mx, my, mr = self.moon
            for dy in range(-mr - 2, mr + 3):
                for dx in range(-2 * mr - 4, 2 * mr + 5):
                    d = math.hypot(dx / 2, dy)
                    if d <= mr:
                        hh = h32(dx, dy, 7) % 100
                        if hh < 18:
                            put(mx + dx, my + dy, "o", 187, False)
                        else:
                            put(mx + dx, my + dy, "@" if d < mr - 0.6 else "O", 230, False)
                    elif d <= mr + 1.8 and h32(dx, dy, int(t * 1.5)) % 5 == 0:
                        put(mx + dx, my + dy, ".", 243 if d < mr + 1 else 239, False)

        self.draw_trees("back", put)

        # ground
        gh = max(1, H - self.horizon)
        for y in range(self.horizon, H):
            k = (y - self.horizon) / gh
            base = 236 + int(k * 6)
            dens = 0.25 + 0.7 * k
            for x in range(W):
                if ch[y][x] != " ":
                    continue
                hv = h32(x // 3 if k > 0.5 else x, y, 3)
                if (hv % 1000) / 1000 < dens:
                    c = "-_=~.,'"[hv % (3 if k > 0.4 else 7)]
                    put(x, y, c, base)

        self.draw_trees("mid", put)
        self.draw_trees("front", put)

        # logs
        fx0, fb, fw = self.fire_x0, self.fire_base, self.fire.w
        logs = ["\\" + "=" * (fw - 2) + "/", " " + "/\\" * ((fw - 2) // 2) + " "]
        for i, row in enumerate(logs):
            for j, c in enumerate(row):
                if c != " ":
                    put(fx0 + j, fb + 1 + i, c, 94 if (j + i) % 3 else 130, False)

        # fire
        n = len(FIRE_CHARS) - 1
        for fy in range(self.fire.h):
            row = self.fire.g[fy]
            y = fb - self.fire.h + 1 + fy
            for fx in range(fw):
                v = row[fx]
                if v > 0.06:
                    put(fx0 + fx, y, FIRE_CHARS[min(n, 1 + int(v * n))],
                        FIRE_RAMP[min(len(FIRE_RAMP) - 1, int(v * len(FIRE_RAMP)))], False)

        # sparks
        for x, y, _, _, life in self.sparks:
            c = SPARK_RAMP[min(len(SPARK_RAMP) - 1, int(life / 2.2 * len(SPARK_RAMP)))]
            put(int(x), int(y), "'" if life > 1.2 else ".", c, False)

        # fireflies
        if self.flies_on:
            for x, y, ph, _ in self.flies:
                b = math.sin(t * 2.3 + ph * 3)
                if b > 0.2:
                    put(int(x), int(y), "*" if b > 0.7 else ".", 190 if b > 0.7 else 106, False)

        # snow (on top of everything)
        for x, y, z, _ in self.flakes:
            c = "." if z < 0.4 else ("+" if z < 0.75 else "*")
            put(int(x), int(y), c, 244 + int(z * 11), False)

        return ch, co

    def draw_trees(self, layer, put):
        body, edge, snowc, trunkc, fill, sparse, amp = LAYERS[layer]
        t = self.t
        gust = 0.6 + 0.22 * abs(self.wind) + 0.25 * math.sin(t * 0.37)
        for tr in self.trees[layer]:
            top = tr.base - tr.h
            sway = amp * gust * math.sin(t * tr.freq + tr.phase)
            lean = self.wind * 0.35 * (amp / 2)
            for r in range(tr.h):
                y = top + r
                k = (1 - r / tr.h) ** 1.4
                off = int(round((sway + lean) * k))
                hw = int(tr.slope * (0.42 * r + 0.75 * (r % 4)))
                cx = tr.x + off
                for i in range(-hw, hw + 1):
                    hv = h32(tr.seed, r, i)
                    if r == 0:
                        c, col = ("A" if layer != "back" else "^"), edge
                    elif i == -hw:
                        c, col = "/", edge
                    elif i == hw:
                        c, col = "\\", edge
                    elif r % 4 == 0 and hv % 10 < 7 or hv % 13 == 0:
                        c, col = ("*" if hv % 3 else "="), snowc
                    elif (hv % 1000) / 1000 < sparse:
                        continue
                    else:
                        c, col = fill[hv % len(fill)], body
                    put(cx + i, y, c, col)
            for r in range(max(1, tr.h // 9)):
                tw = 1 if layer == "back" else 2
                for i in range(tw):
                    put(tr.x - tw // 2 + i, tr.base + r, "|" if tw == 1 else "H", trunkc)

    def status(self, fps):
        on = lambda b: "on" if b else "off"
        return (f" WINTER NIGHT | speed {self.speed:.2f} | wind {self.wind:+.1f} | "
                f"snow {self.snow:.1f} | fire {self.fire_lvl:.1f} | sparks {on(self.sparks_on)} | "
                f"flies {on(self.flies_on)} | glow {on(self.glow_on)} | moon {on(self.moon_on)} | "
                f"{fps:.0f} fps | [H]elp ")


HELP = [
    "  WINTER NIGHT - controls  ",
    "",
    "  q / Esc      quit",
    "  space        pause",
    "  + / -        speed",
    "  <- / ->      wind   (a / d)",
    "  up / down    snow   (w / s)",
    "  [ / ]        fire",
    "  g            glow on/off",
    "  m            moon on/off",
    "  p            sparks on/off",
    "  l            fireflies on/off",
    "  h            close help",
]


# ---------------------------------------------------------------- terminal
class Colors:
    BASIC = [(0, 0, 0), (128, 0, 0), (0, 128, 0), (128, 128, 0), (0, 0, 128), (128, 0, 128),
             (0, 128, 128), (192, 192, 192), (128, 128, 128), (255, 0, 0), (0, 255, 0),
             (255, 255, 0), (0, 0, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255)]

    def __init__(self):
        curses.start_color()
        self.rich = curses.COLORS >= 256
        self.bg = 16 if self.rich else curses.COLOR_BLACK
        self.cache, self.next = {}, 1

    @staticmethod
    def rgb(i):
        if i < 16:
            return Colors.BASIC[i]
        if i < 232:
            i -= 16
            lv = [0, 95, 135, 175, 215, 255]
            return lv[i // 36], lv[(i // 6) % 6], lv[i % 6]
        v = 8 + (i - 232) * 10
        return v, v, v

    def attr(self, c):
        a = self.cache.get(c)
        if a is not None:
            return a
        fg, bold = c, 0
        if not self.rich:
            r, g, b = self.rgb(c)
            best = min(range(16), key=lambda k: sum((p - q) ** 2 for p, q in zip(self.BASIC[k], (r, g, b))))
            fg, bold = best % 8, (curses.A_BOLD if best >= 8 else 0)
        if self.next >= curses.COLOR_PAIRS:
            a = 0
        else:
            curses.init_pair(self.next, fg, self.bg)
            a = curses.color_pair(self.next) | bold
            self.next += 1
        self.cache[c] = a
        return a


def run(stdscr, args):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.keypad(True)
    colors = Colors()
    stdscr.bkgd(" ", colors.attr(16))

    def make():
        Hh, Ww = stdscr.getmaxyx()
        return Scene(Ww, max(5, Hh - 1), args.seed)

    scene = make()
    paused, show_help = False, False
    frame_t = 1.0 / args.fps
    last = time.time()
    fps = float(args.fps)

    while True:
        # ---------------- input
        key = stdscr.getch()
        while key != -1:
            if key in (ord("q"), ord("Q"), 27):
                return
            elif key == curses.KEY_RESIZE:
                old = scene
                scene = make()
                for a in ("speed", "wind", "snow", "fire_lvl", "glow_on", "moon_on", "sparks_on", "flies_on"):
                    setattr(scene, a, getattr(old, a))
                scene.adjust_snow()
                stdscr.clear()
            elif key == ord(" "):
                paused = not paused
            elif key in (ord("+"), ord("=")):
                scene.speed = min(4.0, scene.speed + 0.25)
            elif key in (ord("-"), ord("_")):
                scene.speed = max(0.25, scene.speed - 0.25)
            elif key in (curses.KEY_RIGHT, ord("d")):
                scene.wind = min(6.0, scene.wind + 0.4)
            elif key in (curses.KEY_LEFT, ord("a")):
                scene.wind = max(-6.0, scene.wind - 0.4)
            elif key in (curses.KEY_UP, ord("w")):
                scene.snow = min(5.0, scene.snow + 0.2); scene.adjust_snow()
            elif key in (curses.KEY_DOWN, ord("s")):
                scene.snow = max(0.0, scene.snow - 0.2); scene.adjust_snow()
            elif key == ord("]"):
                scene.fire_lvl = min(3.0, scene.fire_lvl + 0.1)
            elif key == ord("["):
                scene.fire_lvl = max(0.0, scene.fire_lvl - 0.1)
            elif key in (ord("g"), ord("G")):
                scene.glow_on = not scene.glow_on
            elif key in (ord("m"), ord("M")):
                scene.moon_on = not scene.moon_on
            elif key in (ord("p"), ord("P")):
                scene.sparks_on = not scene.sparks_on
            elif key in (ord("l"), ord("L")):
                scene.flies_on = not scene.flies_on
            elif key in (ord("h"), ord("H"), ord("?")):
                show_help = not show_help
            key = stdscr.getch()

        now = time.time()
        dt = min(0.1, now - last)
        last = now
        fps = fps * 0.9 + (1 / max(dt, 1e-3)) * 0.1
        if not paused:
            scene.update(dt)

        # ---------------- draw
        ch, co = scene.render()
        W = scene.W
        for y in range(scene.H):
            row_c, row_k = ch[y], co[y]
            x = 0
            while x < W:
                col = row_k[x] if row_c[x] != " " else 16
                x2 = x + 1
                while x2 < W and (row_k[x2] if row_c[x2] != " " else 16) == col:
                    x2 += 1
                try:
                    stdscr.addstr(y, x, "".join(row_c[x:x2]), colors.attr(col))
                except curses.error:
                    pass
                x = x2
        st = scene.status(fps) + ("| PAUSED " if paused else "")
        try:
            stdscr.addstr(scene.H, 0, st[:W - 1].ljust(W - 1), colors.attr(250) | curses.A_REVERSE)
        except curses.error:
            pass
        if show_help:
            bw = max(len(s) for s in HELP) + 2
            by, bx = max(0, scene.H // 2 - len(HELP) // 2), max(0, W // 2 - bw // 2)
            for i, s in enumerate(HELP):
                try:
                    stdscr.addstr(by + i, bx, s.ljust(bw)[:W - bx], colors.attr(223) | curses.A_REVERSE)
                except curses.error:
                    pass
        stdscr.refresh()

        spent = time.time() - now
        if spent < frame_t:
            time.sleep(frame_t - spent)


def preview(args):
    size = shutil.get_terminal_size((120, 40))
    W = args.width or size.columns
    H = (args.height or size.lines) - 1
    scene = Scene(W, H, args.seed)
    for _ in range(int(args.fps * 3)):
        scene.update(1 / args.fps)
    ch, co = scene.render()
    out = []
    for y in range(H):
        line, cur = ["\x1b[48;5;16m"], None
        for x in range(W):
            if co[y][x] != cur:
                cur = co[y][x]
                line.append(f"\x1b[38;5;{cur}m")
            line.append(ch[y][x])
        out.append("".join(line) + "\x1b[0m")
    out.append("\x1b[7m" + scene.status(args.fps)[:W] + "\x1b[0m")
    print("\n".join(out))


def main():
    ap = argparse.ArgumentParser(description="Animated ASCII winter night with a campfire.")
    ap.add_argument("--fps", type=int, default=25, help="target frames per second (default 25)")
    ap.add_argument("--seed", type=int, default=None, help="random seed for the forest layout")
    ap.add_argument("--preview", action="store_true", help="print one colored frame and exit")
    ap.add_argument("--width", type=int, default=0, help="preview width")
    ap.add_argument("--height", type=int, default=0, help="preview height")
    args = ap.parse_args()
    if args.preview:
        preview(args)
        return
    if not sys.stdout.isatty():
        sys.exit("Run me in a real terminal (or use --preview).")
    try:
        curses.wrapper(run, args)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
