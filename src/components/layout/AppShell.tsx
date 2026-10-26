'use client';

import React, { useState } from 'react';
import { Sidebar } from './Sidebar';
import { TopHeader } from './TopHeader';
import { DisclaimerBanner } from '../shared/DisclaimerBanner';

interface AppShellProps {
  children: React.ReactNode;
}

export const AppShell: React.FC<AppShellProps> = ({ children }) => {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="min-h-screen bg-[var(--bg-main)] text-[var(--text-primary)] flex transition-colors duration-200">
      {/* Fixed Desktop Sidebar & Mobile Drawer */}
      <Sidebar mobileOpen={mobileOpen} onCloseMobile={() => setMobileOpen(false)} />

      {/* Backdrop for mobile drawer */}
      {mobileOpen && (
        <div
          onClick={() => setMobileOpen(false)}
          className="fixed inset-0 z-30 bg-black/60 backdrop-blur-sm md:hidden"
        />
      )}

      {/* Main Content Area (Offset by sidebar on md+) */}
      <div className="flex-1 flex flex-col min-w-0 md:pl-64">
        <TopHeader onToggleMobile={() => setMobileOpen(!mobileOpen)} />

        {/* Dynamic Page Content */}
        <main className="flex-1 px-4 sm:px-6 lg:px-8 py-6 max-w-7xl w-full mx-auto">
          {children}
        </main>

        {/* Global Regulatory Disclaimer */}
        <DisclaimerBanner />
      </div>
    </div>
  );
};
