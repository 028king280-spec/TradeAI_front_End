'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { ArrowUpRight, Bell, ChevronRight, Menu, Search, X } from 'lucide-react';
import { apiClient } from '@/lib/api';
import { navigation, workspaceTitle } from './navigation';
import styles from './Workspace.module.css';

interface StockMatch { symbol: string; companyName: string; exchange: string }

export function TopHeader({ onToggleMobile, mobileOpen }: { onToggleMobile: () => void; mobileOpen: boolean }) {
  const pathname = usePathname();
  const router = useRouter();
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [stocks, setStocks] = useState<StockMatch[]>([]);
  const [searching, setSearching] = useState(false);
  const searchRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const pages = query.trim() ? navigation.flatMap(group => group.items).filter(item => item.label.toLowerCase().includes(query.trim().toLowerCase())) : [];

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); inputRef.current?.focus(); }
      if (event.key === 'Escape') setOpen(false);
    }
    function onOutside(event: MouseEvent) { if (!searchRef.current?.contains(event.target as Node)) setOpen(false); }
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onOutside);
    return () => { document.removeEventListener('keydown', onKey); document.removeEventListener('mousedown', onOutside); };
  }, []);

  useEffect(() => {
    let cancelled = false;
    if (!query.trim()) return;
    const timer = window.setTimeout(async () => {
      setSearching(true);
      try {
        const matches = await apiClient.searchStocks(query.trim());
        if (!cancelled) setStocks(matches.slice(0, 5));
      } catch { if (!cancelled) setStocks([]); } finally { if (!cancelled) setSearching(false); }
    }, 250);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [query]);

  function closeSearch() { setOpen(false); setQuery(''); setStocks([]); setSearching(false); }

  return <header className={styles.header}>
    <div className={styles.breadcrumb}>
      <button onClick={onToggleMobile} className={`${styles.iconButton} ${styles.mobileMenu}`} aria-label="Toggle navigation" aria-controls="workspace-navigation" aria-expanded={mobileOpen}><Menu size={20}/></button>
      <span>Workspace</span><ChevronRight size={13}/><b>{workspaceTitle(pathname)}</b>
    </div>
    <div className={styles.headerActions}>
      <div className={styles.headerSearch} ref={searchRef}>
        <Search size={15}/>
        <form onSubmit={event => { event.preventDefault(); if (query.trim()) { router.push(`/search?q=${encodeURIComponent(query.trim())}`); closeSearch(); } }}>
          <input ref={inputRef} id="global-search-input" aria-label="Search workspace and stocks" aria-controls={open && query.trim() ? 'workspace-search-results' : undefined} autoComplete="off" placeholder="Search stocks or pages…" value={query} onFocus={() => setOpen(true)} onChange={event => { setQuery(event.target.value); setStocks([]); setOpen(true); }}/>
        </form>
        <kbd>⌘ K</kbd>
        {open && query.trim() && <div className={styles.searchResults} id="workspace-search-results" aria-label="Search results">
          <div className="workspace-search-heading">Workspace</div>
          {pages.map(page => <Link key={page.href} href={page.href} onClick={closeSearch}><page.icon size={15}/><span>{page.label}</span><ArrowUpRight size={13}/></Link>)}
          <div className="workspace-search-heading">Stocks</div>
          {stocks.map(stock => <Link key={stock.symbol} href={`/stocks/${encodeURIComponent(stock.symbol)}`} onClick={closeSearch}><span><b>{stock.symbol}</b><small>{stock.companyName} · {stock.exchange}</small></span><ArrowUpRight size={13}/></Link>)}
          {searching && <p role="status">Searching…</p>}
          {!searching && !stocks.length && <p>No matching stocks</p>}
          <Link href={`/search?q=${encodeURIComponent(query.trim())}`} onClick={closeSearch}>View all stock results <ArrowUpRight size={13}/></Link>
          <button onClick={closeSearch} aria-label="Close search"><X size={13}/> Close</button>
        </div>}
      </div>
      <span className={styles.headerDivider}/>
      <Link href="/alerts" className={styles.iconButton} aria-label="Open alerts"><Bell size={18}/></Link>
      <span className={styles.profileAvatar} aria-label="Personal workspace">AV</span>
    </div>
  </header>;
}
