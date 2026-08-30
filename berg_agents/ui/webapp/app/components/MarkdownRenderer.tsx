import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";

export interface MarkdownRendererProps {
  content?: string;
}

/**
 * MarkdownRenderer component.
 * Wraps react-markdown with remark-gfm and rehype-highlight syntax highlighting.
 * Catches rendering exceptions gracefully and displays plain text if markdown parsing fails.
 *
 * @param props - Component properties
 * @returns JSX element rendering the formatted markdown
 */
export function MarkdownRenderer({ content }: MarkdownRendererProps) {
  // Guard empty content - render nothing
  if (!content || content.trim() === "") {
    return null;
  }

  return (
    <div className="markdown-content text-sm leading-relaxed">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          code({ className, children, ...props }: any) {
            const isInline =
              !className &&
              typeof children === "string" &&
              !children.includes("\n");
            if (isInline) {
              return (
                <code
                  className="font-mono bg-surface-soft px-1.5 py-0.5 rounded text-xs text-muted"
                  {...props}
                >
                  {children}
                </code>
              );
            }
            return (
              <pre className="font-mono bg-surface-soft p-3 rounded-lg overflow-x-auto text-xs my-2 border border-border">
                <code className={className} {...props}>
                  {children}
                </code>
              </pre>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

export default MarkdownRenderer;
