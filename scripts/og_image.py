"""Draws the site's link preview (web/public/og.png, 1200x630): what a link shows on
Discord, X, YouTube or Reddit. Dusk colours and the site's fonts (web/src/index.css,
@fontsource). Rerun after changing the wording:

    .venv/bin/python scripts/og_image.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FONTS = ROOT / "web/node_modules/@fontsource"
OUT = ROOT / "web/public/og.png"

BG, SURFACE, BORDER = "#1d2028", "#252933", "#3a404e"
TEXT, MUTED, ACCENT = "#e8eaf0", "#a9afbd", "#e3ac72"

W, H = 1200, 630


def font(family: str, weight: int, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(
        str(FONTS / family / f"files/{family}-latin-{weight}-normal.woff"), size
    )


def main() -> None:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((48, 48, W - 48, H - 48), radius=28, fill=SURFACE, outline=BORDER, width=2)
    d.rectangle((48 + 2, 112, 56, 232), fill=ACCENT)  # the accent bar beside the title

    d.text((96, 104), "ExiledBroker", font=font("fraunces", 700, 104), fill=TEXT)
    d.text(
        (100, 250),
        "Path of Exile currency exchange, hour by hour",
        font=font("nunito-sans", 600, 40),
        fill=ACCENT,
    )
    body = font("nunito-sans", 400, 34)
    for i, line in enumerate(
        [
            "Price check: sell now or hold, from past league starts",
            "Market recap: loops and card turn-ins that paid this hour",
            "Launch market: what to buy on day 1, backtested",
        ]
    ):
        y = 340 + i * 58
        d.ellipse((104, y + 16, 116, y + 28), fill=ACCENT)
        d.text((136, y), line, font=body, fill=MUTED)
    d.text((96, H - 112), "exiledbroker.trade", font=font("nunito-sans", 600, 30), fill=TEXT)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, optimize=True)
    print(f"{OUT.relative_to(ROOT)}: {OUT.stat().st_size // 1024} kB")


if __name__ == "__main__":
    main()
