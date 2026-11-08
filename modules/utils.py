import math
import pandas as pd

def nv(val):
    if val is None: return None
    try:
        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)): return None
        if pd.isna(val): return None
    except Exception: pass
    return float(val)
