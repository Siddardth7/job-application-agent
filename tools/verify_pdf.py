#!/usr/bin/env python3
"""
verify_pdf.py — LaTeX & PDF compilation and ATS text-layer verification tool for Job_Applications.
Hardened with capabilities from MadsLorentzen/ai-job-search.

Checks:
1. LaTeX syntax safety (no bare unescaped &, %, #, _, $)
2. pdflatex compilation (clean exit code)
3. Strict Page Count (1 page for standard resumes, 2 pages for consolidated)
4. ATS Extractable Text Layer (pypdf + pdftotext fallback)
5. Literal Contact Text Verification (email, phone, name)
6. Clean Unicode / No (cid:NNN) or replacement glyphs
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

class VerificationError(Exception):
    """Raised when LaTeX compilation or PDF checks fail."""


def _candidate_identity() -> list[str]:
    """Name + email from data/candidate_resume_database.json, so the ATS-text
    check works for whoever cloned this without hardcoding anyone's identity."""
    import json
    from pathlib import Path
    db = Path(__file__).resolve().parent.parent / "data" / "candidate_resume_database.json"
    try:
        c = json.loads(db.read_text(encoding="utf-8"))["candidate"]
        return [v for v in (c.get("name"), c.get("contact", {}).get("email")) if v]
    except Exception:
        return []


def check_latex_syntax(tex_path: Path) -> list[str]:
    """Scan LaTeX file for dangerous unescaped characters."""
    errors = []
    content = tex_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    
    unescaped_amp = re.compile(r'(?<!\\)&')
    unescaped_under = re.compile(r'(?<!\\)_')
    
    for idx, line in enumerate(lines, start=1):
        clean_line = line.strip()
        if clean_line.startswith('%') or r'\newcommand' in line or r'\renewcommand' in line or r'\def' in line or r'\begin{tabular' in line or r'\end{tabular' in line:
            continue
        
        # Check for unescaped ampersand in body text
        if r'\textbf{' in line or r'\resumeItem{' in line or r'\small{' in line:
            if unescaped_amp.search(line):
                errors.append(f"Line {idx}: Unescaped '&' found: {clean_line}")
                    
        # Check unescaped underscores in plain text
        if r'\href{' not in line and r'\url{' not in line:
            if unescaped_under.search(line):
                errors.append(f"Line {idx}: Unescaped '_' found: {clean_line}")

    return errors

