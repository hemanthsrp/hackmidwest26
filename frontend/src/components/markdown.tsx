import type { ReactNode } from "react";

function inline(text: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g);
  return parts.filter(Boolean).map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**"))
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`"))
      return <code key={index}>{part.slice(1, -1)}</code>;
    if (part.startsWith("*") && part.endsWith("*"))
      return <em key={index}>{part.slice(1, -1)}</em>;
    return part;
  });
}

export function MarkdownText({ content }: { content: string }) {
  const blocks = content.trim().split(/\n\s*\n/).filter(Boolean);
  return (
    <div className="markdown-text">
      {blocks.map((block, index) => {
        const lines = block.split("\n");
        if (lines.every((line) => /^[-*]\s+/.test(line)))
          return (
            <ul key={index}>
              {lines.map((line, item) => (
                <li key={item}>{inline(line.replace(/^[-*]\s+/, ""))}</li>
              ))}
            </ul>
          );
        const heading = lines[0].match(/^(#{1,3})\s+(.+)$/);
        if (heading) {
          const text = inline(heading[2]);
          if (heading[1].length === 1) return <h3 key={index}>{text}</h3>;
          return <h4 key={index}>{text}</h4>;
        }
        return (
          <p key={index}>
            {lines.flatMap((line, lineIndex) =>
              lineIndex ? [<br key={lineIndex} />, ...inline(line)] : inline(line),
            )}
          </p>
        );
      })}
    </div>
  );
}
