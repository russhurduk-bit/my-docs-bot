"""Ядро: принимает запрос пользователя и профиль, возвращает готовые PDF."""
import logging
from pathlib import Path

from db import add_history, get_profile
from services import llm
from services.pdf import render_html_to_pdf

log = logging.getLogger(__name__)


async def process_request(
    tg_id: int,
    user_request: str,
    known_fields: dict | None = None,
    chat_history: list[dict] | None = None,
) -> dict:
    """
    Возвращает:
    {
      "status": "ready" | "need_info",
      "questions": [...],          # если need_info
      "documents": [               # если ready
        {"title": ..., "pdf_path": "...", "history_id": 42, "law_refs": [...], "notes": "..."}
      ]
    }
    """
    profile = await get_profile(tg_id)
    result = await llm.generate_document_html(
        user_request=user_request,
        profile=profile,
        known_fields=known_fields or {},
        history=chat_history,
    )

    if result.get("status") != "ready":
        return result

    out_docs = []
    for d in result.get("documents", []):
        title = d.get("title", "Документ")
        inner_html = d.get("html", "")
        law_refs = d.get("law_refs", [])

        if law_refs:
            refs_html = "<div class=\"law-refs\">Нормативная база: " + "; ".join(law_refs) + "</div>"
            if "</article>" in inner_html:
                inner_html = inner_html.replace("</article>", refs_html + "</article>")
            else:
                inner_html = inner_html + refs_html

        pdf_path = render_html_to_pdf(inner_html, title, tg_id)
        hid = await add_history(
            tg_id=tg_id,
            title=title,
            doc_type=d.get("doc_type", "generic"),
            pdf_path=str(pdf_path),
            input_data={"request": user_request, "known": known_fields or {}},
        )
        out_docs.append({
            "title": title,
            "pdf_path": str(pdf_path),
            "history_id": hid,
            "law_refs": law_refs,
            "notes": d.get("notes", ""),
        })

    return {"status": "ready", "documents": out_docs}
