# Syllabus PDF Extractor

A local Streamlit app that extracts weekly reading sections from textbook PDFs based on your class schedule — organized and ready to upload to [NotebookLM](https://notebooklm.google.com).

## How It Works

1. **Upload** your textbook PDF once per class — the app reads its embedded bookmarks automatically to map section numbers to pages
2. **Define your schedule** by week using the shorthand from your syllabus (e.g. `21.4-5, 22.1-2`)
3. **Generate** — downloads a ZIP organized by week, one PDF per class per week

Your schedule and extraction history are saved locally so everything picks back up where you left off.

## Output Structure

```
weekly_readings.zip
├── Week_01/
│   ├── Biology_101_Week01_Ch21.4-5_22.1-2.pdf
│   └── Chemistry_201_Week01_Ch3.1-3.pdf
├── Week_02/
│   └── ...
```

## Importing a Schedule from CSV or Excel

Instead of filling in the schedule manually, you can upload a CSV or Excel file — useful if you want an LLM to parse your syllabus automatically.

**File format** — three columns, one row per class per week:

```csv
week,class,sections
1,Biology 101,"21.4-5, 22.1-2"
1,Chemistry 201,3.1-3
2,Biology 101,"22.3-4, 23.1"
```

A blank template is available via the Download button inside the app.

**LLM prompt** — take a photo or screenshot of your syllabus and send it with this:

```
Convert this syllabus into a CSV with exactly three columns: week, class, sections.
- week: the week number (integer)
- class: the course name exactly as I will type it (e.g. Biology 101)
- sections: the reading sections in shorthand form (e.g. 21.4-5, 22.1-2)
One row per class per week. Skip weeks with no reading. Output only the CSV, no explanation.
```

Save the output as a `.csv` file and upload it in the Import section of the app.

## Section Spec Format

| Input | Expands to |
|-------|-----------|
| `21.4` | Section 21.4 |
| `21.4-6` | Sections 21.4, 21.5, 21.6 |
| `21.4-5, 22.1-2` | Sections 21.4, 21.5, 22.1, 22.2 |
| `3, 4` | Chapters 3 and 4 |

Sections are matched against the PDF's embedded table of contents. The TOC viewer in the app shows exactly how each entry was detected so you can verify before generating.

## Setup

**Requirements:** Python 3.10+

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open [http://localhost:8501](http://localhost:8501).

## Notes

- Requires textbook PDFs with embedded bookmarks/outlines (standard for most publisher PDFs)
- PDFs are processed locally — nothing is uploaded anywhere
- Schedule and history are stored in `data/app_state.json`
