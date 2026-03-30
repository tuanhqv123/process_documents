import * as React from "react";
import {
  Database,
  FolderOpen,
  BookOpen,
  ChevronRight,
  Plus,
  Activity,
} from "lucide-react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@/components/ui/sidebar";
import type { Workspace } from "@/types";

interface AppSidebarProps extends React.ComponentProps<typeof Sidebar> {
  activePage: "dataset" | "workspace" | "realtime" | null;
  activeWorkspaceId: number | null;
  workspaces: Workspace[];
  workspacesLoading?: boolean;
  onSelectDataset: () => void;
  onSelectWorkspace: (ws: Workspace) => void;
  onSelectRealtime: () => void;
  onCreateWorkspace: () => void;
  onCreateWorkspaceDialog?: (open: boolean) => void;
}

export function AppSidebar({
  activePage,
  activeWorkspaceId,
  workspaces,
  onSelectDataset,
  onSelectWorkspace,
  onSelectRealtime,
  onCreateWorkspace,
  ...props
}: AppSidebarProps) {
  return (
    <Sidebar {...props}>
      {/* Logo */}
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild>
              <div className="flex items-center gap-2 cursor-default select-none">
                <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                  <BookOpen className="size-4" />
                </div>
                <div className="flex flex-col gap-0.5 leading-none">
                  <span className="font-semibold text-sm">Knowledge Base</span>
                  <span className="text-xs text-muted-foreground">
                    Document Library
                  </span>
                </div>
              </div>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent>
        {/* Dataset */}
        <SidebarGroup>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton
                isActive={activePage === "dataset"}
                onClick={onSelectDataset}
                className="cursor-pointer"
              >
                <Database className="size-4" />
                <span>Dataset</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarGroup>

        {/* Realtime Monitor */}
        <SidebarGroup>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton
                isActive={activePage === "realtime"}
                onClick={onSelectRealtime}
                className="cursor-pointer"
              >
                <Activity className="size-4" />
                <span>Real-time Monitor</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarGroup>

        {/* Workspaces collapsible group */}
        <Collapsible defaultOpen className="group/collapsible">
          <SidebarGroup>
            <SidebarGroupLabel
              asChild
              className="group/label text-sm text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
            >
              <CollapsibleTrigger className="w-full flex items-center">
                <FolderOpen className="size-4 mr-2" />
                Workspaces
                <ChevronRight className="ml-auto size-4 transition-transform group-data-[state=open]/collapsible:rotate-90" />
              </CollapsibleTrigger>
            </SidebarGroupLabel>

            <CollapsibleContent>
              <SidebarGroupContent>
                <SidebarMenu>
                  {workspaces.map((ws) => (
                    <SidebarMenuItem key={ws.id}>
                      <SidebarMenuButton
                        isActive={
                          activePage === "workspace" &&
                          activeWorkspaceId === ws.id
                        }
                        onClick={() => onSelectWorkspace(ws)}
                        className="cursor-pointer"
                      >
                        <span className="pl-2 truncate">{ws.name}</span>
                        <span className="ml-auto text-xs text-muted-foreground shrink-0">
                          {ws.doc_count}
                        </span>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  ))}

                  {/* Create new workspace */}
                  <SidebarMenuItem>
                    <SidebarMenuButton
                      onClick={onCreateWorkspace}
                      className="cursor-pointer text-muted-foreground hover:text-foreground"
                    >
                      <Plus className="size-4" />
                      <span>New Workspace</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                </SidebarMenu>
              </SidebarGroupContent>
            </CollapsibleContent>
          </SidebarGroup>
        </Collapsible>
      </SidebarContent>

      <SidebarRail />
    </Sidebar>
  );
}
