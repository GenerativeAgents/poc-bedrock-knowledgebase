#!/usr/bin/env python3
"""AWS 日本語ドキュメントの Markdown 版を取得する。

各ガイドの sitemap.xml からページを列挙し、.html を .md に読み替えて取得する。
出力パスは docs.aws.amazon.com の URL 構造をそのまま写すので、S3 キーから
公開ドキュメントの URL を復元できる(引用リンク用)。
"""
import argparse
import concurrent.futures as cf
import pathlib
import random
import re
import sys
import time
import urllib.error
import urllib.request

BASE = "https://docs.aws.amazon.com/ja_jp/"
UA = "poc-bedrock-knowledgebase/0.1 (+corpus builder for a private RAG PoC)"


def get(url, timeout=30, attempts=5):
    """429/5xx は指数バックオフで粘る。404 は None を返して呼び出し側で捨てる。"""
    for i in range(attempts):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (403, 429) or e.code >= 500:
                if i == attempts - 1:
                    raise
                time.sleep((2**i) + random.random())
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if i == attempts - 1:
                raise
            time.sleep((2**i) + random.random())
    return None


def pages_of(sitemap_url):
    body = get(sitemap_url)
    if body is None:
        return []
    urls = re.findall(r"<loc>(.*?)</loc>", body.decode("utf-8", "replace"))
    # サイトマップにまれに ".html.html" と二重になったエントリが混ざるので正規化する
    urls = [u[: -len(".html")] if u.endswith(".html.html") else u for u in urls]
    return sorted({u for u in urls if u.endswith(".html") and u.startswith(BASE)})


def fetch_page(page_url, outdir):
    rel = page_url[len(BASE):][:-len(".html")] + ".md"
    dest = outdir / rel
    if dest.exists() and dest.stat().st_size > 0:
        return "skip", rel
    body = get(page_url[:-len(".html")] + ".md")
    if body is None:
        return "missing", rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    return "ok", rel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--guides", required=True, help="sitemap.xml の URL を1行1件で並べたファイル")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--workers", type=int, default=4, help="同時接続数。上げすぎると CloudFront に絞られる")
    ap.add_argument("--failed-log", default=None)
    a = ap.parse_args()

    outdir = pathlib.Path(a.outdir)
    guides = [l.strip() for l in open(a.guides) if l.strip()]
    failed, tally = [], {"ok": 0, "skip": 0, "missing": 0, "error": 0}

    for gi, g in enumerate(guides, 1):
        try:
            pages = pages_of(g)
        except Exception as e:
            failed.append(f"{g}\tsitemap\t{e}")
            tally["error"] += 1
            print(f"[{gi}/{len(guides)}] SITEMAP-ERR {g}: {e}", flush=True)
            continue
        with cf.ThreadPoolExecutor(a.workers) as ex:
            futs = {ex.submit(fetch_page, p, outdir): p for p in pages}
            for fut in cf.as_completed(futs):
                try:
                    status, _ = fut.result()
                    tally[status] += 1
                except Exception as e:
                    tally["error"] += 1
                    failed.append(f"{futs[fut]}\tpage\t{e}")
        name = g[len(BASE):].replace("/sitemap.xml", "")
        print(f"[{gi}/{len(guides)}] {name}: {len(pages)}ページ "
              f"(ok={tally['ok']} skip={tally['skip']} missing={tally['missing']} err={tally['error']})",
              flush=True)

    if a.failed_log and failed:
        pathlib.Path(a.failed_log).write_text("\n".join(failed) + "\n")
    print(f"DONE guides={len(guides)} " + " ".join(f"{k}={v}" for k, v in tally.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
