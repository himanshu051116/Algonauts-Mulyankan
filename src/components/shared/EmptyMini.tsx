import { FileText } from "lucide-react";

export function EmptyMini({ text }: { text: string }) {
  return (
    <div className="empty-mini">
      <div aria-hidden="true">
        <FileText size={24} />
      </div>
      <p>{text}</p>
    </div>
  );
}
