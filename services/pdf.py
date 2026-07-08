"""HTML → PDF через WeasyPrint. Оформление по ГОСТ Р 7.0.97-2016."""
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import CSS, HTML

from config import DOC_PAGE_STYLE, STORAGE_DIR, TEMPLATES_DIR

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

BASE_CSS = f"""
@page {{
  size: {DOC_PAGE_STYLE['paper']};
  margin: {DOC_PAGE_STYLE['margin_top_cm']}cm {DOC_PAGE_STYLE['margin_right_cm']}cm
          {DOC_PAGE_STYLE['margin_bottom_cm']}cm {DOC_PAGE_STYLE['margin_left_cm']}cm;
  @bottom-right {{
    content: counter(page) " / " counter(pages);
    font-family: {DOC_PAGE_STYLE['font_family']};
    font-size: 9pt;
    color: #555;
  }}
}}
html {{ font-family: {DOC_PAGE_STYLE['font_family']}; font-size: {DOC_PAGE_STYLE['font_size_pt']}pt; }}
body {{ line-height: {DOC_PAGE_STYLE['line_height']}; color: #000; }}
article.doc {{ text-align: justify; }}
article.doc header {{ margin-bottom: 18pt; }}
article.doc header .to-block {{ text-align: right; white-space: pre-line; margin-bottom: 14pt; }}
article.doc header h1 {{ text-align: center; font-size: 14pt; font-weight: bold; margin: 14pt 0 10pt; text-transform: uppercase; }}
article.doc header h2 {{ text-align: center; font-size: 12pt; font-weight: normal; font-style: italic; margin: 0 0 12pt; }}
article.doc section {{ margin-bottom: 10pt; }}
article.doc p {{ margin: 0 0 6pt; text-indent: 1.25cm; }}
article.doc p.no-indent, article.doc p.signature {{ text-indent: 0; }}
article.doc ol, article.doc ul {{ margin: 6pt 0 6pt 1.25cm; }}
article.doc table {{ border-collapse: collapse; width: 100%; margin: 8pt 0; }}
article.doc th, article.doc td {{ border: 1px solid #000; padding: 4pt 6pt; vertical-align: top; font-size: 11pt; }}
article.doc footer {{ margin-top: 28pt; }}
article.doc footer .sig-row {{ display: flex; justify-content: space-between; margin-top: 24pt; }}
article.doc .law-refs {{ margin-top: 20pt; font-size: 9pt; color: #555; font-style: italic; }}
"""


def _slugify(text: str) -> str:
    text = (text or "doc").strip().lower()
    text = re.sub(r"[^a-zа-я0-9_\-]+", "_", text, flags=re.IGNORECASE)
    return text.strip("_")[:60] or "doc"


def render_html_to_pdf(inner_html: str, title: str, tg_id: int) -> Path:
    """Принимает inner HTML (без html/body) и возвращает путь к PDF."""
    full_html = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"><title>{title}</title></head>
<body>{inner_html}</body></html>"""

    out_dir = STORAGE_DIR / str(tg_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    from datetime import datetime
    fname = f"{datetime.now():%Y%m%d_%H%M%S}_{_slugify(title)}.pdf"
    out = out_dir / fname

    HTML(string=full_html).write_pdf(str(out), stylesheets=[CSS(string=BASE_CSS)])
    return out


def render_template_to_pdf(template_path: str, context: dict, title: str, tg_id: int) -> Path:
    """Рендер Jinja2-шаблона из templates/ → PDF."""
    tpl = _env.get_template(template_path)
    inner = tpl.render(**context)
    return render_html_to_pdf(inner, title, tg_id)
