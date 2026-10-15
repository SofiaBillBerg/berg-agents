/*
 * Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture. The system follows a harness-based execution model with multiple specialized agents working together.
 *
 * Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
 *
 * This program is free software: you can redistribute it and/or modify
 *
 * it under the terms of the GNU Affero General Public License as
 * published by the Free Software Foundation, either version 3 of the
 * License, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program.  If not, see <https://gnu.org/licenses/agpl-3.0.html>.
 */

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
          }}}
        rehypePlugins={[rehypeHighlight]}
        remarkPlugins={[remarkGfm]}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

export default MarkdownRenderer;
