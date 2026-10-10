export function Badge({ label = 'ДЕМО' }: { label?: string }) {
  return <span className="badge">{label}</span>;
}
