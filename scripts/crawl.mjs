#!/usr/bin/env node
// 汕头大学信息公开网·学校办事指南 收料爬虫（P6 知识库产品）
// 用法：node scripts/crawl.mjs
//
// 安全约定（硬性）：
//   1. 只发 https 请求；
//   2. 每个请求前校验 host，必须精确等于 info.stu.edu.cn，
//      其余（localhost/环回/内网 IP/其他域）一律拒绝；
//   3. 只跟随从办事指南栏目页内发现的链接，不爬全站。
//
// 产出：
//   data/raw/lists/      分类列表页原始 HTML（存档）
//   data/raw/articles/   文章页原始 HTML（按 栏目ID-文章ID 命名，可重跑增量续抓）
//   data/extracted/      纯文本（UTF-8，带来源头）
//   data/manifest.json   收料清单与统计
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const RAW_LISTS = path.join(ROOT, "data", "raw", "lists");
const RAW_ARTICLES = path.join(ROOT, "data", "raw", "articles");
const EXTRACTED = path.join(ROOT, "data", "extracted");

for (const d of [RAW_LISTS, RAW_ARTICLES, EXTRACTED]) fs.mkdirSync(d, { recursive: true });

// ===== 安全 URL 校验：https + host 白名单 =====
const ALLOW_HOST = "info.stu.edu.cn";
function safeUrl(href, base) {
  let u;
  try { u = new URL(href, base); } catch { return null; }
  if (u.protocol !== "https:") return null;          // 仅 https
  if (u.hostname !== ALLOW_HOST) return null;        // host 白名单，其余全拒
  if (u.port && u.port !== "443") return null;
  if (!/\.htm[l]?$/.test(u.pathname)) return null;   // 只收网页
  return u;
}

