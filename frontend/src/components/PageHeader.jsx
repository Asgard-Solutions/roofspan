export function PageHeader({ title, description, actions, testid }) {
  return (
    <div className="flex flex-col gap-3 border-b-2 border-orange-500 bg-[#0B1A33] px-6 py-5 sm:flex-row sm:items-center sm:justify-between sm:px-8" data-testid={testid}>
      <div>
        <h1 className="font-heading text-2xl font-bold tracking-tight text-white">{title}</h1>
        {description && <p className="mt-1 text-sm text-slate-300">{description}</p>}
      </div>
      {actions && <div className="rs-header-actions flex items-center gap-2">{actions}</div>}
    </div>
  );
}
