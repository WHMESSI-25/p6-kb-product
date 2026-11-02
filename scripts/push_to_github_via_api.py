# -*- coding: utf-8 -*-
"""用 GitHub API 推送仓库（适用于 github.com:443 被网络阻断、只有 api.github.com 可通的机器）

背景：2026-11-02 推送 P6 时，本机到 github.com 的 git 通道一律超时/502，
但 api.github.com 正常，因此改用 Git Data API 按本地提交历史逐个还原：
blob → tree → commit → ref，最终 GitHub 上的提交信息、作者、时间与本地一致。

用法：
    GITHUB_TOKEN=xxx python scripts/push_to_github_via_api.py WHMESSI-25/p6-kb-product main

令牌只从环境变量 GITHUB_TOKEN 读取，不写入任何文件、不打印。
"""
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

API = "https://api.github.com"


def run(*args):
    return subprocess.run(args, capture_output=True, check=True).stdout


def api(method, path, payload=None, token=""):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        API + path, data=data, method=method,
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json",
                 "User-Agent": "p6-push-script"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body) if body else {}


def main():
    repo, branch = sys.argv[1], sys.argv[2]
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        sys.exit("环境变量 GITHUB_TOKEN 未设置")

    commits = run("git", "rev-list", "--reverse", branch).decode().split()
    print(f"本地提交 {len(commits)} 个，开始还原到 {repo}:{branch}")

    # Git Data API 不接受空库（会 409）：先塞一个占位提交，
    # 最后用 force 把 main 指回真实历史，占位提交变成不可达对象
    try:
        api("GET", f"/repos/{repo}/commits?per_page=1", None, token)
    except urllib.error.HTTPError as e:
        if e.code in (404, 409):
            api("PUT", f"/repos/{repo}/contents/.gitkeep",
                {"message": "初始化仓库", "content": ""}, token)
            print("  空库已初始化")
        else:
            raise

    blob_cache = {}      # 本地 blob sha → GitHub 已上传 sha
    parent = None        # 上一个 GitHub commit sha
    for idx, sha in enumerate(commits, 1):
        meta = run("git", "log", "-1", "--format=%an%x00%ae%x00%aI%x00%cn%x00%ce%x00%cI%x00%B", sha).decode("utf-8")
        an, ae, ad, cn, ce, cd, msg = meta.split("\x00", 6)

        entries = []
        raw = run("git", "ls-tree", "-r", "-z", sha).decode("utf-8")
        for item in raw.split("\x00"):
            if not item:
                continue
            head, path = item.split("\t", 1)
            mode, otype, osha = head.split()
            if otype != "blob":
                continue
            if osha not in blob_cache:
                content = run("git", "cat-file", "blob", osha)
                blob_cache[osha] = api("POST", f"/repos/{repo}/git/blobs",
                                       {"content": base64.b64encode(content).decode(),
                                        "encoding": "base64"}, token)["sha"]
            entries.append({"path": path, "mode": mode, "type": "blob",
                            "sha": blob_cache[osha]})

        tree = api("POST", f"/repos/{repo}/git/trees",
                   {"tree": entries}, token)["sha"]
        commit = api("POST", f"/repos/{repo}/git/commits",
                     {"message": msg.rstrip(), "tree": tree,
                      "parents": [parent] if parent else [],
                      "author": {"name": an, "email": ae, "date": ad},
                      "committer": {"name": cn, "email": ce, "date": cd}}, token)["sha"]
        print(f"  [{idx}/{len(commits)}] {sha[:7]} → {commit[:7]} {msg.splitlines()[0][:40]}")
        parent = commit

    api("PATCH", f"/repos/{repo}/git/refs/heads/{branch}",
        {"sha": parent, "force": True}, token)
    # 默认分支设为 main
    api("PATCH", f"/repos/{repo}", {"default_branch": branch}, token)
    print(f"完成：{repo} 的 {branch} 已指向 {parent[:7]}")


if __name__ == "__main__":
    main()
