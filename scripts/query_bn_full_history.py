import sqlite3
import json

conn = sqlite3.connect('d:\\ReactJs\\aivolve-trading-ai\\backend\\aivolve_trading.db')
cur = conn.cursor()

print("=== SIGNAL EVALUATIONS FOR BANK NIFTY TODAY ===")
cur.execute("""
    SELECT evaluated_at, action, qualified, rejection_reasons, stage_status
    FROM signal_evaluations
    WHERE symbol LIKE '%BANK%'
    ORDER BY evaluated_at ASC
""")
rows = cur.fetchall()
print(f"Total Main Engine Evaluations for BANK NIFTY: {len(rows)}")

step = max(1, len(rows) // 10)
for r in rows[::step] + ([rows[-1]] if rows else []):
    ts, act, qual, rej, stages = r
    try:
        rej_list = json.loads(rej) if rej else []
    except:
        rej_list = rej
    try:
        stg = json.loads(stages) if stages else {}
        failed_stg = {k: v for k, v in stg.items() if v not in ('SUCCESS', 'PASSED')}
    except:
        failed_stg = {}
    print(f"\nTime: {ts} | Action: {act} | Qualified: {qual}")
    print(f"  Failed Stages: {failed_stg}")
    print(f"  Rejections: {rej_list}")

print("\n=== RESEARCH EVALUATIONS FOR BANK NIFTY TODAY ===")
cur.execute("""
    SELECT evaluated_at, qualified, payload
    FROM research_setup_evaluations
    WHERE symbol LIKE '%BANK%'
    ORDER BY evaluated_at ASC
""")
r_rows = cur.fetchall()
print(f"Total Research Engine Evaluations for BANK NIFTY: {len(r_rows)}")
r_step = max(1, len(r_rows) // 8)
for r in r_rows[::r_step] + ([r_rows[-1]] if r_rows else []):
    ts, qual, payload_str = r
    try:
        p = json.loads(payload_str)
        score = p.get('score')
        action = p.get('action')
        reasons = p.get('reasons')
        stages = p.get('stages')
        print(f"\nTime: {ts} | Score: {score} | Action: {action} | Qualified: {qual}")
        print(f"  Reasons: {reasons}")
    except Exception as e:
        print(f"Error parsing: {e}")

conn.close()
