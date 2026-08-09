export interface DocumentPreviewExtraction {
  text: string;
  fileName: string;
  fileType: "pdf" | "word" | "text";
  pageCount?: number;
  pageWordCounts?: number[];
  emptyPages?: number[];
  wordCount: number;
  ocrPages: number[];
  tables: ExtractedTable[];
  images: ExtractedImage[];
  warnings: string[];
}

export interface ExtractedTable {
  page: number;
  rows: string[][];
}

export interface ExtractedImage {
  page: number;
  count: number;
  note: string;
}

export interface PreviewExtractionOptions {
  onProgress?: (message: string) => void;
  ocrLanguages?: string;
}

function countWords(text: string): number {
  return text.match(/[\p{L}\p{M}\p{N}][\p{L}\p{M}\p{N}'/-]*/gu)?.length ?? 0;
}

function cleanText(text: string): string {
  return text
    .split(String.fromCharCode(0)).join("")
    .replace(/[ \t]+/g, " ")
    .replace(/\n[ \t]+/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function groupTextRows(items: { text: string; x: number; y: number }[]): string[][] {
  const rows: { y: number; cells: { x: number; text: string }[] }[] = [];
  for (const item of items) {
    const row = rows.find((candidate) => Math.abs(candidate.y - item.y) <= 3);
    if (row) row.cells.push({ x: item.x, text: item.text });
    else rows.push({ y: item.y, cells: [{ x: item.x, text: item.text }] });
  }
  return rows
    .sort((a, b) => b.y - a.y)
    .map((row) => row.cells.sort((a, b) => a.x - b.x).map((cell) => cell.text))
    .filter((row) => row.length >= 3);
}

function groupTextLines(items: { text: string; x: number; y: number }[]): string[] {
  const lines: { y: number; cells: { x: number; text: string }[] }[] = [];
  for (const item of items) {
    const line = lines.find((candidate) => Math.abs(candidate.y - item.y) <= 3);
    if (line) line.cells.push({ x: item.x, text: item.text });
    else lines.push({ y: item.y, cells: [{ x: item.x, text: item.text }] });
  }
  return lines
    .sort((a, b) => b.y - a.y)
    .map((line) => line.cells.sort((a, b) => a.x - b.x).map((cell) => cell.text).join(" ").trim())
    .filter(Boolean);
}

async function ocrPdfPage(page: PDFPageProxy, languages: string): Promise<string> {
  const { createWorker } = await import("tesseract.js");
  const viewport = page.getViewport({ scale: 1.8 });
  const canvas = document.createElement("canvas");
  canvas.width = Math.ceil(viewport.width);
  canvas.height = Math.ceil(viewport.height);
  const context = canvas.getContext("2d");
  if (!context) return "";
  await page.render({ canvasContext: context, canvas, viewport }).promise;
  const worker = await createWorker(languages);
  try {
    const result = await worker.recognize(canvas);
    return cleanText(result.data.text);
  } finally {
    await worker.terminate();
  }
}

async function extractPdf(file: File, options: PreviewExtractionOptions): Promise<DocumentPreviewExtraction> {
  const pdfjs = await import("pdfjs-dist");
  pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();
  const data = new Uint8Array(await file.arrayBuffer());
  const pdf = await pdfjs.getDocument({ data }).promise;
  const pages: string[] = [];
  const pageWordCounts: number[] = [];
  const emptyPages: number[] = [];
  const ocrPages: number[] = [];
  const tables: ExtractedTable[] = [];
  const images: ExtractedImage[] = [];
  const ocrLanguages = options.ocrLanguages ?? "eng";

  for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
    options.onProgress?.(`Examining PDF page ${pageNumber} of ${pdf.numPages}...`);
    const page = await pdf.getPage(pageNumber);
    const content = await page.getTextContent();
    const positionedItems = content.items
      .filter((item): item is typeof item & { str: string; transform: number[] } => "str" in item && "transform" in item && Boolean(item.str.trim()))
      .map((item) => ({ text: item.str.trim(), x: item.transform[4], y: item.transform[5] }));
    let cleanedPage = cleanText(groupTextLines(positionedItems).join("\n"));
    if (countWords(cleanedPage) < 20) {
      options.onProgress?.(`Running ${ocrLanguages.includes("hin") ? "Hindi and English " : ""}OCR on scanned page ${pageNumber} of ${pdf.numPages}...`);
      let ocrText = "";
      try {
        ocrText = await ocrPdfPage(page, ocrLanguages);
      } catch (error) {
        if (!ocrLanguages.includes("hin")) throw error;
        options.onProgress?.(`Hindi OCR could not start on page ${pageNumber}; retrying with English OCR...`);
        ocrText = await ocrPdfPage(page, "eng");
      }
      if (countWords(ocrText) > countWords(cleanedPage)) {
        cleanedPage = ocrText;
        ocrPages.push(pageNumber);
      }
    }
    const wordCount = countWords(cleanedPage);
    pageWordCounts.push(wordCount);
    if (wordCount < 20) emptyPages.push(pageNumber);
    const tableRows = groupTextRows(positionedItems);
    if (tableRows.length >= 2) tables.push({ page: pageNumber, rows: tableRows.slice(0, 40) });
    const operatorList = await page.getOperatorList();
    const imageCount = operatorList.fnArray.filter((operator: number) =>
      operator === pdfjs.OPS.paintImageXObject
      || operator === pdfjs.OPS.paintInlineImageXObject
      || operator === pdfjs.OPS.paintImageMaskXObject
    ).length;
    if (imageCount) images.push({ page: pageNumber, count: imageCount, note: "Raster image or scanned diagram detected; visual meaning requires reviewer confirmation." });
    pages.push(`[PAGE ${pageNumber}]\n${cleanedPage}`);
  }

  const text = cleanText(pages.join("\n\n"));
  const wordCount = countWords(text);
  const warnings: string[] = [];
  if (wordCount < 250) warnings.push("The file contains too little extractable text for a thorough proposal evaluation.");
  if (emptyPages.length) warnings.push(`${emptyPages.length} page(s) contain fewer than 20 extractable words and may be scanned, blank, or image-heavy.`);
  if (pdf.numPages && wordCount / pdf.numPages < 80) warnings.push("Average extractable text per page is low. OCR may be required.");
  if (ocrPages.length) warnings.push(`OCR was used on ${ocrPages.length} page(s); verify critical numbers and names against the original scan.`);
  if (ocrPages.length && ocrLanguages.includes("hin")) warnings.push("Hindi OCR was enabled; verify matras, names, statistical symbols, and mixed Hindi-English terminology.");
  if (images.length) warnings.push(`${images.reduce((sum, image) => sum + image.count, 0)} image object(s) were inventoried for reviewer inspection.`);
  return {
    text,
    fileName: file.name,
    fileType: "pdf",
    pageCount: pdf.numPages,
    pageWordCounts,
    emptyPages,
    wordCount,
    ocrPages,
    tables,
    images,
    warnings,
  };
}

async function extractWord(file: File): Promise<DocumentPreviewExtraction> {
  if (file.name.toLowerCase().endsWith(".doc")) {
    throw new Error("Legacy .doc files are not supported for text extraction. Save the proposal as .docx or PDF.");
  }
  const mammoth = await import("mammoth/mammoth.browser");
  const result = await mammoth.extractRawText({ arrayBuffer: await file.arrayBuffer() });
  const text = cleanText(result.value);
  const wordCount = countWords(text);
  const warnings = result.messages.map((message: { message: string }) => message.message);
  if (wordCount < 250) warnings.push("The file contains too little extractable text for a thorough proposal evaluation.");
  return {
    text,
    fileName: file.name,
    fileType: "word",
    wordCount,
    ocrPages: [],
    tables: [],
    images: [],
    warnings,
  };
}

// Preview only. The backend independently downloads, validates, extracts, and
// stores document text before evaluation. Do not send this text to the API.
export async function extractDocumentPreview(file: File, options: PreviewExtractionOptions = {}): Promise<DocumentPreviewExtraction> {
  const name = file.name.toLowerCase();
  if (name.endsWith(".pdf") || file.type === "application/pdf") return extractPdf(file, options);
  if (name.endsWith(".docx") || name.endsWith(".doc")) return extractWord(file);
  if (file.type.startsWith("text/") || name.endsWith(".txt") || name.endsWith(".md")) {
    const text = cleanText(await file.text());
    const wordCount = countWords(text);
    return {
      text,
      fileName: file.name,
      fileType: "text",
      wordCount,
      ocrPages: [],
      tables: [],
      images: [],
      warnings: wordCount < 250 ? ["The file contains too little text for a thorough proposal evaluation."] : [],
    };
  }
  throw new Error("Unsupported document type. Upload PDF, DOCX, TXT, or Markdown.");
}
import type { PDFPageProxy } from "pdfjs-dist";
