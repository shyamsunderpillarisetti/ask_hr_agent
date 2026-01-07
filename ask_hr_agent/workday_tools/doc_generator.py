from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any
from io import BytesIO

import warnings
from jinja2 import Environment, StrictUndefined
try:
    # Silence docxcompose/pkg_resources deprecation noise during import
    warnings.filterwarnings(
        "ignore",
        category=UserWarning,
        module=r"docxcompose\.properties",
    )
    from docxtpl import DocxTemplate  # Optional, used for templated docs
    _HAS_DOXCTPL = True
except Exception:
    DocxTemplate = None  # type: ignore
    _HAS_DOXCTPL = False

try:
    from docxtpl import InlineImage  # type: ignore
    from docx.shared import Mm  # type: ignore
    _HAS_INLINE_IMAGE = True
except Exception:
    InlineImage = None  # type: ignore
    Mm = None  # type: ignore
    _HAS_INLINE_IMAGE = False


BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
TEMPLATES_DIR.mkdir(exist_ok=True)

# In-memory document cache: maps doc_key -> {"bytes": BytesIO, "filename": str}
_document_cache: Dict[str, Dict[str, Any]] = {}


def _sanitize_filename(name: str, preserve_spaces: bool = False) -> str:
    """Sanitize filename by removing only invalid filesystem characters.
    
    Args:
        name: Original filename
        preserve_spaces: If True, keep spaces; otherwise convert to underscores
    
    Returns:
        Sanitized filename
    """
    # Remove only invalid Windows filename characters: < > : " / \ | ? *
    invalid_chars = '<>:"/\\|?*'
    safe = "".join(c for c in name if c not in invalid_chars)
    safe = safe.strip()
    if not preserve_spaces:
        safe = safe.replace(" ", "_")
    return safe or f"document_{int(datetime.now().timestamp())}"


def generate_docx_from_template(template_name: str, context: Dict[str, Any], filename: Optional[str] = None) -> Dict[str, Any]:
    """Render a DOCX from a .docx template and store in memory.

    Args:
        template_name: Filename of the template inside templates/
        context: Dict of placeholders to values
        filename: Optional output filename

    Returns:
        Dict with keys: success, filename, download_key (for download route)
    """
    if not _HAS_DOXCTPL:
        raise RuntimeError("docxtpl is not installed. Please install 'docxtpl'.")

    tpl_path = TEMPLATES_DIR / template_name
    if not tpl_path.exists():
        raise FileNotFoundError(f"Template not found: {template_name}")

    # Use preserve_spaces=True for user-friendly filenames like "Employment Verification Letter - John Doe.docx"
    preserve_spaces = filename is not None and " - " in filename
    base_name = _sanitize_filename(filename or f"render_{Path(template_name).stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx", preserve_spaces=preserve_spaces)
    if not base_name.lower().endswith(".docx"):
        base_name += ".docx"

    env = Environment(undefined=StrictUndefined, autoescape=False)
    tpl = DocxTemplate(str(tpl_path))

    # Attach header image if requested (after tpl is created so InlineImage binds correctly)
    if _HAS_INLINE_IMAGE:
        image_specs = [
            {
                "filenames": ["hr_header_image", "Header", "hr_header"],
                "width_key": "hr_header_width_mm",
                "default_width": 170,
            },
        ]
        for spec in image_specs:
            # First non-empty string value found among the keys
            filename_val = next((context.get(k) for k in spec["filenames"] if isinstance(context.get(k), str) and context.get(k)), None)
            if not filename_val:
                continue
            img_path = TEMPLATES_DIR / filename_val
            if not img_path.exists():
                continue
            try:
                width_mm = context.get(spec["width_key"])
                img_width = Mm(float(width_mm)) if width_mm else Mm(spec["default_width"])
                inline_img = InlineImage(tpl, str(img_path), width=img_width)
                for key in spec["filenames"]:
                    context[key] = inline_img
            except Exception as e:
                print(f"[DocGen] Inline image error for {filename_val}: {e}")

    tpl.render(context or {}, jinja_env=env)
    
    # Save to BytesIO instead of disk
    output = BytesIO()
    tpl.save(output)
    output.seek(0)
    
    # Store in cache with unique key
    doc_key = f"{datetime.now().timestamp()}_{base_name}"
    _document_cache[doc_key] = {"bytes": output, "filename": base_name}

    return {
        "success": True,
        "filename": base_name,
        "download_key": doc_key,
    }


def get_document_from_cache(doc_key: str) -> Optional[BytesIO]:
    """Retrieve a document from memory cache by key."""
    cache_entry = _document_cache.get(doc_key)
    if cache_entry:
        return cache_entry.get("bytes")
    return None


def get_document_filename_from_cache(doc_key: str) -> Optional[str]:
    """Retrieve the filename of a cached document by key."""
    cache_entry = _document_cache.get(doc_key)
    if cache_entry:
        return cache_entry.get("filename")
    return None


def get_document_mimetype_from_cache(doc_key: str) -> str:
    """Infer mimetype from cached filename."""
    filename = get_document_filename_from_cache(doc_key) or ""
    if filename.lower().endswith(".pdf"):
        return "application/pdf"
    return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
