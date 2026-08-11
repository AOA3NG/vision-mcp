"""Build the Windows icon from the approved warm Vision/X artwork."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageOps


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "design" / "vision-mcp-icon-source.png"
OUTPUT = ROOT / "packaging" / "vision-mcp.ico"
PREVIEW = ROOT / "design" / "vision-mcp-icon.png"
CANVAS = 1024


def _content_box(image: Image.Image) -> tuple[int, int, int, int]:
    if image.mode == "RGBA" and image.getchannel("A").getextrema()[0] < 255:
        box = image.getchannel("A").point(lambda value: 255 if value > 3 else 0).getbbox()
        if box is None:
            raise ValueError("图标源文件没有可见内容")
        return box
    rgb = image.convert("RGB")
    background = Image.new("RGB", rgb.size, rgb.getpixel((0, 0)))
    difference = ImageChops.difference(rgb, background).convert("L")
    visible = difference.point(lambda value: 255 if value > 3 else 0)
    box = visible.getbbox()
    if box is None:
        raise ValueError("图标源文件没有可见内容")
    return box


def render() -> Image.Image:
    source = Image.open(SOURCE).convert("RGBA")
    cropped = source.crop(_content_box(source))
    side = max(cropped.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(cropped, ((side - cropped.width) // 2, (side - cropped.height) // 2))
    square = ImageOps.fit(square, (CANVAS, CANVAS), Image.Resampling.LANCZOS)

    if square.getchannel("A").getextrema()[0] < 255:
        return square

    # Fallback for an opaque source: mask the surrounding square so Windows
    # taskbars still receive a proper rounded transparent icon.
    alpha = Image.new("L", (CANVAS, CANVAS), 0)
    ImageDraw.Draw(alpha).rounded_rectangle(
        (4, 4, CANVAS - 5, CANVAS - 5), radius=round(CANVAS * 0.19), fill=255
    )
    result = square.copy()
    result.putalpha(alpha)
    return result


def main() -> None:
    image = render()
    PREVIEW.parent.mkdir(parents=True, exist_ok=True)
    image.resize((512, 512), Image.Resampling.LANCZOS).save(PREVIEW)
    image.save(
        OUTPUT,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )


if __name__ == "__main__":
    main()
