"""
utils.py — Shared utilities for the ISO-NE meeting pipeline.
"""
import re


def fix_markdown(text: str) -> str:
    """
    Deterministic cleanup of known formatting issues produced by LLM output.

    1. Backslash-escaped characters — Claude sometimes emits \\-, \\., \\(, \\)
       in Markdown contexts where no escaping is needed.  Strip the backslash
       so it does not appear literally in rendered output.

    2. Dollar-sign LaTeX math — Markdown renderers that support LaTeX (Streamlit,
       many web viewers) treat $...$ as inline math delimiters, which mangles
       dollar amounts mid-sentence (e.g. "$44/MWh ... $5.49/MWh" becomes italic
       garbled text).  We escape $ before digits as \\$ — this is a standard
       CommonMark backslash escape that renders as a literal $ in markdown
       renderers and in KaTeX/MathJax without triggering math mode.

       NOTE: The DOCX renderer (briefing.py _add_run_with_inline_markup) must
       strip these backslash escapes before writing plain text Word runs, since
       python-docx does not interpret CommonMark escapes.
    """
    # 1. Remove unnecessary backslash escapes before any non-newline character.
    #    This handles \-, \., \(, \) etc. that Claude over-escapes.
    #    We apply this BEFORE step 2 so that if Claude already wrote \$9,337
    #    we normalise it to $9,337 first, then re-escape uniformly in step 2.
    text = re.sub(r'\\([^\n])', lambda m: m.group(1), text)

    # 2. Escape $ immediately before a digit as \$ to prevent LaTeX math pairing.
    text = re.sub(r'\$(?=\d)', r'\\$', text)

    return text
