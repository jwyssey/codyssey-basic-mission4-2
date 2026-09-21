#!/usr/bin/env python3
"""완성한 Markdown 리포트를 한글 PDF와 원문 증거 ZIP으로 묶는다."""
import argparse
import hashlib
import html
import io
import json
from pathlib import Path
import re
import zipfile

import fitz
import markdown

ROOT = Path(__file__).resolve().parents[1]


def render_report(path):
    source = path.read_text()
    # PDF에는 긴 저장소 경로를 표시하지 않고 링크의 설명을 유지한다.
    body = markdown.markdown(source, extensions=["tables", "fenced_code"])
    body = body.replace('src="../evidence/', 'src="evidence/')
    # 긴 로그는 공백에서 줄을 바꿔 A4 폭에 맞춘다. 원문은 ZIP에 보존한다.
    def wrap_code(match):
        import textwrap
        text = html.unescape(re.sub(r"<[^>]+>", "", match.group(1)))
        lines = []
        for line in text.splitlines():
            lines.extend(textwrap.wrap(line, 86, replace_whitespace=False, drop_whitespace=False) or [""])
        return "<pre>" + html.escape("\n".join(lines)) + "</pre>"
    return re.sub(r"<pre>(.*?)</pre>", wrap_code, body, flags=re.S)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--font", type=Path, default=Path.home() / ".local/share/fonts/malgun.ttf")
    args = parser.parse_args()
    if not args.font.is_file():
        parser.error("한글 폰트 경로를 --font로 지정하세요")
    output = ROOT / "submission"
    output.mkdir(exist_ok=True)
    manifest = json.loads((ROOT / "evidence/manifest.json").read_text())
    archive = fitz.Archive(str(ROOT))
    archive.add((args.font.read_bytes(), "report-font.ttf"))
    css = """
    @font-face {font-family: Report; src: url(report-font.ttf);}
    body {font-family: Report; font-size: 9pt; line-height: 1.4; color: #182635;}
    h1 {font-size: 18pt; color: #164e63; margin: 4pt 0 15pt;}
    h2 {font-size: 13pt; color: #164e63; margin: 15pt 0 6pt;}
    h3 {font-size: 11pt; margin: 10pt 0 5pt;}
    p {margin: 6pt 0;}
    table {border-collapse: collapse; width: 100%; font-size: 8pt; margin: 9pt 0;}
    td, th {border: 0.4pt solid #bbc8d3; padding: 5pt;}
    th {background: #e8f0f4;}
    pre {font-family: monospace; font-size: 7pt; background: #f0f3f6; padding: 8pt;}
    code {font-size: 8pt;}
    img {width: 100%;}
    a {color: #14657a; text-decoration: none;}
    """
    document = fitz.open()
    sections = [ROOT / "submission/overview.md", *sorted((ROOT / "reports").glob("*.md")), ROOT / "templates/issue-report.md"]
    toc = []
    for path in sections:
        title = path.read_text().splitlines()[0].lstrip("# ")
        toc.append([1, title, len(document) + 1])
        story = fitz.Story(render_report(path), user_css=css, archive=archive)
        buffer = io.BytesIO()
        writer = fitz.DocumentWriter(buffer)
        more = 1
        pages = 0
        while more:
            pages += 1
            if pages > 30:
                raise RuntimeError(f"페이지 배치 실패: {path}")
            media = fitz.paper_rect("a4")
            device = writer.begin_page(media)
            more, _ = story.place(media + (42, 42, -42, -44))
            story.draw(device)
            writer.end_page()
        writer.close()
        with fitz.open(stream=buffer.getvalue(), filetype="pdf") as part:
            document.insert_pdf(part)
    for page in document:
        page.insert_text((42, 823), f"Linux Incident Analysis | 2026-09-18 | {page.number + 1} / {len(document)}",
                         fontsize=8, color=(0.4, 0.45, 0.5))
    document.set_toc(toc)
    document.set_metadata({"title": "Linux 장애 분석 과제 2 - OOM, CPU, Deadlock", "author": "과제 실습 보고서"})
    # 원문 증거와 수집 코드를 보존하되 제공 바이너리·키·캐시는 제외한다.
    files = set()
    for folder in ("bin", "lib", "scripts", "tests", "reports", "templates", "docs", "docker"):
        files.update(p for p in (ROOT / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    for name in ("README.md", "TUTORIAL.md", "Evaluation.md", "Dockerfile", "compose.yaml", ".dockerignore", ".gitattributes", ".gitignore"):
        files.add(ROOT / name)
    files.add(ROOT / "vendor/README.md")
    files.update(p for p in (ROOT / "evidence").glob("*") if p.is_file())
    files.update((ROOT / "evidence/charts").glob("*.png"))
    for relative in manifest["runs"].values():
        files.update(p for p in (ROOT / relative).rglob("*") if p.is_file() and "agent-home" not in p.parts)
    sums = "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(ROOT)}\n" for p in sorted(files))
    (output / "SHA256SUMS").write_text(sums)
    zip_path = output / "source-and-evidence.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for path in sorted(files):
            z.write(path, str(path.relative_to(ROOT)))
        z.writestr("SHA256SUMS", sums)
    document.embfile_add("source-and-evidence.zip", zip_path.read_bytes(), filename=zip_path.name,
                        desc="원본 실험 로그·관측 CSV·수집 코드 (제공 바이너리 제외)")
    pdf = output / "linux-incident-report.pdf"
    document.subset_fonts()
    document.save(pdf, garbage=4, deflate=True)
    print(f"생성 완료: {pdf} ({len(document)} pages), {zip_path}")


if __name__ == "__main__":
    main()
