import { useEffect, useState, useCallback } from "react";
import { Database, FolderOpen, ArrowLeft, Activity, Wifi } from "lucide-react";
import { BrowserRouter, Routes, Route, useNavigate, useLocation } from "react-router-dom";
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { Separator } from "@/components/ui/separator";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ThemeProvider } from "@/components/theme-provider";
import { AppSidebar } from "@/components/app-sidebar";
import { ModeToggle } from "@/components/mode-toggle";
import { DatasetPage } from "@/pages/dataset-page";
import { WorkspacePage } from "@/pages/workspace-page";
import { RealtimePage } from "@/pages/realtime-page";
import { DocumentView } from "@/pages/document-view";
import { Button } from "@/components/ui/button";
import { api } from "@/api/client";
import type { Document, Workspace } from "@/types";

function AppContent() {
  const navigate = useNavigate();
  const location = useLocation();
  const [documents, setDocuments] = useState<Document[]>([]);
  const [realtimeKey, setRealtimeKey] = useState(0);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedDoc, setSelectedDoc] = useState<Document | null>(null);
  const [activeWorkspace, setActiveWorkspace] = useState<Workspace | null>(
    null,
  );
  const [loading, setLoading] = useState(true);

  const isRealtime = location.pathname === "/monitor";
  const isDataset = location.pathname === "/dataset" || location.pathname.startsWith("/dataset/");
  const isWorkspace = location.pathname === "/workspace" || location.pathname.startsWith("/workspace/");

  useEffect(() => {
    Promise.all([api.documents.list(), api.workspaces.list()])
      .then(([docs, wss]) => {
        setDocuments(docs);
        setWorkspaces(wss);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const docId = location.pathname.match(/^\/dataset\/(\d+)$/)?.[1];
    if (docId && documents.length > 0) {
      const doc = documents.find(d => d.id === parseInt(docId));
      if (doc) setSelectedDoc(doc);
    }
  }, [location.pathname, documents]);

  useEffect(() => {
    const wsId = location.pathname.match(/^\/workspace\/(\d+)$/)?.[1];
    if (wsId && workspaces.length > 0) {
      const ws = workspaces.find(w => w.id === parseInt(wsId));
      if (ws) setActiveWorkspace(ws);
    }
  }, [location.pathname, workspaces]);

  const handleDocumentAdded = (doc: Document) => {
    setDocuments((prev) => [doc, ...prev]);
    setSelectedDoc(doc);
    navigate(`/dataset/${doc.id}`);
  };

  const handleDocumentDeleted = (id: number) => {
    setDocuments((prev) => prev.filter((d) => d.id !== id));
    if (selectedDoc?.id === id) {
      setSelectedDoc(null);
      navigate("/dataset");
    }
  };

  const handleDocumentUpdated = useCallback((updated: Document) => {
    setDocuments((prev) =>
      prev.map((d) => (d.id === updated.id ? updated : d)),
    );
    if (selectedDoc?.id === updated.id) setSelectedDoc(updated);
  }, [selectedDoc?.id]);

  const handleSelectWorkspace = (ws: Workspace) => {
    setActiveWorkspace(ws);
    setSelectedDoc(null);
    navigate(`/workspace/${ws.id}`);
  };

  const handleCreateWorkspace = async (name: string, onSuccess: () => void) => {
    if (!name.trim()) return;
    try {
      const ws = await api.workspaces.create(name.trim());
      setWorkspaces((prev) => [ws, ...prev]);
      setActiveWorkspace(ws);
      navigate(`/workspace/${ws.id}`);
      onSuccess();
    } catch (e) {
      console.error("Failed to create workspace:", e);
    }
  };

  const handleWorkspaceUpdated = (ws: Workspace) => {
    setWorkspaces((prev) => prev.map((w) => (w.id === ws.id ? ws : w)));
    if (activeWorkspace?.id === ws.id) setActiveWorkspace(ws);
  };

  const handleWorkspaceDeleted = (id: number) => {
    setWorkspaces((prev) => prev.filter((w) => w.id !== id));
    if (activeWorkspace?.id === id) {
      setActiveWorkspace(null);
      navigate("/workspace");
    }
  };

  const breadcrumb = (() => {
    if (isRealtime) {
      return [{ icon: <Activity className="h-4 w-4" />, label: "Real-time Monitor" }];
    }
    if (isDataset) {
      return selectedDoc
        ? [
            {
              icon: <Database className="h-4 w-4" />,
              label: "Dataset",
              onClick: () => { setSelectedDoc(null); navigate("/dataset"); },
            },
            { label: selectedDoc.filename },
          ]
        : [{ icon: <Database className="h-4 w-4" />, label: "Dataset" }];
    }
    return [
      { icon: <FolderOpen className="h-4 w-4" />, label: "Workspaces" },
      { label: activeWorkspace?.name ?? "" },
    ];
  })();

  if (loading) {
    return (
      <ThemeProvider defaultTheme="system" storageKey="kb-theme">
        <div className="flex items-center justify-center h-screen text-muted-foreground text-sm">
          Loading…
        </div>
      </ThemeProvider>
    );
  }

  return (
    <ThemeProvider defaultTheme="system" storageKey="kb-theme">
      <TooltipProvider>
        <SidebarProvider>
          <AppSidebar
            activePage={isRealtime ? "realtime" : isDataset ? "dataset" : isWorkspace ? "workspace" : null}
            activeWorkspaceId={activeWorkspace?.id ?? null}
            workspaces={workspaces}
            onSelectDataset={() => { setSelectedDoc(null); navigate("/dataset"); }}
            onSelectWorkspace={handleSelectWorkspace}
            onSelectRealtime={() => { setRealtimeKey(k => k + 1); navigate("/monitor"); }}
            onCreateWorkspace={() => {}}
            workspacesLoading={loading}
            onCreateWorkspaceDialog={(open) => {
              if (open) {
                const name = prompt("Workspace name:");
                if (name) handleCreateWorkspace(name, () => {});
              }
            }}
          />

          <SidebarInset>
            <header className="flex h-14 shrink-0 items-center gap-2 border-b px-4">
              <SidebarTrigger className="-ml-1" />
              <Separator orientation="vertical" className="" />

              <nav className="flex flex-1 items-center gap-1.5 text-sm min-w-0">
                {breadcrumb.map((crumb, i) => (
                  <span key={i} className="flex items-center gap-1.5">
                    {i > 0 && <span className="text-muted-foreground">/</span>}
                    {crumb.icon}
                    <span
                      className={
                        i === breadcrumb.length - 1
                          ? "font-medium truncate max-w-xs"
                          : "text-muted-foreground truncate max-w-xs cursor-pointer hover:text-foreground"
                      }
                      onClick={"onClick" in crumb ? crumb.onClick : undefined}
                    >
                      {crumb.label}
                    </span>
                  </span>
                ))}
              </nav>

              {isRealtime && (
                <div className="flex items-center gap-2 text-xs text-muted-foreground mr-2">
                  <span>esp32-001</span>
                  <Wifi className="h-3 w-3 text-green-500" />
                </div>
              )}

              <ModeToggle />
            </header>

            <div className="flex flex-1 overflow-hidden">
              {isRealtime ? (
                <div className="flex-1 overflow-hidden">
                  <RealtimePage key={realtimeKey} />
                </div>
              ) : isDataset ? (
                selectedDoc ? (
                  <div className="flex-1 flex flex-col overflow-hidden">
                    <div className="px-6 pt-3 pb-0 shrink-0">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="gap-1.5 -ml-2 text-muted-foreground"
                        onClick={() => { setSelectedDoc(null); navigate("/dataset"); }}
                      >
                        <ArrowLeft className="h-4 w-4" />
                        Back to Dataset
                      </Button>
                    </div>
                    <div className="flex-1 overflow-y-auto">
                      <DocumentView
                        document={selectedDoc}
                        onDocumentUpdated={handleDocumentUpdated}
                      />
                    </div>
                  </div>
                ) : (
                  <div className="flex-1 overflow-y-auto">
                    <DatasetPage
                      documents={documents}
                      selectedDocId={(selectedDoc as Document | null)?.id ?? null}
                      onSelectDoc={(doc) => { setSelectedDoc(doc); navigate(`/dataset/${doc.id}`); }}
                      onDocumentAdded={handleDocumentAdded}
                      onDocumentDeleted={handleDocumentDeleted}
                      onDocumentUpdated={handleDocumentUpdated}
                    />
                  </div>
                )
              ) : (
                <div className="flex-1 overflow-y-auto">
                  {activeWorkspace ? (
                    <WorkspacePage
                      workspace={activeWorkspace}
                      allDocuments={documents}
                      onWorkspaceUpdated={handleWorkspaceUpdated}
                      onWorkspaceDeleted={handleWorkspaceDeleted}
                    />
                  ) : (
                    <div className="flex flex-col items-center justify-center h-full gap-3 text-muted-foreground">
                      <FolderOpen className="h-12 w-12" />
                      <p className="text-sm">
                        Select a workspace from the sidebar
                      </p>
                    </div>
                  )}
                </div>
              )}
            </div>
          </SidebarInset>
        </SidebarProvider>
      </TooltipProvider>
    </ThemeProvider>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/dataset" element={<AppContent />} />
        <Route path="/dataset/:id" element={<AppContent />} />
        <Route path="/workspace" element={<AppContent />} />
        <Route path="/workspace/:id" element={<AppContent />} />
        <Route path="/monitor" element={<AppContent />} />
        <Route path="*" element={<AppContent />} />
      </Routes>
    </BrowserRouter>
  );
}
