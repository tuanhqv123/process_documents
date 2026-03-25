import { useEffect, useState } from "react";
import { Database, FolderOpen, Plus, ArrowLeft } from "lucide-react";
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
import { DocumentView } from "@/pages/document-view";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { api } from "@/api/client";
import type { Document, Workspace } from "@/types";

type ActivePage = "dataset" | "workspace";

export default function App() {
  const [activePage, setActivePage] = useState<ActivePage>("dataset");
  const [documents, setDocuments] = useState<Document[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedDoc, setSelectedDoc] = useState<Document | null>(null);
  const [activeWorkspace, setActiveWorkspace] = useState<Workspace | null>(
    null,
  );
  const [loading, setLoading] = useState(true);

  // Create workspace dialog
  const [showCreateWs, setShowCreateWs] = useState(false);
  const [newWsName, setNewWsName] = useState("");
  const [creatingWs, setCreatingWs] = useState(false);

  useEffect(() => {
    Promise.all([api.documents.list(), api.workspaces.list()])
      .then(([docs, wss]) => {
        setDocuments(docs);
        setWorkspaces(wss);
      })
      .finally(() => setLoading(false));
  }, []);

  // ── Handlers ────────────────────────────────────────────────────────────────

  const handleDocumentAdded = (doc: Document) => {
    setDocuments((prev) => [doc, ...prev]);
    setSelectedDoc(doc);
    setActivePage("dataset");
  };

  const handleDocumentDeleted = (id: number) => {
    setDocuments((prev) => prev.filter((d) => d.id !== id));
    if (selectedDoc?.id === id) setSelectedDoc(null);
  };

  const handleDocumentUpdated = (updated: Document) => {
    setDocuments((prev) =>
      prev.map((d) => (d.id === updated.id ? updated : d)),
    );
    if (selectedDoc?.id === updated.id) setSelectedDoc(updated);
  };

  const handleSelectWorkspace = (ws: Workspace) => {
    setActiveWorkspace(ws);
    setActivePage("workspace");
    setSelectedDoc(null);
  };

  const handleCreateWorkspace = async () => {
    if (!newWsName.trim()) return;
    setCreatingWs(true);
    try {
      const ws = await api.workspaces.create(newWsName.trim());
      setWorkspaces((prev) => [ws, ...prev]);
      setActiveWorkspace(ws);
      setActivePage("workspace");
      setNewWsName("");
      setShowCreateWs(false);
    } finally {
      setCreatingWs(false);
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
      setActivePage("dataset");
    }
  };

  // ── Breadcrumb ──────────────────────────────────────────────────────────────

  const breadcrumb = (() => {
    if (activePage === "dataset") {
      return selectedDoc
        ? [
            {
              icon: <Database className="h-4 w-4" />,
              label: "Dataset",
              onClick: () => setSelectedDoc(null),
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
            activePage={activePage}
            activeWorkspaceId={activeWorkspace?.id ?? null}
            workspaces={workspaces}
            onSelectDataset={() => {
              setActivePage("dataset");
              setSelectedDoc(null);
            }}
            onSelectWorkspace={handleSelectWorkspace}
            onCreateWorkspace={() => setShowCreateWs(true)}
          />

          <SidebarInset>
            {/* Header */}
            <header className="flex h-14 shrink-0 items-center gap-2 border-b px-4">
              <SidebarTrigger className="-ml-1" />
              <Separator orientation="vertical" className="" />

              {/* Breadcrumb */}
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

              <ModeToggle />
            </header>

            {/* Main content */}
            <div className="flex flex-1 overflow-hidden">
              {activePage === "dataset" ? (
                selectedDoc ? (
                  <div className="flex-1 flex flex-col overflow-hidden">
                    <div className="px-6 pt-3 pb-0 shrink-0">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="gap-1.5 -ml-2 text-muted-foreground"
                        onClick={() => setSelectedDoc(null)}
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
                      selectedDocId={null}
                      onSelectDoc={setSelectedDoc}
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
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setShowCreateWs(true)}
                      >
                        <Plus className="h-4 w-4 mr-1" /> New Workspace
                      </Button>
                    </div>
                  )}
                </div>
              )}
            </div>
          </SidebarInset>

          {/* Create workspace dialog */}
          <Dialog open={showCreateWs} onOpenChange={setShowCreateWs}>
            <DialogContent className="sm:max-w-sm">
              <DialogHeader>
                <DialogTitle>New Workspace</DialogTitle>
                <DialogDescription>
                  Group documents together for a specific project or topic.
                </DialogDescription>
              </DialogHeader>
              <Input
                placeholder="Workspace name"
                value={newWsName}
                onChange={(e) => setNewWsName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleCreateWorkspace()}
                autoFocus
              />
              <div className="flex justify-end gap-2">
                <Button
                  variant="outline"
                  onClick={() => setShowCreateWs(false)}
                >
                  Cancel
                </Button>
                <Button
                  onClick={handleCreateWorkspace}
                  disabled={!newWsName.trim() || creatingWs}
                >
                  {creatingWs ? "Creating…" : "Create"}
                </Button>
              </div>
            </DialogContent>
          </Dialog>
        </SidebarProvider>
      </TooltipProvider>
    </ThemeProvider>
  );
}
