"""Your photo for the portfolio: checked, cropped square, shrunk and re-saved, so the page stays small and safe.

Re-saving drops everything except the pixels: camera details and GPS location (EXIF) never reach the published page.
"""

from __future__ import annotations

import base64
import io

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 8 * 1024 * 1024  # what we accept from the upload
MAX_PIXELS = 40_000_000  # refuses "decompression bombs": tiny files that expand to huge images
SIDE = 480  # pixels; sharp on a 2x screen at the size the page shows it
FORMATS = {"JPEG", "PNG", "WEBP"}


class PhotoError(ValueError):
    """A photo we cannot use, with a sentence the user can act on."""


def prepare_photo(data: bytes) -> bytes:
    """A square 480 x 480 JPEG of the photo's centre, without metadata."""
    if not data:
        raise PhotoError("The photo file is empty")
    if len(data) > MAX_BYTES:
        raise PhotoError("The photo is larger than 8 MB. Use a smaller one")
    try:
        with Image.open(io.BytesIO(data)) as probe:
            fmt, (w, h) = probe.format, probe.size
            if fmt not in FORMATS:
                raise PhotoError("Use a JPEG, PNG or WebP photo")
            if w * h > MAX_PIXELS:
                raise PhotoError("The photo has too many pixels. Use one under 40 megapixels")
            probe.load()
            img = ImageOps.exif_transpose(probe)  # phones store rotation in EXIF; apply it before EXIF is dropped
    except PhotoError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise PhotoError("This file could not be read as a photo") from exc
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        flat = Image.new("RGB", img.size, (255, 255, 255))
        flat.paste(img, mask=img.getchannel("A"))
        img = flat
    img = ImageOps.fit(img.convert("RGB"), (SIDE, SIDE), Image.Resampling.LANCZOS, centering=(0.5, 0.4))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=82, optimize=True, progressive=True)  # no exif= argument: nothing is copied over
    return out.getvalue()


def data_uri(jpeg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")
