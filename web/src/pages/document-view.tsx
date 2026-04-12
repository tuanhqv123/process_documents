import { useEffect, useState, useCallback, useRef } from "react";
import { Brain, X, RefreshCw, Zap, ChevronDown, ArrowLeft, GitFork, FileText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { OcrViewer } from "@/components/ocr-viewer";
import { GraphPage } from "@/pages/graph-page";
import { api } from "@/api/client";
import type { Document, OcrPageData } from "@/types";

interface DocumentViewProps {
  document: Document;
  onDocumentUpdated: (doc: Document) => void;
  onBack?: () => void;
}

type Tab = "ocr" | "graph"

export function DocumentView({
  document: doc,
  onDocumentUpdated,
  onBack,
}: DocumentViewProps) {
  const [ocrPages, setOcrPages] = useState<OcrPageData[]>([]);
  const [ocrLoaded, setOcrLoaded] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [extractingPage, setExtractingPage] = useState(false);
  const [training, setTraining] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  const [tab, setTab] = useState<Tab>("ocr");
  const onDocumentUpdatedRef = useRef(onDocumentUpdated);
  onDocumentUpdatedRef.current = onDocumentUpdated;
  const autoExtractedRef = useRef(false);

  const isExtracting = doc.status === "extracting";
  const isExtracted = doc.status === "extracted";
  const isReady = doc.status === "ready";
  const hasOcr = isExtracted || isReady;
  const canExtract = doc.status === "uploaded" || doc.status === "error";
  const canTrain = isExtracted || isReady;
  const totalPages = doc.page_count || doc.total_pages_ocr || 0;

  // Poll while extracting
  useEffect(() => {
    if (!isExtracting) return;
    let cancelled = false;
    let tid: number;
    const poll = async () => {
      if (cancelled) return;
      try {
        const updated = await api.extract.status(doc.id);
        if (cancelled) return;
        onDocumentUpdatedRef.current(updated);
        if (updated.status === "extracting")
          tid = window.setTimeout(poll, 2000);
        else {
          setOcrLoaded(false);
        }
      } catch {
        tid = window.setTimeout(poll, 3000);
      }
    };
    tid = window.setTimeout(poll, 2000);
    return () => {
      cancelled = true;
      clearTimeout(tid);
    };
  }, [doc.id, isExtracting]);

  // Load OCR pages
  useEffect(() => {
    if (!hasOcr || ocrLoaded) return;
    api.extract
      .ocrPages(doc.id)
      .then((data) => {
        setOcrPages(data.pages);
        setOcrLoaded(true);
      })
      .catch(console.error);
  }, [doc.id, hasOcr, ocrLoaded]);

  const handleExtractAll = useCallback(async () => {
    setExtracting(true);
    try {
      const updated = await api.extract.start(doc.id);
      onDocumentUpdatedRef.current(updated);
      setOcrLoaded(false);
      setOcrPages([]);
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Extraction failed");
    } finally {
      setExtracting(false);
    }
  }, [doc.id]);

  // Auto-extract when document is freshly uploaded
  useEffect(() => {
    if (doc.status === "uploaded" && !autoExtractedRef.current) {
      autoExtractedRef.current = true;
      handleExtractAll();
    }
  }, [doc.status, handleExtractAll]);

  const handleExtractPage = useCallback(async () => {
    setExtractingPage(true);
    try {
      const result = await api.extract.extractPage(doc.id, currentPage);
      setOcrPages((prev) =>
        prev.map((p) => (p.page === currentPage ? result.page_data : p)),
      );
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Page re-extract failed");
    } finally {
      setExtractingPage(false);
    }
  }, [doc.id, currentPage]);

  const handleCancelExtract = useCallback(async () => {
    await api.extract.cancel(doc.id);
  }, [doc.id]);

  const handleTrain = useCallback(async () => {
    setTraining(true);
    try {
      const updated = await api.extract.train(doc.id);
      onDocumentUpdatedRef.current(updated);
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Training failed");
    } finally {
      setTraining(false);
    }
  }, [doc.id]);

  return (
    <div className="flex flex-col h-full">
      {/* ── Toolbar ───────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 px-3 py-2 border-b shrink-0">
        {onBack && (
          <Button
            variant="ghost"
            size="sm"
            className="gap-1.5 text-muted-foreground shrink-0"
            onClick={onBack}
          >
            <ArrowLeft className="h-4 w-4" />
            Back
          </Button>
        )}
        {onBack && <div className="w-px h-4 bg-border shrink-0" />}

        {/* Re-extract dropdown */}
        {(hasOcr || canExtract) && !isExtracting && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="sm" variant="outline" className="gap-1.5" disabled={extracting || extractingPage}>
                {extracting || extractingPage ? (
                  <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Zap className="h-3.5 w-3.5" />
                )}
                {extracting ? "Extracting…" : extractingPage ? `Re-extracting p.${currentPage}…` : "Re-extract"}
                <ChevronDown className="h-3 w-3 ml-0.5" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              {hasOcr && (
                <DropdownMenuItem onClick={handleExtractPage} disabled={extractingPage}>
                  Current page
                </DropdownMenuItem>
              )}
              <DropdownMenuItem onClick={handleExtractAll} disabled={extracting}>
                All pages
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}

        {/* Cancel */}
        {isExtracting && (
          <Button size="sm" variant="ghost" className="gap-1.5 text-muted-foreground" onClick={handleCancelExtract}>
            <X className="h-3.5 w-3.5" /> Cancel
          </Button>
        )}

        {/* Train */}
        {canTrain && !isExtracting && (
          <Button size="sm" className="gap-1.5" onClick={handleTrain} disabled={training}>
            <Brain className="h-3.5 w-3.5" />
            {training ? "Training…" : isReady ? "Re-train" : "Train"}
          </Button>
        )}

        {/* Error */}
        {doc.error && (
          <span className="text-xs text-destructive ml-2 truncate">{doc.error}</span>
        )}

        {/* Progress */}
        {isExtracting && (
          <div className="flex items-center gap-2 ml-2 flex-1 min-w-0">
            <RefreshCw className="h-3 w-3 animate-spin text-muted-foreground shrink-0" />
            <span className="text-xs text-muted-foreground truncate">{doc.extract_message ?? "Extracting…"}</span>
            <span className="text-xs text-muted-foreground shrink-0">{doc.extracted_pages}/{totalPages}</span>
            <Progress value={doc.extract_progress} className="h-1 w-24 shrink-0" />
          </div>
        )}

        {/* Tab switcher */}
        {hasOcr && !isExtracting && (
          <div className="ml-auto flex items-center gap-1 border rounded-md p-0.5 bg-muted/40">
            <button
              onClick={() => setTab("ocr")}
              className={`flex items-center gap-1 px-2 py-1 rounded text-xs transition-colors ${
                tab === "ocr" ? "bg-background shadow-sm text-foreground" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <FileText className="h-3 w-3" /> OCR
            </button>
            <button
              onClick={() => setTab("graph")}
              className={`flex items-center gap-1 px-2 py-1 rounded text-xs transition-colors ${
                tab === "graph" ? "bg-background shadow-sm text-foreground" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <GitFork className="h-3 w-3" /> Graph
            </button>
          </div>
        )}
      </div>

      {/* ── Content ───────────────────────────────────────────────────────── */}
      <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
        {canExtract && !isExtracting && (
          <div className="flex flex-col items-center justify-center h-64 gap-3 text-muted-foreground">
            <Zap className="h-10 w-10 opacity-30" />
            <p className="text-sm">Starting extraction…</p>
          </div>
        )}

        {isExtracting && (
          <div className="flex flex-col items-center justify-center h-64 gap-3 text-muted-foreground">
            <RefreshCw className="h-8 w-8 opacity-40 animate-spin" />
            <p className="text-sm">{doc.extract_message ?? "Extracting…"}</p>
          </div>
        )}

        {hasOcr && tab === "ocr" && (
          <div className="flex-1 min-h-0 overflow-y-auto">
            {ocrLoaded ? (
              <OcrViewer
                docId={doc.id}
                pages={ocrPages}
                totalPages={totalPages}
                currentPage={currentPage}
                onPageChange={setCurrentPage}
                onPagesUpdated={setOcrPages}
              />
            ) : (
              <div className="flex items-center justify-center h-40">
                <RefreshCw className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            )}
          </div>
        )}

        {hasOcr && tab === "graph" && (
          <GraphPage docId={doc.id} docName={doc.filename} />
        )}
      </div>
    </div>
  );
}