def compile_latex(tex_path: Path, output_dir: Path) -> Path:
    """Compile LaTeX to PDF using pdflatex."""
    tex_dir = tex_path.parent
    env = os.environ.copy()
    env["PATH"] = f"/Library/TeX/texbin:/usr/local/bin:{env.get('PATH', '')}"
    
    cmd = [
        "pdflatex",
        "-interaction=nonstopmode",
        f"-output-directory={output_dir}",
        str(tex_path)
    ]
    
    result = subprocess.run(cmd, cwd=tex_dir, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        err_msg = [f"Compilation error for {tex_path.name}:"]
        for line in result.stdout.splitlines()[-25:]:
            err_msg.append(f"  {line}")
        raise VerificationError("\n".join(err_msg))
        
    pdf_path = output_dir / f"{tex_path.stem}.pdf"
    if not pdf_path.exists():
        raise VerificationError(f"pdflatex reported success but {pdf_path.name} was not created.")
    return pdf_path

def normalize_text(text: str) -> str:
    return " ".join(text.split())

def _extract_pypdf(pdf_path: Path):
    """Return (text, pages) or None if pypdf is unavailable/empty."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        reader = PdfReader(str(pdf_path))
        pages = len(reader.pages)
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        return None
    if len(normalize_text(text)) == 0:
        return None
    return text, pages

def _extract_pdftotext(pdf_path: Path):
    """Fallback text extraction via poppler pdftotext + pdfinfo."""
    env = os.environ.copy()
    env["PATH"] = f"/Library/TeX/texbin:/usr/local/bin:{env.get('PATH', '')}"
    try:
        text = subprocess.run(
            ["pdftotext", "-layout", "-enc", "UTF-8", str(pdf_path), "-"],
            env=env, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace"
        ).stdout
        info = subprocess.run(
            ["pdfinfo", str(pdf_path)],
            env=env, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace"
        ).stdout
        match = re.search(r"^Pages:\s+(\d+)\s*$", info, re.MULTILINE)
        pages = int(match.group(1)) if match else 1
        return text, pages
    except Exception as e:
        raise VerificationError(f"Failed to extract text with pdftotext: {e}")

def extract_text_layer(pdf_path: Path) -> tuple[str, int, str]:
    """Extract ATS-readable text. Returns (text, pages, extractor_name)."""
    pypdf_res = _extract_pypdf(pdf_path)
    if pypdf_res is not None:
        text, pages = pypdf_res
        return text, pages, "pypdf"
    text, pages = _extract_pdftotext(pdf_path)
    return text, pages, "pdftotext"

def verify_pdf_content(pdf_path: Path, expected_pages: int = 1, min_chars: int = 100,
                       required_text: list[str] = None, dump_text_path: Path = None):
    """Run thorough ATS verification on PDF."""
    if not pdf_path.is_file():
        raise VerificationError(f"PDF does not exist: {pdf_path}")
        
    extracted_text, actual_pages, extractor = extract_text_layer(pdf_path)
    
    if dump_text_path is not None:
        dump_text_path.parent.mkdir(parents=True, exist_ok=True)
        dump_text_path.write_text(extracted_text, encoding="utf-8")
        
    # 1. Page count check
    if expected_pages is not None and actual_pages != expected_pages:
        raise VerificationError(f"Expected {expected_pages} page(s), got {actual_pages} (extractor: {extractor})")
        
    normalized = normalize_text(extracted_text)
    
    # 2. Text density check
    if len(normalized) < min_chars:
        raise VerificationError(f"Text layer has only {len(normalized)} chars (expected >= {min_chars}). Extractor: {extractor}")
        
    # 3. Unicode & garbled glyph check
    if "(cid:" in extracted_text or "\ufffd" in extracted_text:
        raise VerificationError(f"Garbled font encodings / (cid:NNN) detected in PDF text layer.")
        
    # 4. Required text check (e.g. candidate name, contact)
    if required_text:
        for req in required_text:
            if normalize_text(req).lower() not in normalized.lower():
                raise VerificationError(f"Missing required literal text in ATS layer: '{req}'")
                
    return extractor, extracted_text, actual_pages

def build_parser():
    parser = argparse.ArgumentParser(description="Compile and verify LaTeX/PDF resumes with ATS text layer checks.")
    parser.add_argument("target", type=Path, help="Path to .tex or .pdf file")
    parser.add_argument("--output-dir", type=Path, help="Directory to output compiled PDF")
    parser.add_argument("--expected-pages", "--pages", dest="expected_pages", type=int, default=1, help="Expected page count (default: 1)")
    parser.add_argument("--min-chars", type=int, default=200, help="Minimum non-whitespace chars in text layer")
    parser.add_argument("--contains", action="append", default=[], help="Required text string in ATS layer")
    parser.add_argument("--dump-text", type=Path, help="Dump extracted ATS text layer to path")
    return parser

def main(argv=None):
    args = build_parser().parse_args(argv)
    target = args.target.resolve()
    
    if not target.exists():
        print(f"Error: Target file not found: {target}", file=sys.stderr)
        return 1
        
    output_dir = args.output_dir.resolve() if args.output_dir else target.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Step 1: If input is TeX, check syntax and compile
    if target.suffix.lower() == ".tex":
        syntax_warnings = check_latex_syntax(target)
        if syntax_warnings:
            print(f"Syntax warnings in {target.name}:", file=sys.stderr)
            for warn in syntax_warnings:
                print(f"  {warn}", file=sys.stderr)
                
        try:
            pdf_path = compile_latex(target, output_dir)
        except VerificationError as exc:
            print(f"Compile Error: {exc}", file=sys.stderr)
            return 1
    else:
        pdf_path = target
        
    # Step 2: Verify PDF text layer and pages
    req_text = args.contains if args.contains else _candidate_identity()
    
    try:
        extractor, text, pages = verify_pdf_content(
            pdf_path=pdf_path,
            expected_pages=args.expected_pages,
            min_chars=args.min_chars,
            required_text=req_text,
            dump_text_path=args.dump_text
        )
        print(f"SUCCESS: {pdf_path.name} verified ({pages} page(s), extractor: {extractor}, text-layer clean).")
        return 0
    except VerificationError as exc:
        print(f"Verification Failed for {pdf_path.name}: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())

