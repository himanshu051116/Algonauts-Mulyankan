export function ExplainabilityCard({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="panel explainability-card">
      <h3>{title}</h3>
      {items.length ? items.slice(0, 6).map((item, index) => <p key={`${title}-${index}`}>{item}</p>) : <p>No items identified.</p>}
    </div>
  );
}
