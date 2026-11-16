'use client';
import { useId, useRef, type ReactNode } from 'react';

export function WorkspaceTabs({ tabs, value, onChange, children, label = 'Workspace views' }: { tabs: readonly string[]; value: string; onChange: (value: string) => void; children: ReactNode; label?: string }) {
  const id = useId();
  const ref = useRef<HTMLDivElement>(null);
  return <div className="space-y-6">
    <div className="workspace-tabs" role="tablist" aria-label={label} ref={ref}>
      {tabs.map((tab, index) => <button key={tab} id={`${id}-${index}`} type="button" role="tab" aria-selected={value === tab} aria-controls={`${id}-panel`} tabIndex={value === tab ? 0 : -1} onClick={() => onChange(tab)} onKeyDown={event => {
        const offsets: Record<string, number> = { ArrowRight: (index + 1) % tabs.length, ArrowLeft: (index - 1 + tabs.length) % tabs.length, Home: 0, End: tabs.length - 1 };
        const next = offsets[event.key];
        if (next === undefined) return;
        event.preventDefault(); onChange(tabs[next]); ref.current?.querySelectorAll('button')[next]?.focus();
      }}>{tab}</button>)}
    </div>
    <div id={`${id}-panel`} role="tabpanel" aria-labelledby={`${id}-${tabs.indexOf(value)}`} tabIndex={0}>{children}</div>
  </div>;
}
