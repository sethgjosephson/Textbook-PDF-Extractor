from __future__ import annotations
import streamlit as st
import fitz  # PyMuPDF
import re
import io
import json
import zipfile
from datetime import datetime
from pathlib import Path

st.set_page_config(page_title="Syllabus PDF Extractor", layout="wide")

DATA_DIR = Path(__file__).parent / "data"
STATE_FILE = DATA_DIR / "app_state.json"

# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def load_saved_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"schedule": {}, "history": [], "num_weeks": 8, "class_names": []}


def save_app_state(num_weeks: int, class_names: list[str], history: list[dict]):
    schedule: dict[str, dict] = {}
    for week in range(1, num_weeks + 1):
        week_data = {}
        for cname in class_names:
            spec = st.session_state.get(f"sched_{week}_{cname}", "").strip()
            if spec:
                week_data[cname] = spec
        if week_data:
            schedule[str(week)] = week_data

    DATA_DIR.mkdir(exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(
            {"schedule": schedule, "history": history, "num_weeks": num_weeks, "class_names": class_names},
            indent=2,
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# PDF helpers
# ---------------------------------------------------------------------------

def extract_section_number(title: str) -> str | None:
    m = re.match(r'^(\d+(?:\.\d+)*)', title.strip())
    if m:
        return m.group(1)
    m = re.match(r'^(?:chapter|section|unit|part)\s+(\d+(?:\.\d+)*)', title.strip(), re.IGNORECASE)
    return m.group(1) if m else None


def parse_section_spec(spec: str) -> list[str]:
    """'21.4-5, 22.1-2' → ['21.4', '21.5', '22.1', '22.2']"""
    sections: list[str] = []
    for part in re.split(r'[,;]\s*', spec.strip()):
        part = part.strip()
        if not part:
            continue
        m = re.match(r'^(\d+)\.(\d+)-(?:(\d+)\.)?(\d+)$', part)
        if m:
            chapter = m.group(1)
            start_sub = int(m.group(2))
            end_chapter = m.group(3) or chapter
            end_sub = int(m.group(4))
            if end_chapter == chapter:
                sections.extend(f"{chapter}.{s}" for s in range(start_sub, end_sub + 1))
            else:
                sections.append(f"{chapter}.{start_sub}")
                sections.append(f"{end_chapter}.{end_sub}")
        else:
            sections.append(part)
    return sections


def build_section_map(toc: list, page_count: int) -> dict[str, tuple[int, int]]:
    entries: list[tuple[int, str, int]] = []
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
        if snum not in section_map:
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


def make_zip_path(week: int, class_name: str, spec: str) -> str:
    safe_class = re.sub(r"[^\w\s-]", "", class_name).strip().replace(" ", "_")
    safe_spec = re.sub(r"[,;\s]+", "_", spec.strip()).strip("_")
    return f"Week_{week:02d}/{safe_class}_Week{week:02d}_Ch{safe_spec}.pdf"


# ---------------------------------------------------------------------------
# Session state init — load saved state once per session
# ---------------------------------------------------------------------------
if "classes" not in st.session_state:
    st.session_state.classes: dict[str, dict] = {}

if "history" not in st.session_state:
    saved = load_saved_state()
    st.session_state.history: list[dict] = saved.get("history", [])
    st.session_state._saved_schedule: dict = saved.get("schedule", {})
    st.session_state._saved_num_weeks: int = saved.get("num_weeks", 8)
    st.session_state._saved_class_names: list[str] = saved.get("class_names", [])

# Pre-populate schedule widget keys from saved state (only before first render)
for _week_str, _class_specs in st.session_state._saved_schedule.items():
    for _cname, _spec in _class_specs.items():
        _key = f"sched_{_week_str}_{_cname}"
        if _key not in st.session_state:
            st.session_state[_key] = _spec

# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.title("Syllabus PDF Extractor")
st.caption("Upload your textbooks, map your weekly schedule by section number, and download organized PDFs ready for NotebookLM.")

# ── Step 1: Classes ──────────────────────────────────────────────────────────
st.header("1. Classes & Textbooks")

# Remind user of previously used classes if none are loaded yet
if not st.session_state.classes and st.session_state._saved_class_names:
    st.info(
        "Previously used classes: **" + "**, **".join(st.session_state._saved_class_names) +
        "**. Re-upload their PDFs to continue — your schedule is already saved."
    )

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

to_remove: str | None = None
for cname, cdata in st.session_state.classes.items():
    with st.expander(f"📖 {cname} — {len(cdata['section_map'])} sections, {cdata['page_count']} pages"):
        if cdata["toc"]:
            lines = []
            for level, title, page in cdata["toc"][:50]:
                snum = extract_section_number(title)
                tag = f"  → `{snum}`" if snum else "  *(skipped — no number)*"
                lines.append(f"{'　' * (level - 1)}{title}  p.{page}{tag}")
            st.markdown("\n\n".join(lines))
            if len(cdata["toc"]) > 50:
                st.caption(f"({len(cdata['toc']) - 50} more entries not shown)")
        else:
            st.warning("No bookmarks found. Section extraction won't work for this PDF.")
        if st.button("Remove", key=f"rm_{cname}"):
            to_remove = cname

if to_remove:
    del st.session_state.classes[to_remove]
    st.rerun()

# ── Step 2: Schedule ─────────────────────────────────────────────────────────
if st.session_state.classes:
    st.header("2. Weekly Schedule")
    st.caption("Enter section specs like `21.4-5, 22.1-2`. Leave blank to skip a class for that week.")

    num_weeks = st.number_input(
        "Number of weeks",
        min_value=1,
        max_value=30,
        value=st.session_state._saved_num_weeks,
        step=1,
        key="num_weeks_input",
    )
    class_names = list(st.session_state.classes.keys())

    # Mark weeks that have already been extracted
    extracted_weeks = {
        (entry["week"], entry["class"])
        for entry in st.session_state.history
    }

    for week in range(1, int(num_weeks) + 1):
        done_classes = [c for c in class_names if (week, c) in extracted_weeks]
        badge = f" ✓ {', '.join(done_classes)}" if done_classes else ""
        with st.expander(f"Week {week}{badge}"):
            cols = st.columns(len(class_names))
            for i, cname in enumerate(class_names):
                already = (week, cname) in extracted_weeks
                saved_spec = st.session_state._saved_schedule.get(str(week), {}).get(cname, "")
                cols[i].text_input(
                    cname + (" ✓" if already else ""),
                    placeholder="21.4-5, 22.1-2",
                    key=f"sched_{week}_{cname}",
                    value=saved_spec if f"sched_{week}_{cname}" not in st.session_state else st.session_state[f"sched_{week}_{cname}"],
                )

    col_save, col_gen = st.columns([1, 3])

    if col_save.button("Save Schedule"):
        save_app_state(int(num_weeks), class_names, st.session_state.history)
        st.success("Schedule saved.")

    # ── Step 3: Generate ─────────────────────────────────────────────────────
    st.header("3. Generate")

    if st.button("Generate Weekly PDFs", type="primary"):
        zip_buf = io.BytesIO()
        errors: list[str] = []
        file_count = 0
        new_history: list[dict] = []

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
                                f"Week {week} / {cname}: not found in TOC — `{'`, `'.join(missing)}`"
                            )

                        if page_ranges:
                            pdf_data = extract_pages(cdata["pdf_bytes"], page_ranges)
                            zip_path = make_zip_path(week, cname, spec)
                            zf.writestr(zip_path, pdf_data)
                            file_count += 1
                            new_history.append({
                                "timestamp": datetime.now().isoformat(timespec="seconds"),
                                "week": week,
                                "class": cname,
                                "spec": spec,
                                "sections": sections,
                                "filename": zip_path.split("/")[1],
                            })

        # Merge new history (replace any same week+class entries)
        existing = [
            e for e in st.session_state.history
            if not any(n["week"] == e["week"] and n["class"] == e["class"] for n in new_history)
        ]
        st.session_state.history = sorted(
            existing + new_history, key=lambda e: (e["week"], e["class"])
        )

        save_app_state(int(num_weeks), class_names, st.session_state.history)

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
            st.success(f"Done — {file_count} PDF{'s' if file_count != 1 else ''} generated and schedule saved.")
        else:
            st.error("No PDFs generated. Check your schedule entries and verify section numbers match the TOC above.")

# ── Extraction History ───────────────────────────────────────────────────────
if st.session_state.history:
    st.header("Extraction History")
    import pandas as pd
    df = pd.DataFrame(st.session_state.history)[["timestamp", "week", "class", "spec", "filename"]]
    df.columns = ["Extracted", "Week", "Class", "Sections", "Filename"]
    st.dataframe(df, use_container_width=True, hide_index=True)

    if st.button("Clear History"):
        st.session_state.history = []
        save_app_state(
            int(st.session_state.get("num_weeks_input", 8)),
            list(st.session_state.classes.keys()),
            [],
        )
        st.rerun()
