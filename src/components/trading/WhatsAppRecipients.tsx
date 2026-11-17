'use client';

import React, { useEffect, useState } from 'react';

const STORAGE_KEY = 'aivolve.whatsapp.recipients.v1';

export function WhatsAppRecipients() {
  const [numbers, setNumbers] = useState<string[]>([]);
  const [value, setValue] = useState('');
  const [editing, setEditing] = useState<number | null>(null);
  const [ready, setReady] = useState(false);
  const [message, setMessage] = useState('');

  useEffect(() => {
    const timer = window.setTimeout(() => {
      try {
        const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
        if (!Array.isArray(stored) || !stored.every((item) => typeof item === 'string' && /^\+[1-9]\d{7,14}$/.test(item))) {
          throw new Error('Invalid saved list');
        }
        setNumbers(stored);
        setReady(true);
      } catch {
        setMessage('Saved numbers could not be read. They were not changed.');
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  function persist(next: string[]) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      setNumbers(next);
      setMessage('Saved on this browser. WhatsApp delivery is not connected yet.');
      return true;
    } catch {
      setMessage('Could not save numbers in this browser.');
      return false;
    }
  }

  function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const input = value.replace(/[\s()-]/g, '');
    const normalized = /^[6-9]\d{9}$/.test(input)
      ? `+91${input}`
      : /^91[6-9]\d{9}$/.test(input) ? `+${input}` : input;
    if (!/^\+[1-9]\d{7,14}$/.test(normalized)) {
      setMessage('Enter a 10-digit Indian mobile number, or an international number with + and country code.');
      return;
    }
    if (numbers.some((number, index) => number === normalized && index !== editing)) {
      setMessage('This number is already in the list.');
      return;
    }
    const next = [...numbers];
    if (editing === null) next.push(normalized); else next[editing] = normalized;
    if (persist(next)) { setValue(''); setEditing(null); }
  }

  return (
    <section className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-5 space-y-4 shadow-sm" aria-labelledby="whatsapp-title">
      <div className="space-y-1">
        <h2 id="whatsapp-title" className="text-sm font-semibold text-[var(--text-primary)]">WhatsApp recipients</h2>
        <p className="text-xs text-amber-700 dark:text-amber-400">Delivery not connected yet. These numbers are saved only in this browser and are not sent to the server.</p>
      </div>
      <form onSubmit={save} className="flex flex-col sm:flex-row gap-2">
        <label htmlFor="whatsapp-number" className="sr-only">WhatsApp number</label>
        <input id="whatsapp-number" type="tel" autoComplete="tel" value={value} onChange={(e) => setValue(e.target.value)} placeholder="98765 43210 or +91 98765 43210" className="flex-1 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] p-2.5 text-sm text-[var(--text-primary)]" />
        <button type="submit" disabled={!ready} className="rounded-lg bg-[var(--accent-blue)] px-4 py-2 text-sm font-semibold text-[var(--accent-on)] disabled:opacity-50">{editing === null ? 'Add number' : 'Save change'}</button>
        {editing !== null && <button type="button" onClick={() => { setEditing(null); setValue(''); setMessage(''); }} className="rounded-lg border border-[var(--border-subtle)] px-3 py-2 text-sm">Cancel</button>}
      </form>
      {message && <p role="status" className="text-xs text-[var(--text-secondary)]">{message}</p>}
      {ready && numbers.length === 0 && <p className="text-xs text-[var(--text-muted)]">No numbers added yet.</p>}
      <ul className="space-y-2">
        {numbers.map((number, index) => <li key={number} className="flex items-center gap-3 rounded-lg border border-[var(--border-subtle)] p-2.5 text-sm">
          <span className="flex-1 text-[var(--text-primary)]">{number}</span>
          <button type="button" onClick={() => { setEditing(index); setValue(number); setMessage(''); }} className="text-[var(--accent-blue)]" aria-label={`Edit ${number}`}>Edit</button>
          <button type="button" onClick={() => { if (persist(numbers.filter((_, i) => i !== index))) { setEditing(null); setValue(''); } }} className="text-rose-600" aria-label={`Remove ${number}`}>Remove</button>
        </li>)}
      </ul>
    </section>
  );
}
