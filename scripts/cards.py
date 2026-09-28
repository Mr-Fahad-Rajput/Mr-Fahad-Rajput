"""Render the profile cards in the faadii.com style (paper neobrutalism).

Run by .github/workflows/cards.yml every day. Writes PNGs (light and dark) into cards/.
Content lives in scripts/cards.json; edit that, not this file.

Environment:
  GH_USER      GitHub username (default: from cards.json)
  CARDS_TOKEN  optional token; when set, the languages card also counts private repos
  GITHUB_TOKEN used for public API calls when CARDS_TOKEN is not set
  OFFLINE=1    skip network calls (languages and badges use fixtures, for local testing)
"""
import datetime as dt
import io
import json
import math
import os
import pathlib
import textwrap

from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
FONTS = ROOT / "scripts" / "fonts"
OUT = ROOT / "cards"
DATA = json.loads((ROOT / "scripts" / "cards.json").read_text())
OFFLINE = os.environ.get("OFFLINE") == "1"
TODAY = dt.date.today()

S = 2  # render at 2x for sharp text
THEMES = {
    "light": dict(bg="#F7EFDD", surface="#FFFBF2", sunk="#EFE6D3", line="#111111", shadow="#111111",
                  text="#111111", muted="#4A4538", faint="#6E6756"),
    "dark": dict(bg="#121316", surface="#1E1F25", sunk="#26272E", line="#F3E9D6", shadow="#F3E9D6",
                 text="#F3E9D6", muted="#B9B2A3", faint="#8C8677"),
}
ACCENT, LILAC, MINT, CORAL, INK, PAPER = "#FACC15", "#B7B0F6", "#A8E6C5", "#FF9DA7", "#111111", "#FFFBF2"
PASTELS = [LILAC, MINT, CORAL]


# ---------------------------------------------------------------- helpers

def font(name, size, wght=None, wdth=None):
    f = ImageFont.truetype(str(FONTS / f"{name}.ttf"), int(size * S))
    if name == "Archivo":
        f.set_variation_by_axes([wght or 700, wdth or 100])
    elif name == "Plex":
        f.set_variation_by_axes([wght or 400, wdth or 100])
    else:
        f.set_variation_by_axes([wght or 500])
    return f


def px(v):
    return int(v * S)


def canvas(w, h):
    im = Image.new("RGBA", (px(w), px(h)), (0, 0, 0, 0))
    return im, ImageDraw.Draw(im)


def card(d, box, fill, t, r=16, bw=3, sh=5):
    x0, y0, x1, y1 = [px(v) for v in box]
    if sh:
        d.rounded_rectangle((x0 + px(sh), y0 + px(sh), x1 + px(sh), y1 + px(sh)), px(r), fill=t["shadow"])
    d.rounded_rectangle((x0, y0, x1, y1), px(r), fill=fill, outline=t["line"], width=px(bw))


def text(d, xy, s, f, fill, spacing=0.0):
    x, y = px(xy[0]), px(xy[1])
    if not spacing:
        d.text((x, y), s, font=f, fill=fill)
        return xy[0] + d.textlength(s, font=f) / S
    for ch in s:
        d.text((x, y), ch, font=f, fill=fill)
        x += d.textlength(ch, font=f) + px(spacing)
    return (x - px(spacing)) / S


def width(d, s, f, spacing=0.0):
    return d.textlength(s, font=f) / S + spacing * max(len(s) - 1, 0)


def wrap(d, s, f, max_w):
    words, lines, cur = s.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if width(d, trial, f) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def pill(d, x, y, label, fill, t, f=None, dot=False, outline=None):
    f = f or font("JBMono", 9.5, 700)
    w = width(d, label, f, 1.2) + 22 + (12 if dot else 0)
    d.rounded_rectangle((px(x), px(y), px(x + w), px(y + 22)), px(11), fill=fill,
                        outline=outline or t["line"], width=px(2))
    tx = x + 11
    if dot:
        d.ellipse((px(tx), px(y + 7.5), px(tx + 7), px(y + 14.5)), fill=INK)
        tx += 12
    text(d, (tx, y + 4.5), label, f, INK, 1.2)
    return w


def check(d, x, y, size, fill):
    d.line([(px(x), px(y + size * 0.55)), (px(x + size * 0.38), px(y + size * 0.9)),
            (px(x + size), px(y + size * 0.1))], fill=fill, width=px(2.2), joint="curve")


def save(im, name, theme):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}-{theme}.png"
    im.save(path, optimize=True)
    return path


def months_between(start, end):
    return (end.year - start.year) * 12 + (end.month - start.month)


def month_name(ym):
    y, m = map(int, ym.split("-"))
    return dt.date(y, m, 1).strftime("%b %Y")


