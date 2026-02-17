import glob, json, re
from pathlib import Path
import pandas as pd

RAW_ROOT = Path("backend/data/raw")
OUT_DIR = Path("backend/data/processed")
OUT_DIR.mkdir(parents=True, exist_ok=True)

def clean_text(s: str) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s

def pick_first_existing(cols, candidates):
    lower = {c.lower(): c for c in cols}
    for cand in candidates:
        if cand.lower() in lower:
            return lower[cand.lower()]
    return None

def build_resume_samples(max_rows=200):
    # Find a likely resume CSV
    csvs = glob.glob(str(RAW_ROOT / "resume_dataset" / "**/*.csv"), recursive=True)
    if not csvs:
        print("No resume CSV found. (If the dataset is PDFs-only, skip to PR2 manual samples.)")
        return

    # Try each CSV until we find a "resume text" column
    for p in csvs:
        df = pd.read_csv(p)
        text_col = pick_first_existing(df.columns, ["Resume", "resume", "Resume_str", "Resume_text", "text", "Text", "Content", "Resume_Text"])
        label_col = pick_first_existing(df.columns, ["Category", "category", "Label", "label"])
        if text_col:
            out_path = OUT_DIR / "sample_resumes.jsonl"
            n = 0
            with out_path.open("w", encoding="utf-8") as f:
                for _, row in df.iterrows():
                    t = clean_text(row.get(text_col, ""))
                    if len(t) < 200:
                        continue
                    rec = {
                        "user_id": "student1",
                        "source_type": "kaggle",
                        "raw_text": t,
                        "metadata": {"dataset": "snehaanbhawal/resume-dataset", "label": str(row.get(label_col, "")), "source_file": Path(p).name},
                        "image_ref": "/images/resume_icon.png",
                    }
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    n += 1
                    if n >= max_rows:
                        break
            print("Wrote:", out_path, "rows:", n)
            return

    print("Could not find a resume text column automatically. Check columns and update candidates list.")

def build_job_samples(max_rows=500):
    csvs = glob.glob(str(RAW_ROOT / "linkedin_job_postings" / "**/*.csv"), recursive=True)
    if not csvs:
        print("No job CSV found.")
        return

    # Prefer the biggest-looking main file first
    for p in sorted(csvs, key=lambda x: -Path(x).stat().st_size):
        df = pd.read_csv(p)
        title_col = pick_first_existing(df.columns, ["title", "Title", "job_title", "Job Title", "position", "Position"])
        desc_col  = pick_first_existing(df.columns, ["description", "Description", "job_description", "Job Description", "desc", "text"])
        company_col = pick_first_existing(df.columns, ["company", "Company", "company_name", "Company Name"])
        loc_col = pick_first_existing(df.columns, ["location", "Location", "job_location", "Job Location"])
        if title_col and desc_col:
            out_path = OUT_DIR / "sample_jobs.jsonl"
            n = 0
            with out_path.open("w", encoding="utf-8") as f:
                for _, row in df.iterrows():
                    title = clean_text(row.get(title_col, ""))
                    desc = clean_text(row.get(desc_col, ""))
                    if len(desc) < 200:
                        continue
                    rec = {
                        "title": title,
                        "company": clean_text(row.get(company_col, "")) if company_col else "",
                        "location": clean_text(row.get(loc_col, "")) if loc_col else "",
                        "description": desc,
                        "source": "kaggle",
                        "metadata": {"dataset": "arshkon/linkedin-job-postings", "source_file": Path(p).name},
                    }
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    n += 1
                    if n >= max_rows:
                        break
            print("Wrote:", out_path, "rows:", n, "from:", p)
            return

    print("Could not find title+description columns automatically. Check columns and update candidates list.")

if __name__ == "__main__":
    build_resume_samples()
    build_job_samples()
