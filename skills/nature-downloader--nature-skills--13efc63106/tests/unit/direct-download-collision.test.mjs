import { describe, test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { saveFullTextResponse } from "../../scripts/lib/direct-download.mjs";

function pdfResponse(text) {
  const body = Buffer.from(`%PDF-1.4\n${text}\n%%EOF\n`);
  return new Response(body, { status: 200, headers: { "content-type": "application/pdf" } });
}

describe("saved full-text filenames", () => {
  test("a different paper with the same title does not overwrite the first", async () => {
    const outDir = fs.mkdtempSync(path.join(os.tmpdir(), "direct-download-"));
    const first = await saveFullTextResponse(pdfResponse("paper one"), { outDir, title: "Editorial" });
    const second = await saveFullTextResponse(pdfResponse("paper two"), { outDir, title: "Editorial" });
    assert.equal(first.ok, true);
    assert.equal(second.ok, true);
    assert.notEqual(first.file, second.file);
    assert.match(fs.readFileSync(first.file, "utf8"), /paper one/);
    assert.match(fs.readFileSync(second.file, "utf8"), /paper two/);
  });

  test("the same content saved twice reuses one file", async () => {
    const outDir = fs.mkdtempSync(path.join(os.tmpdir(), "direct-download-"));
    const first = await saveFullTextResponse(pdfResponse("same"), { outDir, title: "Same Paper" });
    const second = await saveFullTextResponse(pdfResponse("same"), { outDir, title: "Same Paper" });
    assert.equal(first.file, second.file);
    assert.equal(fs.readdirSync(path.join(outDir, "PDFs")).length, 1);
  });

  test("no temporary part files are left behind", async () => {
    const outDir = fs.mkdtempSync(path.join(os.tmpdir(), "direct-download-"));
    await saveFullTextResponse(pdfResponse("a"), { outDir, title: "T" });
    await saveFullTextResponse(pdfResponse("b"), { outDir, title: "T" });
    assert.deepEqual(fs.readdirSync(path.join(outDir, "PDFs")).filter((f) => f.includes(".part-")), []);
  });
});