# ---------------------------------------------------------------- network

def gh_get(url):
    import requests
    token = os.environ.get("CARDS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r


def fetch_languages(user):
    if OFFLINE:
        return {"HTML": 4930, "JavaScript": 4170, "CSS": 500, "Less": 370, "Markdown": 900,
                "Python": 20, "Dockerfile": 2}, 4, False
    private = bool(os.environ.get("CARDS_TOKEN"))
    base = ("https://api.github.com/user/repos?affiliation=owner,collaborator,organization_member"
            if private else f"https://api.github.com/users/{user}/repos?type=owner")
    repos, page = [], 1
    while True:
        batch = gh_get(f"{base}&per_page=100&page={page}").json()
        repos += batch
        if len(batch) < 100:
            break
        page += 1
    cfg = DATA["languages"]
    skip = set(cfg.get("exclude_repos", []))
    md_exts = tuple(cfg.get("markdown_extensions", [".md", ".mdx", ".markdown"]))
    totals, counted = {}, 0
    for repo in repos:
        if repo.get("fork") or repo["name"] in skip:
            continue
        langs = gh_get(repo["languages_url"]).json()
        # GitHub's language stats leave out prose (Markdown), so count it from the file tree
        if cfg.get("include_markdown") and repo.get("default_branch"):
            try:
                tree = gh_get(f"{repo['url']}/git/trees/{repo['default_branch']}?recursive=1").json()
                md = sum(e.get("size", 0) for e in tree.get("tree", [])
                         if e.get("type") == "blob" and e["path"].lower().endswith(md_exts))
                if md:
                    langs["Markdown"] = langs.get("Markdown", 0) + md
            except Exception as e:  # empty repos return 409; skip them
                print(f"tree skipped for {repo['name']}: {e}")
        if langs:
            counted += 1
        for k, v in langs.items():
            totals[k] = totals.get(k, 0) + v
    for k in DATA["languages"].get("exclude_languages", []):
        totals.pop(k, None)
    return totals, counted, private


def fetch_image(url, fallback_color):
    if not OFFLINE:
        import requests
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            return Image.open(io.BytesIO(r.content)).convert("RGBA")
        except Exception as e:  # keep the previous tile rather than publishing a placeholder
            print(f"badge fetch failed, keeping the previous tile: {url}: {e}")
            return None
    im = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse((10, 10, 190, 190), fill=fallback_color, outline=INK, width=6)
    return im


# ---------------------------------------------------------------- cards

def status_card(theme):
    t, cfg = THEMES[theme], DATA["status"]
    rows = cfg["components"]
    W, row_h, top = 880, 58, 96
    H = top + row_h * len(rows) + 58
    im, d = canvas(W, H)
    card(d, (4, 4, W - 10, H - 10), t["surface"], t)
    x0 = 32
    text(d, (x0, 28), cfg["eyebrow"], font("JBMono", 10, 600), t["faint"], 2)
    text(d, (x0, 46), cfg["title"], font("Archivo", 24, 900, 110), t["text"])
    label = "ALL SYSTEMS OPERATIONAL"
    lf = font("JBMono", 9.5, 700)
    pw = width(d, label, lf, 1.2) + 34
    pill(d, W - 42 - pw, 48, label, MINT, t, lf, dot=True)

    n = cfg.get("months", 24)
    bar_w, gap = 9, 3
    bars_x = 400
    end = dt.date(TODAY.year, TODAY.month, 1)
    for i, row in enumerate(rows):
        y = top + i * row_h
        d.line((px(x0), px(y), px(W - 42), px(y)), fill=t["sunk"] if theme == "light" else t["sunk"], width=px(2))
        text(d, (x0, y + 11), row["name"], font("Archivo", 15, 800), t["text"])
        text(d, (x0, y + 32), row["detail"], font("Plex", 12, 400), t["muted"])
        since = row.get("since")
        if since:
            sy, sm = map(int, since.split("-"))
            start = dt.date(sy, sm, 1)
            for b in range(n):
                month_index = n - 1 - b  # months before now
                mdate = end.year * 12 + end.month - 1 - month_index
                active = mdate >= start.year * 12 + start.month - 1
                bx = bars_x + b * (bar_w + gap)
                d.rounded_rectangle((px(bx), px(y + 14), px(bx + bar_w), px(y + 42)), px(2.5),
                                    fill=MINT if active else t["sunk"],
                                    outline=t["line"] if active else t["sunk"], width=px(1.5))
            right = f"since {month_name(since)}" if not row.get("since_label") else row["since_label"]
        else:
            right = row.get("state", "")
            pill(d, bars_x, y + 17, row.get("badge", "OPEN"), ACCENT, t)
        rf = font("JBMono", 10.5, 600)
        text(d, (W - 42 - width(d, right, rf), y + 22), right, rf, t["muted"])
    fy = top + row_h * len(rows) + 14
    d.line((px(x0), px(fy - 14), px(W - 42), px(fy - 14)), fill=t["sunk"], width=px(2))
    text(d, (x0, fy), f"Bars: the last {n} months, one per month · updated daily", font("JBMono", 9.5, 500), t["faint"], 0.6)
    return im


def incidents_card(theme):
    t, cfg = THEMES[theme], DATA["incidents"]
    W, x0, inner = 880, 32, 880 - 32 - 52
    tmp, dtmp = canvas(W, 10)
    sf, tf = font("Plex", 13, 400), font("Archivo", 16, 800)
    blocks = []
    for inc in cfg["items"]:
        lines = wrap(dtmp, inc["summary"], sf, inner - 150)
        blocks.append((inc, lines, 30 + 22 + 19 * len(lines) + 22))
    H = 96 + sum(b[2] for b in blocks) + 44
    im, d = canvas(W, H)
    card(d, (4, 4, W - 10, H - 10), t["surface"], t)
    text(d, (x0, 28), cfg["eyebrow"], font("JBMono", 10, 600), t["faint"], 2)
    text(d, (x0, 46), cfg["title"], font("Archivo", 24, 900, 110), t["text"])
    y = 96
    for inc, lines, h in blocks:
        d.line((px(x0), px(y), px(W - 42), px(y)), fill=t["sunk"], width=px(2))
        pub = dt.date.fromisoformat(inc["published"])
        done = pub <= TODAY
        idf = font("JBMono", 10.5, 700)
        text(d, (x0, y + 18), inc["id"], idf, t["faint"], 0.8)
        if done:
            pill(d, x0, y + 38, "RESOLVED", MINT, t)
        else:
            pill(d, x0, y + 38, "WRITING UP", LILAC, t)
        cx = x0 + 150
        text(d, (cx, y + 14), inc["title"], tf, t["text"])
        for j, ln in enumerate(lines):
            text(d, (cx, y + 40 + j * 19), ln, sf, t["muted"])
        foot = (f"Postmortem on faadii.com/blog" if done
                else f"Postmortem publishes {pub.strftime('%-d %b %Y')}")
        text(d, (cx, y + 44 + len(lines) * 19), foot, font("JBMono", 9.5, 600), t["faint"], 0.6)
        y += h
    d.line((px(x0), px(y), px(W - 42), px(y)), fill=t["sunk"], width=px(2))
    text(d, (x0, y + 14), cfg["footer"], font("JBMono", 9.5, 500), t["faint"], 0.6)
    return im


def languages_card(theme, langs, repos, private):
    t, cfg = THEMES[theme], DATA["languages"]
    total = sum(langs.values()) or 1
    min_pct = cfg.get("min_percent", 0.1)
    ranked = [kv for kv in sorted(langs.items(), key=lambda kv: -kv[1]) if 100 * kv[1] / total >= min_pct]
    top = ranked[: cfg.get("top", 8)]
    W, H = 430, 92 + 40 * len(top) + 62
    im, d = canvas(W, H)
    card(d, (4, 4, W - 10, H - 10), LILAC, t)
    x0 = 28
    text(d, (x0, 26), cfg["eyebrow"], font("JBMono", 9.5, 700), INK, 1.8)
    text(d, (x0, 44), cfg["title"], font("Archivo", 21, 900, 108), INK)
    y = 92
    nf, pf = font("Archivo", 13.5, 800), font("JBMono", 10.5, 700)
    bar_x, bar_w = x0, W - 10 - x0 - 28
    for name, v in top:
        pct = 100 * v / total
        text(d, (x0, y), name, nf, INK)
        label = f"{pct:.1f}%"
        text(d, (W - 38 - width(d, label, pf), y + 1), label, pf, INK)
        by = y + 21
        d.rounded_rectangle((px(bar_x), px(by), px(bar_x + bar_w), px(by + 11)), px(5.5), fill=PAPER,
                            outline=INK, width=px(2))
        fill_w = max(bar_w * pct / 100, 11)
        d.rounded_rectangle((px(bar_x), px(by), px(bar_x + fill_w), px(by + 11)), px(5.5), fill=INK)
        y += 40
    scope = "public and private repositories" if private else "public repositories"
    foot = f"Across {repos} {scope} · updated daily"
    text(d, (x0, H - 40), foot, font("JBMono", 9, 600), INK, 0.4)
    return im


def terminal_card(theme):
    """A fetch-style terminal: ASCII bolt on the left, machine facts on the right."""
    t, cfg = THEMES[theme], DATA["terminal"]
    W, H = 880, 440
    im, d = canvas(W, H)
    term_bg, fg, dim = "#121316", "#F3E9D6", "#8C8677"
    card(d, (4, 4, W - 10, H - 10), term_bg, t)
    # title bar
    d.line((px(6), px(40), px(W - 12), px(40)), fill=t["line"] if theme == "light" else "#3A3B44", width=px(3))
    for i, c in enumerate([CORAL, ACCENT, MINT]):
        cx = 28 + i * 20
        d.ellipse((px(cx - 6), px(22 - 6), px(cx + 6), px(22 + 6)), fill=c, outline=INK, width=px(1.5))
    tf = font("JBMono", 10.5, 600)
    title = f"{cfg['prompt']}: ~"
    text(d, (W / 2 - width(d, title, tf) / 2, 15), title, tf, dim)
    mf, mb = font("JBMono", 13, 500), font("JBMono", 13, 800)
    y = 62
    x = text(d, (28, y), cfg["prompt"], mb, MINT)
    x = text(d, (x, y), ":~$ ", mb, fg)
    text(d, (x, y), cfg["command"], mf, fg)
    # ASCII bolt
    art = [
        "        ▄████▀",
        "      ▄████▀",
        "    ▄████▀",
        "  ▄██████████▀",
        "      ▄████▀",
        "    ▄███▀",
        "   ▄█▀",
    ]
    af = font("JBMono", 17, 800)
    bb = d.textbbox((0, 0), "█", font=af)
    step = (bb[3] - bb[1]) / S
    top = 128 + (9 * 24 - step * len(art)) / 2
    for i, ln in enumerate(art):
        text(d, (40, top + i * step - bb[1] / S), ln, af, ACCENT)
    # facts
    fx = 330
    years = TODAY.year - int(cfg["uptime_since"])
    head = cfg["prompt"]
    text(d, (fx, 100), head, mb, ACCENT)
    text(d, (fx, 120), "─" * len(head), mf, dim)
    rows = [("Uptime", f"{years} years (since {cfg['uptime_since']})")] + [tuple(r) for r in cfg["rows"]]
    y = 146
    for k, v in rows:
        x = text(d, (fx, y), k, mb, MINT)
        text(d, (fx + 92, y), v, mf, fg)
        y += 24
    # palette strip, like the fetch tools print
    for i, c in enumerate([INK, CORAL, ACCENT, MINT, LILAC, "#F3E9D6"]):
        bx = fx + i * 34
        d.rectangle((px(bx), px(y + 12), px(bx + 28), px(y + 28)), fill=c,
                    outline="#3A3B44" if c == INK else None, width=px(1))
    return im


def cert_tile(theme, cert, i, badge):
    t = THEMES[theme]
    W, H = 200, 236
    im, d = canvas(W, H)
    fill = PASTELS[i % len(PASTELS)]
    card(d, (4, 4, W - 10, H - 10), fill, t)
    b = badge.copy()
    b.thumbnail((px(112), px(112)), Image.LANCZOS)
    im.alpha_composite(b, (int((px(W - 6) - b.width) / 2), px(20)))
    tf = font("Archivo", 11.5, 800)
    lines = wrap(d, cert["title"], tf, W - 40)[:3]
    y = 144
    for ln in lines:
        text(d, ((W - 6) / 2 - width(d, ln, tf) / 2, y), ln, tf, INK)
        y += 15
    vf = font("JBMono", 8.5, 700)
    v = "VERIFY ON CREDLY ↗"
    text(d, ((W - 6) / 2 - width(d, v, vf, 0.8) / 2, H - 38), v, vf, INK, 0.8)
    return im


def slug(s):
    import re
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


# ---------------------------------------------------------------- main

def main():
    user = os.environ.get("GH_USER") or DATA["user"]
    try:
        langs, repos, private = fetch_languages(user)
    except Exception as e:
        print(f"languages fetch failed, keeping the previous card: {e}")
        langs = None
    badges = [fetch_image(c["image"], PASTELS[i % 3]) for i, c in enumerate(DATA["certs"])]
    for theme in THEMES:
        save(status_card(theme), "status", theme)
        save(incidents_card(theme), "incidents", theme)
        save(terminal_card(theme), "terminal", theme)
        if langs:
            save(languages_card(theme, langs, repos, private), "languages", theme)
        for i, (c, b) in enumerate(zip(DATA["certs"], badges)):
            if b is None:
                continue
            (OUT / "certs").mkdir(parents=True, exist_ok=True)
            cert_tile(theme, c, i, b).save(OUT / "certs" / f"{slug(c['title'])}-{theme}.png", optimize=True)
    print("cards written to", OUT)


if __name__ == "__main__":
    main()
