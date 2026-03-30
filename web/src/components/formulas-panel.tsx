import ReactMarkdown from "react-markdown"
import remarkMath from "remark-math"
import rehypeKatex from "rehype-katex"
import "katex/dist/katex.min.css"
import type { Formula } from "@/types"

export function FormulasPanel({ formulas }: { formulas: Formula[] }) {
  if (formulas.length === 0) {
    return (
      <div className="flex items-center justify-center h-40 text-muted-foreground text-sm">
        No formulas extracted.
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {formulas.map((formula) => (
        <div key={formula.id} className="p-4 bg-muted/30 rounded-lg border border-border">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs text-muted-foreground font-mono bg-muted/50 px-2 py-1 rounded">
              {formula.formula_type === "inline" ? "Inline" : "Display"}
            </span>
            <span className="text-xs text-muted-foreground">
              Page {formula.page_num + 1}
            </span>
          </div>
          <div className="overflow-x-auto p-3 rounded border bg-background">
            <ReactMarkdown
              remarkPlugins={[remarkMath]}
              rehypePlugins={[rehypeKatex]}
            >
              {formula.formula_type === "inline"
                ? `$${formula.latex}$`
                : `$$\n${formula.latex}\n$$`}
            </ReactMarkdown>
          </div>
        </div>
      ))}
    </div>
  )
}
