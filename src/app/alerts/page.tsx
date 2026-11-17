'use client';
import { PageHeading } from "@/components/shared/PageHeading";
import { WhatsAppRecipients } from '@/components/trading/WhatsAppRecipients';

import React, { useState } from 'react';
import Link from 'next/link';

import { Send, BellRing, CheckCircle2, AlertCircle, ExternalLink, Sliders, RefreshCw, Copy, Check, MessageSquare } from 'lucide-react';
import { usePaperTrading } from '@/context/PaperTradingContext';

export default function AlertsConfigPage() {
  const { telegramConfig, updateTelegramConfig, sendTelegramTestAlert } = usePaperTrading();

  const [botToken, setBotToken] = useState(telegramConfig.botToken || '');
  const [chatId, setChatId] = useState(telegramConfig.chatId || '');
  const [minScore, setMinScore] = useState(telegramConfig.minScore || 80);
  const [notifyCall, setNotifyCall] = useState(telegramConfig.notifyCall ?? true);
  const [notifyPut, setNotifyPut] = useState(telegramConfig.notifyPut ?? true);
  const [enabled, setEnabled] = useState(telegramConfig.enabled ?? false);

  const [isSendingTest, setIsSendingTest] = useState(false);
  const [testResult, setTestResult] = useState<{ success?: boolean; message?: string } | null>(
    null
  );
  const [savedSuccess, setSavedSuccess] = useState(false);
  const [copiedFormat, setCopiedFormat] = useState(false);

  const handleSave = () => {
    updateTelegramConfig({
      botToken,
      chatId,
      minScore,
      notifyCall,
      notifyPut,
      enabled,
    });
    setSavedSuccess(true);
    setTimeout(() => setSavedSuccess(false), 2000);
  };

  const handleTest = async () => {
    setIsSendingTest(true);
    setTestResult(null);

    // Save current values first
    updateTelegramConfig({ botToken, chatId, minScore, notifyCall, notifyPut, enabled });

    const res = await sendTelegramTestAlert();
    setTestResult(res);
    setIsSendingTest(false);
  };

  const sampleAlert = `🚀 AIVOLVE TRADING AI — BREAKOUT ALERT ⚡
━━━━━━━━━━━━━━━━━━━━
📈 Stock: RELIANCE (NSE)
🎯 Signal: CALL (Bullish Momentum)
📊 Quant Setup Score: 86 / 100
💵 CMP: ₹1,455.00
🎯 Target: ₹1,510.00 (+3.78%)
🛡️ Stop Loss: ₹1,420.00 (-2.40%)
⚡ Risk:Reward: 1 : 1.6
━━━━━━━━━━━━━━━━━━━━
💡 AI Catalyst: Price trading above 20 EMA and VWAP dynamic pivot with 1.8x institutional volume surge.
⚠️ Disclaimer: AI research suggestion only. Test with virtual paper trading.`;

  const copySample = () => {
    navigator.clipboard.writeText(sampleAlert);
    setCopiedFormat(true);
    setTimeout(() => setCopiedFormat(false), 2000);
  };

  return (
    <div className="space-y-6 pb-12">
      {/* Header */}
      <PageHeading title="Alerts & notifications" description="Manage your notification settings in one place." actions={<><Link
          href="/"
          className="self-start md:self-auto text-xs tabular-nums text-[var(--text-secondary)] hover:text-[var(--text-primary)] px-3 py-1.5 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] transition-colors"
        >
          ← Return to Dashboard
        </Link></>}/>

      <WhatsAppRecipients />
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Configuration Form (7 cols) */}
        <div className="lg:col-span-7 space-y-5">
          <div className="rounded-xl border border-[var(--border-subtle)] dark:border-[var(--border-subtle)] bg-[var(--bg-surface)] dark:bg-[var(--bg-surface)] p-5 space-y-4 shadow-sm">
            <div className="flex items-center justify-between pb-3 border-b border-[var(--border-subtle)] dark:border-[var(--border-subtle)]">
              <div className="flex items-center gap-2 text-xs font-semibold tabular-nums text-[var(--text-primary)] dark:text-[var(--text-primary)]">
                <Sliders className="w-4 h-4 text-amber-600 dark:text-[#dfa759]" />
                <span>Telegram Bot Credentials</span>
              </div>
              <span className="text-[10px] tabular-nums text-[var(--text-muted)] dark:text-[var(--text-secondary)]">
                Saved locally in browser
              </span>
            </div>

            {/* Bot Token Input */}
            <div className="space-y-1.5">
              <label className="text-xs tabular-nums text-[var(--text-secondary)] dark:text-[var(--text-secondary)] flex items-center justify-between">
                <span>Telegram Bot Token:</span>
                <a
                  href="https://t.me/BotFather"
                  target="_blank"
                  rel="noreferrer"
                  className="text-[10px] text-[var(--accent-blue)] dark:text-[var(--accent-blue)] hover:underline flex items-center gap-1 font-semibold"
                >
                  <span>Get from @BotFather</span>
                  <ExternalLink className="w-2.5 h-2.5" />
                </a>
              </label>
              <input
                type="text"
                value={botToken}
                onChange={(e) => setBotToken(e.target.value)}
                placeholder="e.g. 123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"
                className="w-full p-2.5 bg-[var(--bg-surface-elevated)] dark:bg-black/40 border border-[var(--border-subtle)] dark:border-[var(--border-subtle)] focus:border-amber-500 rounded-xl text-xs tabular-nums text-[var(--text-primary)] dark:text-[var(--text-primary)] placeholder:text-[var(--text-secondary)] focus:outline-none transition-colors"
              />
            </div>

            {/* Chat ID Input */}
            <div className="space-y-1.5">
              <label className="text-xs tabular-nums text-[var(--text-secondary)] dark:text-[var(--text-secondary)] flex items-center justify-between">
                <span>Chat ID or Channel Username:</span>
                <span className="text-[10px] text-[var(--text-muted)]">e.g. 987654321 or @mychannel</span>
              </label>
              <input
                type="text"
                value={chatId}
                onChange={(e) => setChatId(e.target.value)}
                placeholder="e.g. -1001234567890 or your User Chat ID"
                className="w-full p-2.5 bg-[var(--bg-surface-elevated)] dark:bg-black/40 border border-[var(--border-subtle)] dark:border-[var(--border-subtle)] focus:border-amber-500 rounded-xl text-xs tabular-nums text-[var(--text-primary)] dark:text-[var(--text-primary)] placeholder:text-[var(--text-secondary)] focus:outline-none transition-colors"
              />
            </div>

            {/* Score Threshold Slider */}
            <div className="space-y-2 pt-2 border-t border-[var(--border-subtle)] dark:border-[var(--border-subtle)]">
              <div className="flex items-center justify-between text-xs tabular-nums">
                <span className="text-[var(--text-secondary)] dark:text-[var(--text-secondary)]">Minimum Quant Score Threshold:</span>
                <span className="text-amber-700 dark:text-[#dfa759] font-semibold">{minScore} / 100</span>
              </div>
              <input
                type="range"
                min="70"
                max="95"
                step="5"
                value={minScore}
                onChange={(e) => setMinScore(parseInt(e.target.value))}
                className="w-full accent-amber-500 cursor-pointer"
              />
              <div className="flex items-center justify-between text-[10px] tabular-nums text-[var(--text-muted)]">
                <span>70 (More signals)</span>
                <span>80 (Recommended)</span>
                <span>90 (Ultra-selective)</span>
              </div>
            </div>

            {/* Signal Filters */}
            <div className="space-y-2 pt-2 border-t border-[var(--border-subtle)] dark:border-[var(--border-subtle)]">
              <span className="text-xs tabular-nums text-[var(--text-secondary)] dark:text-[var(--text-secondary)] block">
                Notify for Signal Categories:
              </span>
              <div className="grid grid-cols-2 gap-3 text-xs tabular-nums">
                <label className="flex items-center gap-2 p-2.5 rounded-lg bg-[var(--bg-surface-elevated)] dark:bg-black/30 border border-[var(--border-subtle)] dark:border-[var(--border-subtle)] cursor-pointer">
                  <input
                    type="checkbox"
                    checked={notifyCall}
                    onChange={(e) => setNotifyCall(e.target.checked)}
                    className="accent-emerald-500"
                  />
                  <span className="text-emerald-700 dark:text-emerald-400 font-semibold">CALL Setups (Bullish)</span>
                </label>
                <label className="flex items-center gap-2 p-2.5 rounded-lg bg-[var(--bg-surface-elevated)] dark:bg-black/30 border border-[var(--border-subtle)] dark:border-[var(--border-subtle)] cursor-pointer">
                  <input
                    type="checkbox"
                    checked={notifyPut}
                    onChange={(e) => setNotifyPut(e.target.checked)}
                    className="accent-rose-500"
                  />
                  <span className="text-rose-700 dark:text-rose-400 font-semibold">PUT Setups (Bearish)</span>
                </label>
              </div>
            </div>

            {/* Test Result Feedback */}
            {testResult && (
              <div
                className={`p-3 rounded-xl border text-xs tabular-nums flex items-center gap-2 ${
                  testResult.success
                    ? 'bg-emerald-50 dark:bg-emerald-500/15 border-emerald-200 dark:border-emerald-500/30 text-emerald-700 dark:text-emerald-300'
                    : 'bg-rose-50 dark:bg-rose-500/15 border-rose-200 dark:border-rose-500/30 text-rose-700 dark:text-rose-300'
                }`}
              >
                {testResult.success ? (
                  <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0" />
                ) : (
                  <AlertCircle className="w-4 h-4 text-rose-600 dark:text-rose-400 shrink-0" />
                )}
                <span>{testResult.message}</span>
              </div>
            )}

            {savedSuccess && (
              <div className="p-2.5 rounded-lg bg-emerald-50 dark:bg-emerald-500/10 border border-emerald-200 dark:border-emerald-500/20 text-emerald-700 dark:text-emerald-300 text-xs tabular-nums flex items-center gap-1.5">
                <CheckCircle2 className="w-3.5 h-3.5" />
                <span>Configuration saved successfully!</span>
              </div>
            )}

            {/* Action Buttons */}
            <div className="flex items-center gap-3 pt-3">
              <button
                type="button"
                onClick={handleSave}
                className="flex-1 py-2 rounded-xl bg-[var(--bg-surface-elevated)] hover:bg-[var(--bg-surface-elevated)] dark:bg-[var(--bg-surface-elevated)] dark:hover:bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] dark:border-[var(--border-subtle)] text-xs tabular-nums text-[var(--text-primary)] dark:text-[var(--text-primary)] transition-colors"
              >
                Save Settings
              </button>
              <button
                type="button"
                onClick={handleTest}
                disabled={isSendingTest}
                className="flex-1 py-2 rounded-xl bg-gradient-to-r from-[var(--accent-blue)] to-[var(--accent-blue)] hover:opacity-95 text-xs tabular-nums font-semibold text-[var(--text-primary)] shadow-sm flex items-center justify-center gap-2 transition-all disabled:opacity-50"
              >
                {isSendingTest ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    <span>Sending to Telegram...</span>
                  </>
                ) : (
                  <>
                    <Send className="w-3.5 h-3.5" />
                    <span>Send Test Alert Now</span>
                  </>
                )}
              </button>
            </div>
          </div>

          {/* Quick Setup Instructions */}
          <div className="rounded-xl border border-[var(--border-subtle)] dark:border-[var(--border-subtle)] bg-[var(--bg-surface)] dark:bg-[var(--bg-surface)] p-4 space-y-2 text-xs tabular-nums shadow-sm">
            <h4 className="font-semibold text-[var(--text-primary)] dark:text-[var(--text-primary)] flex items-center gap-1.5">
              <MessageSquare className="w-3.5 h-3.5 text-[var(--accent-blue)] dark:text-[var(--accent-blue)]" />
              <span>How to setup in 60 seconds:</span>
            </h4>
            <ol className="text-[var(--text-secondary)] dark:text-[var(--text-secondary)] space-y-1.5 pl-4 list-decimal text-[11px]">
              <li>
                Open Telegram and search for <strong className="text-[var(--text-primary)] dark:text-[var(--text-primary)]">@BotFather</strong>.
              </li>
              <li>
                Send <code className="text-amber-700 dark:text-[#dfa759] font-semibold">/newbot</code>, give it a name, and copy the API Token.
              </li>
              <li>
                Start a chat with your new bot or add it as an admin in your Telegram Channel.
              </li>
              <li>
                Enter your Chat ID or Channel @username above and click <strong className="text-[var(--text-primary)] dark:text-[var(--text-primary)]">&quot;Send Test Alert Now&quot;</strong>!
              </li>
            </ol>
          </div>
        </div>

        {/* Right Column: Live Alert Preview (5 cols) */}
        <div className="lg:col-span-5 space-y-4">
          <div className="rounded-xl border border-[var(--border-subtle)] dark:border-[var(--border-subtle)] bg-[var(--bg-surface)] dark:bg-[var(--bg-surface)] p-5 space-y-3 shadow-sm">
            <div className="flex items-center justify-between pb-2 border-b border-[var(--border-subtle)] dark:border-[var(--border-subtle)]">
              <span className="text-xs tabular-nums font-semibold text-[var(--text-primary)] dark:text-[var(--text-primary)] flex items-center gap-1.5">
                <BellRing className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
                <span>Telegram Alert Output Preview</span>
              </span>
              <button
                onClick={copySample}
                className="text-[10px] tabular-nums text-[var(--text-muted)] dark:text-[var(--text-secondary)] hover:text-[var(--text-primary)] dark:hover:text-[var(--text-primary)] flex items-center gap-1"
              >
                {copiedFormat ? <Check className="w-3 h-3 text-emerald-600 dark:text-emerald-400" /> : <Copy className="w-3 h-3" />}
                <span>{copiedFormat ? 'Copied' : 'Copy'}</span>
              </button>
            </div>

            {/* Telegram Message Bubble Mockup */}
            <div className="rounded-xl bg-[var(--bg-surface)] border border-[var(--border-subtle)] p-4 text-xs tabular-nums text-[var(--text-primary)] shadow-xl space-y-2 leading-relaxed">
              <div className="flex items-center gap-2 pb-1.5 border-b border-[var(--border-subtle)]">
                <div className="w-5 h-5 rounded-full bg-gradient-to-tr from-amber-500 to-[var(--accent-blue)] flex items-center justify-center text-[9px] font-semibold text-black">
                  AV
                </div>
                <span className="font-semibold text-[var(--accent-blue)] text-xs">Aivolve Trading AI Bot</span>
                <span className="text-[10px] text-[var(--text-muted)] ml-auto">10:30 AM</span>
              </div>

              <div className="text-[11px] space-y-1 pt-1">
                <p className="font-semibold text-[var(--text-primary)]">🚀 AIVOLVE TRADING AI — BREAKOUT ALERT ⚡</p>
                <div className="h-px bg-[var(--bg-surface-elevated)] my-1" />
                <p>📈 <strong className="text-[var(--text-primary)]">Stock:</strong> RELIANCE (NSE)</p>
                <p>🎯 <strong className="text-emerald-400">Signal:</strong> CALL (Bullish Momentum)</p>
                <p>📊 <strong className="text-amber-400">Quant Setup Score:</strong> 86 / 100</p>
                <p>💵 <strong className="text-[var(--text-primary)]">CMP:</strong> ₹1,455.00</p>
                <p>🎯 <strong className="text-emerald-400">Target:</strong> ₹1,510.00 (+3.78%)</p>
                <p>🛡️ <strong className="text-rose-400">Stop Loss:</strong> ₹1,420.00 (-2.40%)</p>
                <p>⚡ <strong className="text-[var(--accent-blue)]">Risk:Reward:</strong> 1 : 1.6</p>
                <div className="h-px bg-[var(--bg-surface-elevated)] my-1" />
                <p className="text-[var(--text-secondary)]">
                  💡 <strong className="text-[var(--text-primary)]">AI Catalyst:</strong> Price trading above 20 EMA and VWAP dynamic pivot with 1.8x volume surge.
                </p>
                <p className="text-[10px] text-[var(--text-secondary)] italic pt-1">
                  ⚠️ Disclaimer: AI research suggestion only. Test with virtual paper trading.
                </p>
              </div>
            </div>

            <div className="p-3 rounded-lg bg-[var(--bg-surface-elevated)] dark:bg-black/30 border border-[var(--border-subtle)] dark:border-[var(--border-subtle)] text-[11px] tabular-nums text-[var(--text-muted)] dark:text-[var(--text-secondary)]">
              <span className="text-amber-700 dark:text-[#dfa759] font-semibold block mb-1">Instant Direct Delivery:</span>
              Alerts are dispatched directly via Telegram Official Bot API without passing through third-party servers.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
