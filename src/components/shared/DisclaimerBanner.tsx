import { ShieldCheck } from 'lucide-react';

export function DisclaimerBanner() {
  return <footer className="workspace-footer">
    <div><ShieldCheck size={14}/><span>Designed for thoughtful decisions.</span></div>
    <p>Market analysis is probabilistic and for education and research. AIVOLVE is not a registered SEBI research analyst or broker. Paper trades use virtual capital.</p>
    <span>AIVOLVE TECH · IST / INR</span>
  </footer>;
}
