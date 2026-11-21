import json

transcript_path = r'C:\Users\Sourav Verma\.gemini\antigravity\brain\a47b88ae-3d04-471a-a671-adebd0b6ad2f\.system_generated\logs\transcript.jsonl'
target_ids = ['PT-D8D780EB', 'PT-21E1FBA1', 'PT-FBEA215F', 'PT-8F92618C', 'PT-87BAC4A8', 'PT-B43E2C4B']

with open(transcript_path, 'r', encoding='utf-8') as f:
    for line_idx, line in enumerate(f):
        if line_idx > 29470:
            break
        for tid in target_ids:
            if tid in line:
                data = json.loads(line)
                step = data.get('step_index')
                created = data.get('created_at')
                content = str(data.get('content', ''))
                idx = content.find(tid)
                snippet = content[max(0, idx - 100): min(len(content), idx + 200)].replace('\n', ' ')
                print(f"Line {line_idx} | Step {step} | Created: {created} | TID: {tid}")
                print(f"   Snippet: {snippet}\n")
