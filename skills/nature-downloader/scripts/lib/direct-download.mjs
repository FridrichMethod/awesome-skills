import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { classifyFullTextContent } from "./provider-utils.mjs";

export function safeArticleBasename(title = "", doi = "") {
  const base = String(title || doi || "article")
    .trim()
    .replace(/[\/:*?"<>|]+/g, "")
    .replace(/\s+/g, "_")
    .slice(0, 140);
  return base || "article";
}

// Titles are not unique ("Editorial", or the "article" fallback), so a second paper must not
// replace the first. Reuse the file only when its bytes are identical; otherwise add -2, -3, ...
function uniqueFullTextPath(directory, basename, extension, sha256) {
  for (let suffix = 1; ; suffix += 1) {
    const candidate = path.join(directory, `${basename}${suffix === 1 ? "" : `-${suffix}`}${extension}`);
    if (!fs.existsSync(candidate)) return candidate;
    const existing = crypto.createHash("sha256").update(fs.readFileSync(candidate)).digest("hex");
    if (existing === sha256) return candidate;
  }
}

export async function saveFullTextResponse(response, { outDir, title = "", doi = "", source = "" } = {}) {
  if (!response.ok) return { ok: false, httpStatus: response.status };
  const body = Buffer.from(await response.arrayBuffer());
  const contentType = response.headers.get("content-type") || "";
  const classification = classifyFullTextContent({ contentType, head: body.subarray(0, 65536) });
  if (!classification.valid) return { ok: false, httpStatus: response.status, contentType, ...classification };
  const folder = classification.format === "pdf" ? "PDFs" : "FullText";
  const sha256 = crypto.createHash("sha256").update(body).digest("hex");
  fs.mkdirSync(path.join(outDir, folder), { recursive: true });
  const file = uniqueFullTextPath(path.join(outDir, folder), safeArticleBasename(title, doi), classification.extension, sha256);
  if (!fs.existsSync(file)) {
    const temp = `${file}.part-${process.pid}`;
    fs.writeFileSync(temp, body);
    fs.renameSync(temp, file);
  }
  return {
    ok: true,
    file,
    bytes: body.length,
    sha256,
    contentType,
    format: classification.format,
    source: source || response.url || "",
  };
}
