import json
with open("cache/pr_2400_data.json", "r") as f:
    data = json.load(f)
cands = set((d["Partido"], d["Candidato"]) for d in data)
print(f"Total unique candidates: {len(cands)}\n")
for cand in sorted(list(cands)):
    print(cand)
