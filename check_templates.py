import json, requests

r = requests.get("http://localhost:8000/api/v1/checklists/templates")
data = r.json()
worker = [x for x in data if 'worker' in x['checklist_type']]

for t in worker:
    print(f"\n=== {t['display_name']} ({t['checklist_type']}) ===")
    for item in t['items']:
        print(f"  {item['item_no']}. [{item['section_name']}] {item['item_text']}")

print(f"\n\nTotal worker checklists: {len(worker)}")
