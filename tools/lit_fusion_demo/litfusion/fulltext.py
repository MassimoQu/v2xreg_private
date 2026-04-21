import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


def _safe_name(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return "paper"
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", s)
    return s[:180].strip("_") or "paper"


def paper_id_to_stem(paper_id: str) -> str:
    return _safe_name(paper_id)


def guess_pdf_url(paper: Dict[str, Any]) -> Optional[str]:
    url = paper.get("pdf_url")
    if isinstance(url, str) and url.strip():
        return url.strip()

    arxiv_id = paper.get("arxiv_id")
    if isinstance(arxiv_id, str) and arxiv_id.strip():
        return "https://arxiv.org/pdf/%s.pdf" % arxiv_id.strip()

    u = paper.get("url") or paper.get("id")
    if isinstance(u, str) and u:
        # arXiv abs -> pdf
        m = re.search(r"https?://arxiv\\.org/abs/([^?#]+)", u)
        if m:
            return "https://arxiv.org/pdf/%s.pdf" % m.group(1)
        # direct pdf
        if u.lower().endswith(".pdf"):
            return u

    return None


def download_pdf(url: str, dst: Path, timeout_s: int = 60, retries: int = 2) -> bool:
    if dst.exists() and dst.stat().st_size > 0:
        return True

    dst.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "litfusion-demo/0.2"}
    last_err = None
    for _ in range(max(1, retries + 1)):
        try:
            r = requests.get(url, stream=True, timeout=timeout_s, headers=headers)
            if r.status_code >= 400:
                last_err = RuntimeError("HTTP %d" % r.status_code)
                continue
            with open(str(dst), "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 64):
                    if chunk:
                        f.write(chunk)
            if dst.exists() and dst.stat().st_size > 0:
                return True
        except Exception as e:
            last_err = e
            continue
    if last_err:
        return False
    return False


def extract_pdf_text(pdf_path: Path, txt_path: Path, timeout_s: int = 180) -> bool:
    if txt_path.exists() and txt_path.stat().st_size > 0:
        return True
    txt_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        # -enc UTF-8 ensures downstream JSON/LLM prompts are stable.
        subprocess.run(
            ["pdftotext", "-q", "-enc", "UTF-8", "-nopgbrk", str(pdf_path), str(txt_path)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout_s,
        )
    except Exception:
        return False

    return txt_path.exists() and txt_path.stat().st_size > 0


def prepare_fulltext_assets(
    papers: List[Dict[str, Any]],
    *,
    out_dir: Path,
    max_papers: int = 12,
    concurrency: int = 4,
) -> Dict[str, Any]:
    """
    Download PDFs (when possible) and extract text.

    Outputs:
      - <out_dir>/pdfs/*.pdf
      - <out_dir>/texts/*.txt
    """

    pdf_dir = out_dir / "pdfs"
    txt_dir = out_dir / "texts"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    txt_dir.mkdir(parents=True, exist_ok=True)

    picked = []
    for p in papers or []:
        if len(picked) >= int(max_papers):
            break
        if not isinstance(p, dict):
            continue
        pid = p.get("paper_id") or p.get("id") or ""
        if not pid:
            continue
        picked.append(p)

    results = {"downloaded": [], "extracted": [], "failed": []}  # type: Dict[str, Any]

    def work(p: Dict[str, Any]) -> Tuple[str, bool, bool]:
        pid = p.get("paper_id") or p.get("id") or ""
        pdf_url = guess_pdf_url(p)
        if not pdf_url:
            return pid, False, False
        pdf_path = pdf_dir / (_safe_name(pid) + ".pdf")
        ok_dl = download_pdf(pdf_url, pdf_path)
        if not ok_dl:
            return pid, False, False
        txt_path = txt_dir / (_safe_name(pid) + ".txt")
        ok_txt = extract_pdf_text(pdf_path, txt_path)
        return pid, True, ok_txt

    with ThreadPoolExecutor(max_workers=max(1, int(concurrency))) as ex:
        futs = [ex.submit(work, p) for p in picked]
        for f in as_completed(futs):
            pid, ok_dl, ok_txt = f.result()
            if ok_dl:
                results["downloaded"].append(pid)
            if ok_txt:
                results["extracted"].append(pid)
            if not ok_dl and not ok_txt:
                results["failed"].append(pid)

    return results


def read_fulltext(out_dir: Path, paper_id: str) -> Optional[str]:
    txt = out_dir / "texts" / (_safe_name(paper_id) + ".txt")
    if not txt.exists():
        return None
    try:
        return txt.read_text()
    except Exception:
        return None
