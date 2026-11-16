'use client';

import React, { useState } from 'react';
import { X, Copy, Check, FileText, Sparkles } from 'lucide-react';

interface AIMarketReportModalProps {
  isOpen: boolean;
  onClose: () => void;
  reportText?: string;
  symbol?: string;
}

export const AIMarketReportModal: React.FC<AIMarketReportModalProps> = ({
  isOpen,
  onClose,
  reportText,
  symbol = 'NIFTY 50',
}) => {
  const [copied, setCopied] = useState(false);

  if (!isOpen) return null;

  const handleCopy = () => {
    if (!reportText) return;
    navigator.clipboard.writeText(reportText);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="relative w-full max-w-2xl max-h-[85vh] bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-2xl shadow-2xl flex flex-col tabular-nums overflow-hidden">
        {/* Modal Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)]">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-[var(--accent-blue)]/10 border border-[var(--accent-blue)]/20 flex items-center justify-center">
              <Sparkles className="w-4 h-4 text-[var(--accent-blue)]" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-[var(--text-primary)]">
                INSTITUTIONAL AI MARKET ANALYSIS
              </h3>
              <p className="text-[11px] text-[var(--text-muted)]">
                15-Point Standard ICT + SMC Report • {symbol}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={handleCopy}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-[var(--bg-surface)] hover:bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] text-[var(--text-primary)] transition-colors"
            >
              {copied ? (
                <>
                  <Check className="w-3.5 h-3.5 text-emerald-500" />
                  <span className="text-emerald-500">Copied</span>
                </>
              ) : (
                <>
                  <Copy className="w-3.5 h-3.5 text-[var(--text-muted)]" />
                  <span>Copy Report</span>
                </>
              )}
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg hover:bg-[var(--bg-surface-elevated)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Modal Content */}
        <div className="p-5 overflow-y-auto space-y-4 text-xs leading-relaxed text-[var(--text-secondary)] whitespace-pre-wrap select-text selection:bg-[var(--accent-blue)]/20">
          {reportText ? (
            <div className="p-4 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] tabular-nums text-[11px] text-[var(--text-primary)]">
              {reportText}
            </div>
          ) : (
            <div className="py-12 text-center text-[var(--text-muted)]">
              <FileText className="w-8 h-8 mx-auto mb-2 opacity-40" />
              <p>No AI report generated for current session.</p>
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div className="px-5 py-3 border-t border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] flex items-center justify-between text-[10px] text-[var(--text-muted)]">
          <span>Non-predictive quantitative analysis • Actual market prices</span>
          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded-lg font-semibold bg-[var(--accent-blue)] hover:bg-[var(--accent-blue)] text-[var(--accent-on)] transition-colors"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
};

