import React, {useEffect, useState} from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";

 /**
 * MarkdownRenderer component
 * Wraps react-markdown with remark-gfm and rehype-highlight
 * Never throws on malformed partial markdown - catches errors and displays raw text
 * Renders nothing for empty content
 */
function MarkdownRenderer({content}) {
    // Guard empty content - render nothing
    if (!content || content.trim() === "") {
        return null;
    }

    // Catch rendering errors gracefully
    const [renderedContent, setRenderedContent] = useState(content);

    useEffect(() => {
        try {
            setRenderedContent(content);
        } catch {
            // If anything goes wrong, keep raw text
            setRenderedContent(content);
        }
    }, [content]);

    return (
        <div className="markdown-content">
            <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeHighlight]}
                // Add breaks: true so single newlines render as <br>
                breaks={true}
                components={{
                    // Safe rendering - ensure code blocks don't break on unknown languages
                    code({node, inline, className, children, ...props}) {
                        const match = /language-(\w+)/.exec(className || "");
                        const lang = match ? match[1] : "";
                        // Always render with pre/code tags, even if unknown language
                        return inline ? (
                            <code
                                {...props}
                                style={{
                                    fontFamily: "monospace",
                                    background: "#f5f5f5",
                                    padding: "0.2em 0.4em",
                                    borderRadius: "3px",
                                }}
                            >
                                {children}
                            </code>
                        ) : (
                            <pre
                                {...props}
                                style={{
                                    background: "#f5f5f5",
                                    padding: "1em",
                                    borderRadius: "5px",
                                    overflow: "auto",
                                }}
                            >
                <code className={className} {...props}>
                  {children}
                </code>
              </pre>
                        );
                    },
                }}
            >
                {renderedContent}
            </ReactMarkdown>
        </div>
    );
}

export default MarkdownRenderer;
