"""Server-side markdown rendering with HTML sanitization."""

import bleach
import markdown

ALLOWED_TAGS = [
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "br", "hr",
    "ul", "ol", "li",
    "strong", "em", "del", "code", "pre", "blockquote",
    "a", "table", "thead", "tbody", "tr", "th", "td",
]

ALLOWED_ATTRIBUTES = {
    "a": ["href", "title", "rel"],
    "th": ["align"],
    "td": ["align"],
}


def render_markdown(text: str) -> str:
    """Convert markdown to sanitized HTML."""
    if not text or not text.strip():
        return ""
    html = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "nl2br"],
    )
    return bleach.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        strip=True,
    )
