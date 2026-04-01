"""
PDF Summarizer — paste a PDF URL, get a multimodal summary with inline charts.
"""

import io
import re
import tempfile
from pathlib import Path

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

import anthropic
from pipeline.summarizer import (
    extract_text_pdf,
    extract_images_pdf,
    _img_to_png_b64,
    _clean_output,
)

MODEL = "claude-sonnet-4-6"
INPUT_COST_PER_MTOK = 3.0   # $/MTok for Sonnet 4
OUTPUT_COST_PER_MTOK = 15.0

PROMPT_TEMPLATE = """\
You are an expert analyst. Below is the full text of a PDF document, along with \
{n_images} images extracted from it (charts, graphs, diagrams, tables).

Produce a detailed, structured summary of the document. \
Where a chart or graph is relevant to the point you are making, \
reference it **inline** using the exact marker `[Image N]` (e.g. [Image 1], [Image 2]). \
Place the marker on its own line, right after the paragraph that discusses it. \
Only reference images that are substantive charts, graphs, or diagrams — skip logos and decorative images.

Use markdown formatting with headers, bullet points, and bold for key figures.

--- DOCUMENT TEXT ---
{text}
"""


def _download_pdf(url: str) -> Path:
    """Download PDF to a temp file and return its path."""
    resp = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.write(resp.content)
    tmp.close()
    return Path(tmp.name)


def _estimate_image_tokens(images: list[dict]) -> int:
    """Estimate token cost of images using Anthropic's formula: w*h/750."""
    total = 0
    for img in images:
        w = img.get("width", 0)
        h = img.get("height", 0)
        total += max(int(w * h / 750), 200)  # minimum ~200 tokens per image
    return total


def _summarize(text: str, images: list[dict]) -> tuple[str, dict]:
    """Send text + images to Claude and return (summary, usage_info)."""
    client = anthropic.Anthropic()

    prompt = PROMPT_TEMPLATE.format(n_images=len(images), text=text[:180_000])

    # Build multimodal content blocks
    content: list[dict] = [{"type": "text", "text": prompt}]
    for i, img in enumerate(images, 1):
        b64 = _img_to_png_b64(img["image_bytes"])
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": b64},
        })
        content.append({
            "type": "text",
            "text": f"[This is Image {i} — from page {img['page_or_slide']}]",
        })

    msg = client.messages.create(
        model=MODEL, max_tokens=8192,
        messages=[{"role": "user", "content": content}],
    )

    input_tok = msg.usage.input_tokens
    output_tok = msg.usage.output_tokens
    image_tok_est = _estimate_image_tokens(images)
    input_cost = input_tok * INPUT_COST_PER_MTOK / 1_000_000
    output_cost = output_tok * OUTPUT_COST_PER_MTOK / 1_000_000

    usage = {
        "input_tokens": input_tok,
        "output_tokens": output_tok,
        "image_tokens_est": image_tok_est,
        "text_tokens_est": input_tok - image_tok_est,
        "input_cost": input_cost,
        "output_cost": output_cost,
        "total_cost": input_cost + output_cost,
        "n_images": len(images),
    }

    return _clean_output(msg.content[0].text.strip()), usage


def _render_with_inline_images(summary: str, images: list[dict]):
    """Render summary markdown, replacing [Image N] with actual images."""
    # Split on [Image N] markers
    parts = re.split(r"\[Image\s+(\d+)\]", summary)
    # parts alternates: text, image_num, text, image_num, ...
    for i, part in enumerate(parts):
        if i % 2 == 0:
            # Text segment
            if part.strip():
                st.markdown(part.strip())
        else:
            # Image reference
            idx = int(part) - 1
            if 0 <= idx < len(images):
                img_bytes = images[idx]["image_bytes"]
                page = images[idx]["page_or_slide"]
                st.image(img_bytes, caption=f"Page {page}", use_container_width=True)


# ── UI ────────────────────────────────────────────────────────────────────────

st.title("PDF Summarizer")
st.caption("Paste a PDF URL to get an AI summary with inline charts and graphs.")

url = st.text_input(
    "PDF URL",
    placeholder="https://www.iso-ne.com/static-assets/documents/...",
)

if st.button("Summarize", type="primary", disabled=not url):
    with st.status("Working...", expanded=True) as status:
        st.write("Downloading PDF...")
        try:
            pdf_path = _download_pdf(url)
        except Exception as e:
            st.error(f"Download failed: {e}")
            st.stop()

        st.write("Extracting text...")
        text = extract_text_pdf(pdf_path)

        st.write(f"Extracting images...")
        images = extract_images_pdf(pdf_path, min_px=150)
        # Sort by area descending, keep substantive ones
        images.sort(
            key=lambda x: x.get("width", 0) * x.get("height", 0), reverse=True
        )
        images = images[:15]
        st.write(f"Found {len(images)} images.")

        st.write("Generating summary...")
        summary, usage = _summarize(text, images)

        status.update(label="Done", state="complete")

    st.session_state["pdf_summary"] = summary
    st.session_state["pdf_images"] = images
    st.session_state["pdf_usage"] = usage

# Render persisted results
if "pdf_summary" in st.session_state:
    # ── Cost / token metrics ──
    if "pdf_usage" in st.session_state:
        u = st.session_state["pdf_usage"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Input tokens", f"{u['input_tokens']:,}")
        c2.metric("Output tokens", f"{u['output_tokens']:,}")
        c3.metric("Image tokens (est.)", f"{u['image_tokens_est']:,}")
        c4.metric("Total cost", f"${u['total_cost']:.4f}")
        with st.expander("Cost breakdown"):
            st.markdown(
                f"- **Text tokens** (est.): {u['text_tokens_est']:,}\n"
                f"- **Image tokens** (est.): {u['image_tokens_est']:,} "
                f"({u['n_images']} images)\n"
                f"- **Input cost**: ${u['input_cost']:.4f} "
                f"({u['input_tokens']:,} tok × ${INPUT_COST_PER_MTOK}/MTok)\n"
                f"- **Output cost**: ${u['output_cost']:.4f} "
                f"({u['output_tokens']:,} tok × ${OUTPUT_COST_PER_MTOK}/MTok)\n"
                f"- **Total**: ${u['total_cost']:.4f}"
            )

    st.divider()
    _render_with_inline_images(
        st.session_state["pdf_summary"],
        st.session_state["pdf_images"],
    )
