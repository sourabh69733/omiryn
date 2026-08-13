from __future__ import annotations

from io import BytesIO
import warnings

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError


_SUPPORTED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}
_MAX_IMAGE_PIXELS = 20_000_000
_MAX_IMAGE_DIMENSION = 2_048
_JPEG_QUALITY = 88


def sanitize_profile_photo(content: bytes) -> bytes:
    """Decode an image and emit a metadata-free, size-bounded JPEG."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as candidate:
                image_format = candidate.format
                candidate.verify()

            if image_format not in _SUPPORTED_IMAGE_FORMATS:
                raise ValueError("unsupported image format")

            with Image.open(BytesIO(content)) as candidate:
                if candidate.width * candidate.height > _MAX_IMAGE_PIXELS:
                    raise ValueError("image has too many pixels")
                candidate.load()
                normalized = ImageOps.exif_transpose(candidate).convert("RGB")
    except (Image.DecompressionBombError, Image.DecompressionBombWarning, UnidentifiedImageError, OSError, ValueError):
        raise HTTPException(
            status_code=415,
            detail="Upload a valid JPG, PNG, WebP, or GIF image.",
        ) from None

    normalized.thumbnail(
        (_MAX_IMAGE_DIMENSION, _MAX_IMAGE_DIMENSION),
        Image.Resampling.LANCZOS,
    )
    output = BytesIO()
    normalized.save(output, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
    return output.getvalue()
