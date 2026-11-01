#!/usr/bin/env node
// 从 data/raw/articles/ 的原始 HTML 重新抽取纯文本（P6 收料管线第二步）
// 用法：node scripts/extract.mjs
//
// 为什么独立成脚本：爬取只负责把原始页面完整存档（一次），正文抽取规则可以
// 反复改进重跑（多次），互不牵连。manifest.json 由本脚本重建。
//
// 抽取规则：
//   1. 正文取 v_news_content 容器；容器内有嵌套 div，
//      用「<div> 开闭配对扫描」找到真正的结束位置（旧的截断 bug 根源）；
//   2. 去标签、还原实体、压缩空白；
//   3. 正文字数 < 60 的标记 thin=true（多半是图片流程图，文本天然少）。
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const RAW = path.join(ROOT, "data", "raw", "articles");
const OUT = path.join(ROOT, "data", "extracted");

// ===== 平衡配对：从 v_news_content 的开 <div> 扫到与之配对的 </div> =====
function extractContentDiv(html) {
  const start = html.search(/<div[^>]*v_news_content[^>]*>/i);
  if (start === -1) return null;
  const re = /<div\b[^>]*>|<\/div\s*>/gi;
  re.lastIndex = start;
  let depth = 0, token;
  while ((token = re.exec(html))) {
    if (token[0][1] === "/") {
      depth--;
      if (depth === 0) return html.slice(start, token.index + token[0].length);
    } else {
      depth++;
    }
  }
  return html.slice(start); // 页面不规范没闭合时，取到结尾兜底
}

function stripTags(s) {
  return s.replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, "\n")
    .replace(/&nbsp;/g, " ").replace(/&amp;/g, "&").replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">").replace(/&quot;/g, '"')
    .replace(/[ \t\u3000]+/g, " ")
    .replace(/\n\s*\n\s*\n+/g, "\n\n")
    .trim();
}

function extractArticle(html, url) {
  const title = (/<title>([^<]+)<\/title>/i.exec(html)?.[1] || "无标题")
    .replace(/-?信息公开网.*$/, "").replace(/-汕头大学.*$/, "").trim();
  const div = extractContentDiv(html);
  const body = div ? stripTags(div) : stripTags(html).slice(0, 8000);
  return { title, body };
}

// ===== 主流程 =====
fs.mkdirSync(OUT, { recursive: true });
const oldManifest = JSON.parse(fs.readFileSync(path.join(ROOT, "data", "manifest.json"), "utf-8"));
const catById = Object.fromEntries(oldManifest.articles.map((a) => [a.id, a.category]));

const articles = [];
for (const f of fs.readdirSync(RAW).filter((f) => f.endsWith(".htm"))) {
  const id = f.replace(".htm", "");
  const html = fs.readFileSync(path.join(RAW, f), "utf-8");
  const url = oldManifest.articles.find((a) => a.id === id)?.url
    ?? `https://info.stu.edu.cn/info/${id.replace("-", "/")}.htm`;
  const { title, body } = extractArticle(html, url);
  const text = `来源：${url}\n标题：${title}\n\n${body}`;
  fs.writeFileSync(path.join(OUT, id + ".txt"), text);
  articles.push({
    id, category: catById[id] || "未分类", title, url,
    chars: text.length, thin: body.length < 60,
    file: `data/extracted/${id}.txt`,
  });
}

articles.sort((a, b) => (a.category === b.category ? (a.id < b.id ? -1 : 1) : a.category < b.category ? -1 : 1));
const byCategory = {};
for (const a of articles) byCategory[a.category] = (byCategory[a.category] || 0) + 1;
const report = {
  source: oldManifest.source,
  crawledAt: oldManifest.crawledAt,
  extractedAt: new Date().toISOString(),
  totalArticles: articles.length,
  totalChars: articles.reduce((s, a) => s + a.chars, 0),
  thinCount: articles.filter((a) => a.thin).length,
  byCategory, articles,
};
fs.writeFileSync(path.join(ROOT, "data", "manifest.json"), JSON.stringify(report, null, 2));

console.log(`重抽取完成：${articles.length} 篇，共 ${report.totalChars} 字（thin 疑似图片页 ${report.thinCount} 篇）`);
for (const [cat, n] of Object.entries(byCategory)) console.log(`  ${cat}: ${n} 篇`);
const top = [...articles].sort((a, b) => b.chars - a.chars).slice(0, 5);
console.log("最长的 5 篇：");
for (const a of top) console.log(`  ${a.chars} 字  [${a.category}] ${a.title}`);
