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
  , / .       fireflies
"""
import argparse
import curses
import math
import random
import shutil
import sys
import time

# ---------------------------------------------------------------- palettes
FIRE_RAMP = [52, 88, 130, 166, 202, 208, 214, 220, 226, 227, 228, 229, 230, 230]
FIRE_CHARS = " .:;+*xxXXX0OO@@ee"
GLOW_RAMP = [180, 186, 222, 221, 220, 214, 220, 226, 228, 229]
SPARK_RAMP = [88, 124, 160, 202, 208, 214, 220, 226]

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
    def __init__(self, x, base, height, depth, rng):
        self.x, self.base, self.h, self.d = x, base, height, depth
        self.phase = rng.random() * math.tau
        self.freq = rng.uniform(0.55, 1.05)
        self.slope = rng.uniform(0.85, 1.2)
        self.seed = rng.randrange(1 << 30)
        self.shade = rng.randrange(3)


class Fire:
    """Classic 'doom fire' heat propagation, shaped into a campfire cone."""

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.g = [[0.0] * w for _ in range(h)]

    def step(self, intensity, wind):
        w, h, g = self.w, self.h, self.g
        cx = (w - 1) / 2
        power = min(1.0, intensity / 1.2)
        for x in range(w):
            fall = max(0.0, 1 - (abs(x - cx) / (w / 2)) ** 2.2)
            g[h - 1][x] = min(1.0, fall * power * random.uniform(0.7, 1.15))
        decay = 1.15 / (h * max(0.35, min(1.6, intensity / 1.5)))
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
        self.speed, self.wind, self.snow, self.fire_lvl, self.flies_lvl = 1.0, 2.4, 1.6, 1.7, 2.0
        self.glow_on = self.moon_on = self.sparks_on = True
        self.build()

    # ------------------------------------------------ layout
    def build(self):
        W, H, rng = self.W, self.H, self.rng
        cx = W / 2
        self.horizon = int(H * 0.40)

        fw = max(11, min(34, W // 7))
        fh = max(7, int(H * 0.28))
        self.fire = Fire(fw, fh)
        self.fire_x0 = int(cx - fw / 2)
        self.fire_base = H - 2                     # bottom row of flames, embers under it
        self.glow_c = (cx, H - 4)
        self.glow_r = max(8.0, H * 0.42)

        # forest corridor: tiny trees far away in the middle, huge ones near the edges
        trees = []
        for _ in range(max(6, W // 8)):            # far band along the horizon
            trees.append(Tree(rng.uniform(W * .25, W * .75), self.horizon + rng.randint(-1, 2),
                              rng.randint(2, max(3, int(H * .09))), 0.05, rng))
        for side in (-1, 1):
            n = max(7, W // 11)
            for i in range(n):
                d = ((i + rng.random()) / n) ** 0.8   # 0 = far, 1 = near (evenly spread)
                base = int(self.horizon + (H * 0.80 - self.horizon) * d ** 1.25) + rng.randint(-1, 1)
                h = int(H * (0.10 + 0.62 * d ** 1.3) * rng.uniform(0.8, 1.15))
                gap = W * (0.04 + 0.30 * d ** 1.15)
                x = cx + side * (gap + rng.uniform(0, W * 0.16 * d + 3))
                trees.append(Tree(x, base, max(3, h), d, rng))
            for _ in range(1):                    # giants on the very edge
                x = (rng.uniform(-0.06, 0.08) * W) if side < 0 else (rng.uniform(0.92, 1.06) * W)
                trees.append(Tree(x, int(H * rng.uniform(0.82, 0.9)), int(H * rng.uniform(0.75, 0.9)), 1.0, rng))
        trees.sort(key=lambda tr: (tr.base, tr.d))
        self.trees = trees
        for tr in trees:
            tr.x = int(tr.x)

        self.stars = [(rng.randrange(W), rng.randrange(max(1, self.horizon)),
                       rng.random() * math.tau, rng.uniform(0.6, 3.0))
                      for _ in range(W * self.horizon // 40)]
        self.moon = (int(W * 0.94), max(3, int(H * 0.15)), 2)
        self.lanterns = [(int(cx - fw * 1.6), H - int(H * 0.22)), (int(cx + fw * 1.4), H - int(H * 0.24))]

        self.flakes, self.sparks, self.flies = [], [], []
        self.adjust_snow()
        self.adjust_flies()

    def adjust_snow(self):
        target = int(self.W * self.H * 0.045 * self.snow)
        while len(self.flakes) < target:
            self.flakes.append(self.new_flake(top=False))
        del self.flakes[target:]

    def adjust_flies(self):
        r = self.rng
        target = int(self.W / 22 * self.flies_lvl)
        while len(self.flies) < target:
            self.flies.append([r.uniform(0, self.W), r.uniform(self.horizon - 3, self.H - 3),
                               r.random() * math.tau, r.uniform(0.5, 1.5)])
        del self.flies[target:]

    def new_flake(self, top=True):
        r = self.rng
        z = r.random()
        return [r.uniform(0, self.W), -1.0 if top else r.uniform(0, self.H) ** 1.0, z, r.random() * math.tau]

    # ------------------------------------------------ simulation
    def update(self, dt):
        dt *= self.speed
        self.t += dt
        t, W, H, r = self.t, self.W, self.H, self.rng

        self._fire_acc = getattr(self, "_fire_acc", 0.0) + dt * 22
        while self._fire_acc >= 1:
            self._fire_acc -= 1
            self.fire.step(self.fire_lvl, self.wind * 0.3)

        for f in self.flakes:
            z = f[2]
            f[1] += (2.0 + z * 6.0) * dt
            f[0] += (self.wind * (0.6 + z) + math.sin(t * 1.7 + f[3]) * 0.8) * dt
            if f[1] >= H:
                f[:] = self.new_flake()
            f[0] %= W

        if self.sparks_on:
            rate = self.fire_lvl * 8 * dt
            while rate > 0:
                if r.random() < rate:
                    self.sparks.append([
                        W / 2 + r.uniform(-1, 1) * self.fire.w * 0.2,
                        self.fire_base - self.fire.h * 0.6,
                        self.wind * 0.6 + r.uniform(-1.5, 1.5),
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
            fl[1] = max(self.horizon - 4, min(H - 3, fl[1]))

    # ------------------------------------------------ rendering
    def render(self):
        W, H, t = self.W, self.H, self.t
        ch = [[" "] * W for _ in range(H)]
        co = [[16] * W for _ in range(H)]

        gx, gy = self.glow_c
        gr = self.glow_r * (0.55 + 0.25 * self.fire_lvl)
        flick = 0.85 + 0.1 * math.sin(t * 13.1) * math.sin(t * 7.3) + 0.2 * self.fire.heat_sum()
        glow_on = self.glow_on and self.fire_lvl > 0.05

        def put(x, y, c, col, glow=True):
            if 0 <= x < W and 0 <= y < H:
                if glow and glow_on:
                    dx, dy = (x - gx) * 0.45, y - gy
                    i = (1 - math.sqrt(dx * dx + dy * dy) / gr) * flick
                    if i > 0.3:
                        col = GLOW_RAMP[min(len(GLOW_RAMP) - 1, int((i - 0.3) * 1.6 * len(GLOW_RAMP)))]
                    elif i > 0.05 and (h32(x, y, 77) % 100) < i * 90:
                        col = 222                  # warm specks on far trees
                ch[y][x] = c
                co[y][x] = col

        # stars (most of the sky is snow anyway)
        for x, y, ph, sp in self.stars:
            b = math.sin(t * sp + ph)
            if b > 0.6:
                put(x, y, "*", 255, False)
            elif b > -0.2:
                put(x, y, ".", 247, False)

        # ground: long rows of dashes in perspective
        gh = max(1, H - self.horizon)
        for y in range(self.horizon, H):
            k = (y - self.horizon) / gh
            seg = 3 + int(k * k * 20)
            rowc = "'-'_'-="[h32(y, 11) % 7] if k > 0.35 else "-.,'"[h32(y, 12) % 4]
            shift = h32(y, 5) % 50
            col = 240 + int(k * 15)
            for x in range(W):
                hv = h32((x + shift) // seg, y, 9)
                if hv % 5 == 0 or (k < 0.35 and hv % 3):
                    continue
                put(x, y, rowc, col)

        self.draw_trees(put)

        # moon peeking in at the top right
        if self.moon_on:
            mx, my, mr = self.moon
            for dy in range(-mr, mr + 1):
                for dx in range(-2 * mr - 1, 2 * mr + 2):
                    d = math.hypot(dx / 2, dy)
                    if d <= mr + 0.3:
                        c = "0690O@"[h32(dx, dy, 5) % 6] if d < mr - 0.4 else "0"
                        put(mx + dx, my + dy, c, 230 if d < mr - 0.4 else 252, False)

        # lanterns on the sides of the path
        for lx, ly in self.lanterns:
            for j, row in enumerate(["[ ]", "[|]", " | "]):
                for i, c in enumerate(row):
                    if c != " ":
                        put(lx + i, ly + j, c, 250)

        # embers / logs under the fire
        fx0, fb, fw = self.fire_x0, self.fire_base, self.fire.w
        for j in range(-1, fw + 1):
            c = ",.o_"[h32(j, int(t * 6)) % 4]
            put(fx0 + j, fb + 1, c, (202, 166, 208, 130)[h32(j, int(t * 5)) % 4], False)

        # fire
        n = len(FIRE_CHARS) - 1
        for fy in range(self.fire.h):
            row = self.fire.g[fy]
            y = fb - self.fire.h + 1 + fy
            for fx in range(fw):
                v = row[fx]
                if v > 0.07:
                    put(fx0 + fx, y, FIRE_CHARS[min(n, 1 + int(v * n))],
                        FIRE_RAMP[min(len(FIRE_RAMP) - 1, int(v * len(FIRE_RAMP)))], False)

        # sparks
        for x, y, _, _, life in self.sparks:
            c = SPARK_RAMP[min(len(SPARK_RAMP) - 1, int(life / 2.2 * len(SPARK_RAMP)))]
            put(int(x), int(y), "'" if life > 1.2 else ".", c, False)

        # fireflies
        for x, y, ph, _ in self.flies:
            b = math.sin(t * 2.3 + ph * 3)
            if b > 0.1:
                put(int(x), int(y), "*" if b > 0.6 else "+", 226 if b > 0.6 else 184, False)

        # snow (on top of everything)
        for x, y, z, _ in self.flakes:
            c = "." if z < 0.2 else ("'" if z < 0.35 else "*")
            put(int(x), int(y), c, 247 + int(z * 8), False)

        return ch, co

    def draw_trees(self, put):
        t = self.t
        gust = 0.6 + 0.22 * abs(self.wind) + 0.25 * math.sin(t * 0.37)
        for tr in self.trees:
            d = tr.d
            if d < 0.25:
                greens, fill, snow_c, trunk_c = (59, 65), "^/\\'.", 250, 52
            elif d < 0.55:
                greens, fill, snow_c, trunk_c = (65, 66, 108), "/\\Am^#", 253, 94
            elif d < 0.9:
                greens, fill, snow_c, trunk_c = (108, 114, 151), "#mA%&#m", 255, 94
            else:
                greens, fill, snow_c, trunk_c = (108, 151, 157, 194), "#H%m&#Hm", 255, 130
            # every tree gets its own shade so neighbours don't blend together
            shift = (0, 1, -1)[tr.shade]
            pal = (59, 65, 66, 108, 114, 151, 157, 194)
            greens = tuple(pal[max(0, min(len(pal) - 1, pal.index(g) + shift))] for g in greens)
            edge_c = greens[-1]
            amp = 0.5 + 2.2 * d
            tier = max(3, tr.h // 5)
            top = tr.base - tr.h
            sway = amp * gust * math.sin(t * tr.freq + tr.phase)
            lean = self.wind * 0.3 * d
            for r in range(tr.h):
                y = top + r
                k = (1 - r / tr.h) ** 1.4
                off = int(round((sway + lean) * k))
                rr = r % tier
                hw = int(tr.slope * (0.40 * r + 0.8 * rr))
                cx = tr.x + off
                # dark outline so overlapping trees stay separate
                put(cx - hw - 1, y, " ", 16, False)
                put(cx + hw + 1, y, " ", 16, False)
                for i in range(-hw, hw + 1):
                    hv = h32(tr.seed, r, i)
                    edge = i == -hw or i == hw
                    if r == 0:
                        c, col = "A", snow_c                       # snowy tip
                    elif rr == 0 or (rr == 1 and edge):
                        # snow lying on top of each tier of branches
                        c = "/" if i == -hw else ("\\" if i == hw else "*~^_*"[hv % 5])
                        col = snow_c
                    elif edge:
                        c, col = ("/" if i < 0 else "\\"), edge_c
                    elif rr == tier - 1 and hv % 3 == 0:
                        c, col = "_", greens[0]                    # shadow under branches
                    elif hv % 29 == 0:
                        c, col = "*", snow_c                       # stray snow clumps
                    else:
                        c, col = fill[hv % len(fill)], greens[hv % len(greens)]
                    put(cx + i, y, c, col)
            tw = 1 if d < 0.4 else 3
            for r in range(max(1, min(4, tr.h // 8))):
                for j in range(tw):
                    c = "|" if tw == 1 else "|#|"[j]
                    put(tr.x - tw // 2 + j, tr.base + r, c, trunk_c)

    def status(self, fps):
        on = lambda b: "on" if b else "off"
        return (f" WINTER NIGHT | speed {self.speed:.2f} | wind {self.wind:.1f} | "
                f"snow {self.snow:.1f} | fire {self.fire_lvl:.1f} | flies {self.flies_lvl:.1f} | "
                f"glow {on(self.glow_on)} | moon {on(self.moon_on)} | {fps:.0f} fps | [H]elp ")


HELP = [
    "  WINTER NIGHT - controls  ",
    "",
    "  q / Esc      quit",
    "  space        pause",
    "  + / -        speed",
    "  <- / ->      wind   (a / d)",
    "  up / down    snow   (w / s)",
    "  [ / ]        fire",
    "  , / .        fireflies",
    "  g            glow on/off",
    "  m            moon on/off",
    "  p            sparks on/off",
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
                for a in ("speed", "wind", "snow", "fire_lvl", "flies_lvl", "glow_on", "moon_on", "sparks_on"):
                    setattr(scene, a, getattr(old, a))
                scene.adjust_snow()
                scene.adjust_flies()
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
            elif key in (ord("."), ord(">")):
                scene.flies_lvl = min(5.0, scene.flies_lvl + 0.5); scene.adjust_flies()
            elif key in (ord(","), ord("<")):
                scene.flies_lvl = max(0.0, scene.flies_lvl - 0.5); scene.adjust_flies()
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
            stdscr.addstr(scene.H, 0, st[:W - 1].ljust(W - 1), colors.attr(250))
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
    out.append("\x1b[38;5;250m" + scene.status(args.fps)[:W] + "\x1b[0m")
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
