from __future__ import annotations
import streamlit as st
import fitz  # PyMuPDF
import re
import io
import zipfile

st.set_page_config(page_title="Syllabus PDF Extractor", layout="wide")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def extract_section_number(title: str) -> str | None:
    """Pull a leading section number out of a TOC title.

    Handles both '21.4 Some Title' and 'Chapter 21 / Section 21.4' forms.
    """
    m = re.match(r'^(\d+(?:\.\d+)*)', title.strip())
    if m:
        return m.group(1)
    m = re.match(
        r'^(?:chapter|section|unit|part)\s+(\d+(?:\.\d+)*)',
        title.strip(),
        re.IGNORECASE,
    )
    return m.group(1) if m else None


def parse_section_spec(spec: str) -> list[str]:
    """Parse a human-readable spec into a flat list of section IDs.

    '21.4-5, 22.1-2'  →  ['21.4', '21.5', '22.1', '22.2']
    '3, 4'            →  ['3', '4']
    '21.4-21.6'       →  ['21.4', '21.5', '21.6']
    """
    sections: list[str] = []
    for part in re.split(r'[,;]\s*', spec.strip()):
        part = part.strip()
        if not part:
            continue
        # Range like "21.4-5" or "21.4-21.6"
        m = re.match(r'^(\d+)\.(\d+)-(?:(\d+)\.)?(\d+)$', part)
        if m:
            chapter = m.group(1)
            start_sub = int(m.group(2))
            end_chapter = m.group(3) or chapter
            end_sub = int(m.group(4))
            if end_chapter == chapter:
                sections.extend(f"{chapter}.{s}" for s in range(start_sub, end_sub + 1))
            else:
                # Cross-chapter range — add first and last as bookends
                sections.append(f"{chapter}.{start_sub}")
                sections.append(f"{end_chapter}.{end_sub}")
        else:
            sections.append(part)
    return sections


def build_section_map(toc: list, page_count: int) -> dict[str, tuple[int, int]]:
    """Return {section_number: (start_page, end_page)} using 0-based page indices.

    End page for a section is determined by the next sibling/parent entry in the
    TOC hierarchy, so subsections are included automatically.
    """
    entries: list[tuple[int, str, int]] = []  # (level, snum, page_0idx)
    for level, title, page in toc:
        snum = extract_section_number(title)
        if snum:
            entries.append((level, snum, page - 1))

    section_map: dict[str, tuple[int, int]] = {}
    for i, (level, snum, start) in enumerate(entries):
        end = page_count - 1
        for j in range(i + 1, len(entries)):
            if entries[j][0] <= level:
                end = entries[j][2] - 1
                break
        if snum not in section_map:  # first occurrence wins
            section_map[snum] = (start, end)
    return section_map


def load_pdf(pdf_file) -> dict:
    pdf_bytes = pdf_file.read()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    toc = doc.get_toc()
    page_count = doc.page_count
    doc.close()
    return {
        "pdf_bytes": pdf_bytes,
        "toc": toc,
        "page_count": page_count,
        "section_map": build_section_map(toc, page_count),
    }


def extract_pages(pdf_bytes: bytes, page_ranges: list[tuple[int, int]]) -> bytes:
    src = fitz.open(stream=pdf_bytes, filetype="pdf")
    out = fitz.open()
    for start, end in page_ranges:
        out.insert_pdf(src, from_page=max(0, start), to_page=min(end, src.page_count - 1))
    result = out.tobytes()
    src.close()
    out.close()
    return result


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
if "classes" not in st.session_state:
    st.session_state.classes: dict[str, dict] = {}

# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.title("Syllabus PDF Extractor")
st.caption("Upload your textbooks, map your weekly schedule by section number, and download organized PDFs ready for NotebookLM.")

# ── Step 1: Classes ─────────────────────────────────────────────────────────
st.header("1. Classes & Textbooks")

with st.form("class_form", clear_on_submit=True):
    col1, col2 = st.columns([1, 2])
    class_name = col1.text_input("Class name", placeholder="e.g. Biology 101")
    pdf_file = col2.file_uploader("Textbook PDF", type="pdf")
    submitted = st.form_submit_button("Add Class")

