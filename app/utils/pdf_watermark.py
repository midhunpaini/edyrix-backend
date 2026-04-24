import fitz  # PyMuPDF


def add_watermark(pdf_bytes: bytes, user_name: str, user_id: str) -> bytes:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    label = f"Edyrix · {user_name} · {user_id[:8]}"

    for page in doc:
        w, h = page.rect.width, page.rect.height
        page.insert_text(
            fitz.Point(w * 0.12, h * 0.55),
            label,
            fontsize=22,
            color=(0.75, 0.75, 0.75),
            rotate=45,
            overlay=True,
        )

    return doc.tobytes()
