#!/usr/bin/env python3
# P6 知识库产品：附件 PDF 下载 + 文字层抽取（语料充实，2026-11-01）
#
# 背景：办事指南页面正文多为图片流程图 PDF，HTML 抽取只有「下载阅读器」提示语。
# 实测这些 PDF 为矢量导出，自带文字层（如教代会流程 752 字），值得全量抽取。
#
# 安全约定（硬性，与 crawl.mjs 一致并加固）：
#   1. 只发 https 请求，端口仅 443；
#   2. host 必须精确等于 info.stu.edu.cn（字符串层 + URL 解析层双重校验）；
#   3. 请求前做 DNS 解析，所有解析结果必须是公网地址（防 DNS rebinding，
#      阻断私网/环回/链路本地/保留地址）；
#   4. 禁止重定向（防 30x 逃逸到其他 host）；
#   5. 只下载文章页 HTML 里出现的 .pdf 附件，不爬全站。
#
# 幂等性：PDF 已下载的跳过（断点续跑）；文字抽取每次重跑（本地操作，快）。
#
# 用法：python scripts/extract_pdf.py
#
# 产出：
#   data/raw/pdfs/       原始 PDF 存档（按 栏目ID-文章ID[-序号].pdf 命名）
#   data/extracted/      在原 txt 末尾追加「【附件PDF正文】】」小节
#   data/pdf_manifest.json  每篇文章的 PDF 附件清单与字数统计
import ipaddress
import json
import re
import socket
import time
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

try:
    import pymupdf  # 新 API
except ImportError:  # 兼容旧安装名
    import fitz as pymupdf

ROOT = Path(__file__).resolve().parent.parent
PDFS = ROOT / "data" / "raw" / "pdfs"
EXTRACTED = ROOT / "data" / "extracted"
PDFS.mkdir(parents=True, exist_ok=True)

ALLOW_HOST = "info.stu.edu.cn"
UA = {"User-Agent": "Mozilla/5.0 (compatible; p6-kb-collector/1.0)"}  # HTTP 头只能用 ASCII


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """一律禁止重定向：30x 直接抛 HTTPError，防止被引去其他 host"""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def guard_url(url):
    """请求前完整校验：https + host 白名单 + 端口 + DNS 解析全公网"""
    p = urllib.parse.urlparse(url)
    if p.scheme != "https" or p.hostname != ALLOW_HOST or (p.port not in (None, 443)):
        raise ValueError(f"URL 未通过白名单校验: {url}")
    infos = socket.getaddrinfo(p.hostname, 443, proto=socket.IPPROTO_TCP)
    ips = {info[4][0] for info in infos}
    for ip_s in ips:
        ip = ipaddress.ip_address(ip_s)
        if not ip.is_global:
            raise ValueError(f"DNS 解析到非公网地址 {ip}，拒绝请求")
    return ips


def safe_url(href, base):
    """字符串层预筛：仅收 .pdf 附件链接（真正校验在请求前 guard_url 做）"""
    absu = urljoin(base, href)
    if not re.search(r"\.pdf(\?|$)", absu, re.I):
        return None
    if not absu.startswith("https://"):
        return None
    rest = absu[len("https://"):]
    if not (rest == ALLOW_HOST + "/" or rest.startswith(ALLOW_HOST + "/")):
        return None
    return absu


def download(url, dest, tries=2):
    """带重试的下载；成功返回 True"""
    for i in range(tries):
        try:
            guard_url(url)  # 每次请求前都重新校验（含 DNS）
            req = urllib.request.Request(url, headers=UA)
            with OPENER.open(req, timeout=20) as resp:
                dest.write_bytes(resp.read())
            return True
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(1.5)
    return False


def pdf_text(path):
    """抽取 PDF 全部文字层，按行去空行合并"""
    doc = pymupdf.open(path)
    lines = []
    for page in doc:
        for ln in page.get_text().splitlines():
            ln = ln.strip()
            if ln:
                lines.append(ln)
    doc.close()
    return lines


def main():
    manifest = json.loads((ROOT / "data" / "manifest.json").read_text(encoding="utf-8"))
    out, errors = [], []
    for a in manifest["articles"]:
        art_html = ROOT / "data" / "raw" / "articles" / f"{a['id']}.htm"
        if not art_html.exists():
            continue
        html = art_html.read_text(encoding="utf-8", errors="ignore")
        hrefs = re.findall(r'href="([^"]+)"', html, re.I)
        pdfs = []
        for h in hrefs:
            u = safe_url(h, a["url"])
            if u and u not in [p["pdfUrl"] for p in pdfs]:
                pdfs.append({"pdfUrl": u})
        if not pdfs:
            continue

        # 1) 下载（幂等：已存在跳过）
        for i, p in enumerate(pdfs):
            suffix = f"-{i + 1}" if len(pdfs) > 1 else ""
            dest = PDFS / f"{a['id']}{suffix}.pdf"
            p["file"] = f"data/raw/pdfs/{dest.name}"
            if not dest.exists():
                try:
                    download(p["pdfUrl"], dest)
                except Exception as e:
                    errors.append(f"{a['id']}  {p['pdfUrl']}  {e}")
                    p["status"] = f"下载失败: {e}"
                    continue
                time.sleep(0.35)  # 礼貌延迟，别给学校服务器添堵
            # 2) 抽取文字层
            try:
                lines = pdf_text(dest)
            except Exception as e:
                errors.append(f"{a['id']}  PDF解析失败  {e}")
                p["status"] = f"解析失败: {e}"
                continue
            p["pages"] = len(pymupdf.open(dest))
            p["chars"] = sum(len(x) for x in lines)
            p["status"] = "ok"

        # 3) 追加进 extracted txt（先清掉旧小节，重跑幂等）
        ok = [p for p in pdfs if p.get("status") == "ok"]
        if ok:
            txt_path = EXTRACTED / f"{a['id']}.txt"
            text = txt_path.read_text(encoding="utf-8")
            text = re.split(r"\n【附件PDF正文】", text)[0].rstrip() + "\n"
            for p in ok:
                lines = pdf_text(ROOT / p["file"])
                text += "\n【附件PDF正文】\n" + "\n".join(lines) + "\n"
            txt_path.write_text(text, encoding="utf-8")
        out.append({"id": a["id"], "category": a["category"], "title": a["title"],
                    "pdfCount": len(pdfs), "pdfs": pdfs})

    total_chars = sum(p["chars"] for o in out for p in o["pdfs"] if p.get("status") == "ok")
    report = {
        "source": "汕头大学信息公开网·学校办事指南（附件PDF）",
        "extractedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "articlesWithPdf": len(out),
        "totalPdfChars": total_chars,
        "errors": errors,
        "articles": out,
    }
    (ROOT / "data" / "pdf_manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"PDF 抽取完成：{len(out)} 篇文章含附件，抽出文字共 {total_chars} 字")
    if errors:
        print(f"失败 {len(errors)} 个：")
        for e in errors:
            print("  " + e)


if __name__ == "__main__":
    main()
