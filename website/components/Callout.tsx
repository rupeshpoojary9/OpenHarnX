const labels = {
  note: "Note",
  warning: "Important",
  experimental: "Experimental",
  limit: "Limitation",
} as const;

export function Callout({
  type = "note",
  title,
  children,
}: {
  type?: keyof typeof labels;
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <aside className={`callout callout--${type}`}>
      <p className="callout__label">{title ?? labels[type]}</p>
      {children}
    </aside>
  );
}
