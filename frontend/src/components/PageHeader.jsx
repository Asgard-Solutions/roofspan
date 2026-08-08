export function PageHeader({ title, description, actions, testid }) {
  return (
    <div className="flex flex-col gap-3 border-b border-border bg-white px-6 py-5 sm:flex-row sm:items-center sm:justify-between sm:px-8" data-testid={testid}>
      <div>
        <h1 className="font-heading text-2xl font-bold tracking-tight text-slate-900">{title}</h1>
        {description && <p className="mt-1 text-sm text-slate-500">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
