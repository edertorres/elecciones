import core
import json
import pandas as pd

# Load data
with open("cache/pr_2400_data.json", "r") as f:
    data = json.load(f)
    df = pd.DataFrame(data)

# Load stats
with open("cache/pr_2400_stats.json", "r") as f:
    stats = json.load(f)

# Generate with 8.5 cm page width
core.generate_typst_pro(
    df, 
    "TEST", 
    "test_report.typ", 
    stats=stats, 
    etype_label="PRESIDENCIA", 
    is_national=False, 
    page_width=8.5
)

# Compile
pdf_path = core.compile_pdf("test_report.typ")
print("Compiled PDF path:", pdf_path)