// ===== 种子：办事指南 17 个分类页（来自首页导航提取） =====
const SEEDS = [
  ["综合管理", "zhgl.htm"], ["行政工作", "xzgz.htm"], ["组织工作", "zzgz.htm"],
  ["宣传工作", "xcgz.htm"], ["纪检监察工作", "jjjcgz.htm"], ["工会工作", "ghgz.htm"],
  ["教学管理", "jxgl.htm"], ["科学研究", "kxyj.htm"], ["人事工作", "rsgz.htm"],
  ["学生工作", "xsgz.htm"], ["资产管理", "zcgl.htm"], ["财务管理", "cwgl.htm"],
  ["后勤基建", "hqjj.htm"], ["审计工作", "sjgz.htm"], ["安全管理", "aqgl.htm"],
  ["对外交流与合作", "dwjlyhz.htm"], ["校友工作", "xygz.htm"],
].map(([cat, f]) => ({ cat, url: `https://${ALLOW_HOST}/xxgk1/xxbszn/${f}` }));

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ===== 带重试的抓取（自动识别 charset） =====
async function fetchPage(url, tries = 2) {
  for (let i = 0; i < tries; i++) {
    try {
      const resp = await fetch(url, {
        headers: { "User-Agent": "Mozilla/5.0 (compatible; p6-kb-collector/1.0)" }, // HTTP 头只能用 ASCII
        signal: AbortSignal.timeout(20000),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const buf = Buffer.from(await resp.arrayBuffer());
      let charset = /charset=([\w-]+)/i.exec(resp.headers.get("content-type") || "")?.[1]
        || /charset=["']?([\w-]+)/i.exec(buf.slice(0, 2000).toString("latin1"))?.[1] || "utf-8";
      charset = charset.toLowerCase();
      let html;
      try { html = new TextDecoder(charset === "gb2312" ? "gbk" : charset).decode(buf); }
      catch { html = buf.toString("utf-8"); }
      return html;
    } catch (err) {
      if (i === tries - 1) throw err;
      await sleep(1500); // 失败重试前等一等
    }
  }
}

// ===== HTML 提取 =====
function extractLinks(html) {
  const out = [];
  const re = /<a[^>]+href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/gi;
  let m;
  while ((m = re.exec(html))) {
    const text = m[2].replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim();
    out.push({ href: m[1], text });
  }
  return out;
}

function stripTags(s) {
  return s.replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, "\n")
    .replace(/&nbsp;/g, " ").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"')
    .replace(/[ \t\u3000]+/g, " ")
    .replace(/\n\s*\n\s*\n+/g, "\n\n")
    .trim();
}

function extractArticle(html, url) {
  const title = (/<title>([^<]+)<\/title>/i.exec(html)?.[1] || "无标题")
    .replace(/-?信息公开网.*$/, "").replace(/-汕头大学.*$/, "").trim();
  // VSB 正文通常在 v_news_content 容器里；取不到就退化为整页去头尾
  const m = /<div[^>]*class="[^"]*v_news_content[^"]*"[^>]*>([\s\S]*?)<\/div>\s*(?:<div|<\/td|<!--)/i.exec(html);
  const body = m ? stripTags(m[1]) : stripTags(html).slice(0, 8000);
  return { title, text: `来源：${url}\n标题：${title}\n\n${body}` };
}

// ===== 主循环：列表页 BFS → 文章页落盘 =====
const isArticle = (u) => /\/info\/\d+\/\d+\.htm[l]?$/.test(u.pathname);

const queue = SEEDS.map((s) => ({ ...s, kind: "list" }));
const seen = new Set();
const manifest = [];
const errors = [];

while (queue.length) {
  const item = queue.shift();
  if (seen.has(item.url)) continue;
  seen.add(item.url);

  let html;
  try { html = await fetchPage(item.url); }
  catch (err) { errors.push(`${item.url}  ${err.message}`); continue; }

  if (item.kind === "list") {
    // 列表页存档
    const fname = item.url.replace(/^.*\/xxbszn\//, "").replace(/[/?=]/g, "_");
    fs.writeFileSync(path.join(RAW_LISTS, fname), html);
    for (const { href } of extractLinks(html)) {
      const u = safeUrl(href, item.url);
      if (!u) continue;
      if (isArticle(u)) queue.push({ cat: item.cat, url: u.href, kind: "article" });
      else if (u.pathname.startsWith("/xxgk1/xxbszn/")) queue.push({ cat: item.cat, url: u.href, kind: "list" }); // 子栏目/翻页
    }
  } else {
    // 文章页：文件名用 栏目ID-文章ID，天然去重、可断点续抓
    const idm = item.url.match(/\/info\/(\d+)\/(\d+)\.htm/);
    const fname = `${idm[1]}-${idm[2]}.htm`;
    const rawPath = path.join(RAW_ARTICLES, fname);
    let { title, text } = extractArticle(html, item.url);
    if (fs.existsSync(rawPath)) continue; // 已抓过（重跑增量）
    fs.writeFileSync(rawPath, html);
    const txtPath = path.join(EXTRACTED, fname.replace(".htm", ".txt"));
    fs.writeFileSync(txtPath, text);
    manifest.push({
      id: fname.replace(".htm", ""), category: item.cat, title,
      url: item.url, chars: text.length,
      file: path.relative(ROOT, txtPath).replaceAll("\\", "/"),
    });
  }
  await sleep(350); // 礼貌延迟，别给学校服务器添堵
}

// ===== 清单与统计 =====
manifest.sort((a, b) => (a.category === b.category ? a.id < b.id ? -1 : 1 : a.category < b.category ? -1 : 1));
const stats = {};
for (const a of manifest) stats[a.category] = (stats[a.category] || 0) + 1;
const report = {
  source: "汕头大学信息公开网·学校办事指南",
  crawledAt: new Date().toISOString(),
  totalArticles: manifest.length,
  totalChars: manifest.reduce((s, a) => s + a.chars, 0),
  byCategory: stats,
  errors,
  articles: manifest,
};
fs.writeFileSync(path.join(ROOT, "data", "manifest.json"), JSON.stringify(report, null, 2));

console.log(`收料完成：${manifest.length} 篇文章，共 ${report.totalChars} 字`);
for (const [cat, n] of Object.entries(stats)) console.log(`  ${cat}: ${n} 篇`);
if (errors.length) console.log(`失败 ${errors.length} 个请求：\n  ` + errors.join("\n  "));
