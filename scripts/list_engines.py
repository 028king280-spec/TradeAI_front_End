import os
import glob

app_dir = 'd:/ReactJs/aivolve-trading-ai/backend/app'
engines = []
for root, dirs, files in os.walk(app_dir):
    for f in files:
        if 'engine' in f.lower() or 'detector' in f.lower() or 'pipeline' in f.lower():
            engines.append(os.path.join(root, f))

for e in sorted(engines):
    print(e.replace(app_dir, 'app'))
