import type { ReactNode } from 'react';

export function PageHeading({ title, description, eyebrow = 'Your edge starts with clarity', actions }: { title: ReactNode; description: string; eyebrow?: string; actions?: ReactNode }) {
  return <div className="workspace-page-heading">
    <div><p className="workspace-eyebrow">{eyebrow}</p><h1>{title}</h1><p>{description}</p></div>
    {actions && <div className="workspace-page-actions">{actions}</div>}
  </div>;
}