if submitted:
    if class_name and pdf_file:
        with st.spinner(f"Reading TOC from {pdf_file.name}…"):
            st.session_state.classes[class_name] = load_pdf(pdf_file)
        n = len(st.session_state.classes[class_name]["section_map"])
        st.success(f"Added **{class_name}** — {n} sections detected from bookmarks.")
    else:
        st.error("Provide both a class name and a PDF file.")

# Show loaded classes; track any removal request
to_remove: str | None = None
for cname, cdata in st.session_state.classes.items():
    label = f"📖 {cname} — {len(cdata['section_map'])} sections, {cdata['page_count']} pages"
    with st.expander(label):
        if cdata["toc"]:
            lines = []
            for level, title, page in cdata["toc"][:50]:
                snum = extract_section_number(title)
                tag = f"  → matched as **{snum}**" if snum else "  *(no number — skipped)*"
                lines.append(f"{'　' * (level - 1)}{title}  p.{page}{tag}")
            st.markdown("\n\n".join(lines))
            if len(cdata["toc"]) > 50:
                st.caption(f"({len(cdata['toc']) - 50} more entries not shown)")
        else:
            st.warning("No bookmarks found in this PDF. Section extraction won't work — check if your PDF has an embedded outline.")
        if st.button("Remove", key=f"rm_{cname}"):
            to_remove = cname

if to_remove:
    del st.session_state.classes[to_remove]
    st.rerun()

# ── Step 2: Schedule ────────────────────────────────────────────────────────
if st.session_state.classes:
    st.header("2. Weekly Schedule")
    st.caption(
        "Enter section specs using the shorthand from your syllabus — e.g. `21.4-5, 22.1-2`. "
        "Leave a cell blank to skip that class for the week."
    )

    num_weeks = st.number_input("Number of weeks", min_value=1, max_value=30, value=8, step=1)
    class_names = list(st.session_state.classes.keys())

    for week in range(1, int(num_weeks) + 1):
        with st.expander(f"Week {week}"):
            cols = st.columns(len(class_names))
            for i, cname in enumerate(class_names):
                cols[i].text_input(
                    cname,
                    placeholder="21.4-5, 22.1-2",
                    key=f"sched_{week}_{cname}",
                )

    # ── Step 3: Generate ────────────────────────────────────────────────────
    st.header("3. Generate")

    if st.button("Generate Weekly PDFs", type="primary"):
        zip_buf = io.BytesIO()
        errors: list[str] = []
        file_count = 0

        with st.spinner("Extracting pages…"):
            with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for week in range(1, int(num_weeks) + 1):
                    for cname in class_names:
                        spec = st.session_state.get(f"sched_{week}_{cname}", "").strip()
                        if not spec:
                            continue

                        cdata = st.session_state.classes[cname]
                        sections = parse_section_spec(spec)
                        page_ranges: list[tuple[int, int]] = []
                        missing: list[str] = []

                        for sec in sections:
                            if sec in cdata["section_map"]:
                                page_ranges.append(cdata["section_map"][sec])
                            else:
                                missing.append(sec)

                        if missing:
                            errors.append(
                                f"Week {week} / {cname}: sections not found in TOC — `{'`, `'.join(missing)}`"
                            )

                        if page_ranges:
                            pdf_data = extract_pages(cdata["pdf_bytes"], page_ranges)
                            safe = re.sub(r"[^\w\s-]", "", cname).strip().replace(" ", "_")
                            zf.writestr(f"Week_{week:02d}/{safe}.pdf", pdf_data)
                            file_count += 1

        for e in errors:
            st.warning(e)

        if file_count > 0:
            zip_buf.seek(0)
            st.download_button(
                label=f"Download {file_count} PDFs (ZIP)",
                data=zip_buf,
                file_name="weekly_readings.zip",
                mime="application/zip",
                type="primary",
            )
            st.success(f"Done — {file_count} PDF{'s' if file_count != 1 else ''} generated.")
        else:
            st.error("No PDFs generated. Check your schedule entries and verify section numbers match the TOC above.")
