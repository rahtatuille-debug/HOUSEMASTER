"""Student photos: checked, squared and shrunk on upload, stored in the database."""
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError
from rest_framework.exceptions import ValidationError

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
SIZE = 400  # pixels, square
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
# Checked from the file's header before decoding: a small PNG can claim 9,000 x 9,000 pixels and take
# hundreds of MB to decode. Phone cameras make 12 to 50 megapixels. JPEGs are decoded at a fraction of
# their size (draft mode), so they can be larger.
MAX_PIXELS = 50_000_000
MAX_JPEG_PIXELS = 250_000_000


def process_photo(uploaded_file):
    """Return JPEG bytes for a square, SIZE x SIZE version of the upload."""
    if uploaded_file.size > MAX_UPLOAD_BYTES:
        raise ValidationError({"photo": "The photo must be smaller than 8 MB."})
    try:
        image = Image.open(uploaded_file)
        image_format = image.format
        width, height = image.size
        if width * height > (MAX_JPEG_PIXELS if image_format == "JPEG" else MAX_PIXELS):
            raise ValidationError({"photo": "That photo is too large. Upload one under 50 megapixels."})
        if image_format == "JPEG":
            image.draft("RGB", (SIZE * 2, SIZE * 2))
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
