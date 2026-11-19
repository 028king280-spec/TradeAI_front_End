import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_INTERNAL_URL || 'http://127.0.0.1:8000';
const OPERATOR_KEY = process.env.OPERATOR_SECRET_KEY || 'aivolve-internal-operator';

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();

    // SENSEX Governance Lock Enforcement
    const instrument = String(body.instrument || '').toUpperCase();
    if (instrument.includes('SENSEX') || instrument.includes('BSE')) {
      return NextResponse.json(
        {
          success: false,
          circuitBreakerState: 'GOVERNANCE_LOCKED',
          message: 'SENSEX trading rejected: Under strict GOVERNANCE_LOCK. Unconfigured institutional parameters. Only NIFTY, BANKNIFTY, and FINNIFTY permitted.',
        },
        { status: 403 }
      );
    }

    // Strip any client-forged replay or override flags
    if (body.marketFeatures) {
      delete body.marketFeatures.allowAfterHoursSimulation;
      delete body.marketFeatures.dataStatus;
      delete body.marketFeatures.feedStatus;
      delete body.marketFeatures.isReplay;
    }

    // Secure server-side proxy with operator secret header
    const backendRes = await fetch(`${BACKEND_URL}/api/paper-trading/open`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-AIVOLVE-AUTH-TOKEN': OPERATOR_KEY,
      },
      body: JSON.stringify(body),
    });

    const data = await backendRes.json();
    return NextResponse.json(data, { status: backendRes.status });
  } catch (err: any) {
    return NextResponse.json(
      {
        success: false,
        message: `Paper trading proxy error: ${err.message || 'Server error'}`,
      },
      { status: 500 }
    );
  }
}
