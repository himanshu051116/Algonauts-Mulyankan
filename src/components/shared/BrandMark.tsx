import { Gauge } from "lucide-react";

export function BrandMark({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`brand ${compact ? "brand-compact" : ""}`}>
      <div className="brand-icon"><Gauge size={compact ? 20 : 28} /></div>
      <div>
        <strong>MULYANKAN</strong>
        {!compact && <span>Coal proposal preliminary scrutiny platform</span>}
      </div>
    </div>
  );
}
