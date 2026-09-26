"""Student photos: checked, squared and shrunk on upload, stored in the database."""
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError
from rest_framework.exceptions import ValidationError

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
SIZE = 400  # pixels, square
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


def process_photo(uploaded_file):
    """Return JPEG bytes for a square, SIZE x SIZE version of the upload."""
    if uploaded_file.size > MAX_UPLOAD_BYTES:
        raise ValidationError({"photo": "The photo must be smaller than 8 MB."})
    try:
        image = Image.open(uploaded_file)
        image_format = image.format
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValidationError({"photo": "That file isn't a photo HouseMaster can read."})
    if image_format not in ALLOWED_FORMATS:
        raise ValidationError({"photo": "Upload a JPEG, PNG or WebP photo."})
    # Phones store rotation separately; apply it so the photo isn't sideways.
    image = ImageOps.exif_transpose(image).convert("RGB")
    image = ImageOps.fit(image, (SIZE, SIZE), Image.LANCZOS)
    out = BytesIO()
    # Re-encoding drops all metadata (e.g. GPS location in phone photos).
    image.save(out, format="JPEG", quality=85, optimize=True)
    return out.getvalue()
