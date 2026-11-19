import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_INTERNAL_URL || 'http://127.0.0.1:8000';
const OPERATOR_KEY = process.env.OPERATOR_SECRET_KEY || 'aivolve-internal-operator';

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();

    const backendRes = await fetch(`${BACKEND_URL}/api/paper-trading/close`, {
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
