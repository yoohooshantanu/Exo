import numpy as np
import pandas as pd
from pathlib import Path

# Constants
G = 6.6743e-11           # m^3 kg^-1 s^-2
M_EARTH = 5.972e24       # kg
R_EARTH = 6.371e6        # m
SIGMA = 5.67e-8          # W m^-2 K^-4
SEC_PER_GYR = 1e9 * 365.25 * 24 * 3600

# Model Assumptions
EPSILON = 0.1            # Heating efficiency
M_ENV = 1e-6 * M_EARTH   # 1 bar secondary atmosphere

def compute_t_sat(teff):
    """
    Compute saturation time (Gyr) based on spectral type.
    Uses FGK relation (Jackson+ 2012) ~ 0.1 Gyr.
    Uses M relation (Engle & Guinan 2018) ~ 1.0+ Gyr.
    Linearly interpolate between 6000K (0.1 Gyr) and 3000K (1.0 Gyr).
    """
    if pd.isna(teff):
        return 0.5
    t = 0.1 + 0.9 * (6000 - teff) / (6000 - 3000)
    return max(0.1, min(1.5, t))

def xuv_integral(t_gyr, t_sat_gyr):
    """
    Integral of (L_xuv / L_bol) dt over time.
    L_xuv / L_bol = 1e-3 for t <= t_sat
    L_xuv / L_bol = 1e-3 * (t / t_sat)^-1.5 for t > t_sat
    Returns result in seconds (since L_xuv/L_bol is dimensionless).
    """
    t_sec = t_gyr * SEC_PER_GYR
    t_sat_sec = t_sat_gyr * SEC_PER_GYR
    
    if t_sec <= t_sat_sec:
        return 1e-3 * t_sec
    else:
        # Integral = 1e-3 * t_sat + 2 * 1e-3 * t_sat * (1 - sqrt(t_sat / t))
        return 1e-3 * t_sat_sec * (3.0 - 2.0 * np.sqrt(t_sat_sec / t_sec))

def compute_mass_loss(teq, radius_earth, mass_earth, t_gyr, t_sat_gyr):
    """
    Compute total mass lost in kg.
    """
    if pd.isna(teq):
        return np.nan
        
    # Impute missing mass or radius using rocky density approximation M = R^3
    if pd.isna(mass_earth) and pd.notna(radius_earth):
        mass_earth = radius_earth ** 3
    elif pd.isna(radius_earth) and pd.notna(mass_earth):
        radius_earth = mass_earth ** (1/3)
    elif pd.isna(mass_earth) and pd.isna(radius_earth):
        return np.nan
        
    rp = radius_earth * R_EARTH
    mp = mass_earth * M_EARTH
    
    # F_bol = 4 * sigma * Teq^4 (assuming zero albedo, full redistribution)
    f_bol = 4 * SIGMA * (teq ** 4)
    
    integral_s = xuv_integral(t_gyr, t_sat_gyr)
    u_xuv = f_bol * integral_s  # Joules per m^2
    
    delta_m = (EPSILON * np.pi * (rp ** 3) * u_xuv) / (G * mp)
    return delta_m

def expected_retention(teq, radius_earth, mass_earth, t_sat_gyr, age_gyr, age_is_imputed):
    """
    Compute retention probability.
    If age is missing or imputed, marginalize over 1-10 Gyr uniform prior.
    """
    if pd.isna(teq):
        return np.nan
        
    def retention_from_t(t):
        dm = compute_mass_loss(teq, radius_earth, mass_earth, t, t_sat_gyr)
        # Sigmoid: P = 1 / (1 + (Delta M / M_env))
        return 1.0 / (1.0 + (dm / M_ENV))

    if pd.notna(age_gyr) and not age_is_imputed:
        # Real age
        return retention_from_t(age_gyr)
    else:
        # Marginalize (100 samples)
        t_samples = np.linspace(1.0, 10.0, 100)
        retentions = [retention_from_t(t) for t in t_samples]
        return np.mean(retentions)

def run_model(df):
    """
    Apply the XUV model to the dataset.
    """
    results = []
    
    for _, row in df.iterrows():
        t_sat = compute_t_sat(row['teff'])
        retention = expected_retention(
            teq=row['teq_k'],
            radius_earth=row['radius_earth'],
            mass_earth=row['mass_earth'],
            t_sat_gyr=t_sat,
            age_gyr=row['age_gyr'],
            age_is_imputed=row['age_is_imputed']
        )
        results.append({
            'planet_id': row['planet_id'],
            'planet_name': row['planet_name'],
            'teff': row['teff'],
            't_sat_gyr': t_sat,
            'retention_prob': retention
        })
        
    return pd.DataFrame(results)

def sanity_check():
    print("--- LUGER & BARNES SANITY CHECK ---")
    teq = 255.0
    r = 1.0
    m = 1.0
    age = 4.5
    
    # G-dwarf (Teff = 5800K)
    t_sat_g = compute_t_sat(5800)
    ret_g = expected_retention(teq, r, m, t_sat_g, age, False)
    
    # M-dwarf (Teff = 3000K)
    t_sat_m = compute_t_sat(3000)
    ret_m = expected_retention(teq, r, m, t_sat_m, age, False)
    
    print(f"Target: Earth-sized planet at Teq=255K, Age=4.5 Gyr")
    print(f"G-dwarf (5800K): t_sat = {t_sat_g:.2f} Gyr, Retention = {ret_g:.4e}")
    print(f"M-dwarf (3000K): t_sat = {t_sat_m:.2f} Gyr, Retention = {ret_m:.4e}")
    if ret_m < ret_g:
        print("Sanity Check PASSED: M-dwarf has strictly lower retention due to extended saturation phase.\n")
    else:
        print("Sanity Check FAILED: Model does not penalize M-dwarf correctly.\n")

if __name__ == "__main__":
    sanity_check()
    snapshot_path = Path("outputs/snapshots/latest_snapshot.csv")
    if not snapshot_path.exists():
        print(f"Snapshot not found at {snapshot_path}")
    else:
        df = pd.read_csv(snapshot_path)
        out_df = run_model(df)
        print(out_df.head(10))
        print(f"\nModel applied successfully to {len(out_df)} planets.")
