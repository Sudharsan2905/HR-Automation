"use client";

import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import { cn } from "@/lib/utils";

/** Sanitized markdown renderer for question text (supports fenced code blocks). */
export function RichText({ children, className }: { children: string; className?: string }) {
  return (
    <div className={cn("text-base leading-relaxed break-words", className)}>
      <ReactMarkdown
        rehypePlugins={[rehypeSanitize]}
        components={{
          pre: ({ children: c }) => (
            <pre className="my-2 max-w-full overflow-x-auto rounded-md bg-slate-900 p-3 text-[13px] text-slate-100">
              {c}
            </pre>
          ),
          code: ({ className: cls, children: c }) => (
            <code className={cn("font-mono", !cls && "rounded bg-muted px-1.5 py-0.5 text-[0.875em]", cls)}>
              {c}
            </code>
          ),
          p: ({ children: c }) => <p className="my-2">{c}</p>,
          ul: ({ children: c }) => <ul className="my-2 list-disc pl-6">{c}</ul>,
          ol: ({ children: c }) => <ol className="my-2 list-decimal pl-6">{c}</ol>,
          img: ({ src, alt }) => (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={typeof src === "string" ? src : undefined} alt={alt ?? ""} className="my-2 max-w-full rounded" />
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
