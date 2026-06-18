from core import get_nomenclator

def get_dept_options():
    try:
        nom = get_nomenclator()
        items = nom.get("ambitos", {}).get("1", [])
        opts = {}
        for item in items:
            level = item.get("l")
            if level == 1: # COLOMBIA
                opts["NACIONAL"] = {"code": item["c"], "name": item["n"]}
            elif level == 2: # DEPARTAMENTOS
                opts[item["n"]] = {"code": item["c"], "name": item["n"]}
        return opts
    except Exception as e:
        print(f"Error: {e}")
        return {}

opts = get_dept_options()
print(f"RISARALDA code: {opts.get('RISARALDA')}")
print(f"NACIONAL code: {opts.get('NACIONAL')}")
