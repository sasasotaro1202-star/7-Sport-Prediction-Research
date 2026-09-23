  # already-cutoff-safe state and are evaluated by the existing chronological OOS gates.
  def _mul(a,b):
   return float(a*b) if np.isfinite(a) and np.isfinite(b) else np.nan
  f['D__elo_x_form']=_mul(f['D__elo'],f['D__recent_form_delta'])
  coverage_vals=np.asarray([f['A__stat_coverage'],f['B__stat_coverage']],dtype=float)
  coverage_mean=float(np.mean(coverage_vals[np.isfinite(coverage_vals)])) if np.any(np.isfinite(coverage_vals)) else np.nan
  f['D__elo_x_coverage']=_mul(f['D__elo'],coverage_mean)
  f['D__momentum_x_form']=_mul(f['D__elo_momentum'],f['D__recent_form_delta'])
  f['D__momentum_x_freshness']=_mul(f['D__elo_momentum'],f['D__stat_freshness_mean_days'])
  f['D__form_x_short_rest']=_mul(f['D__recent_form_delta'],f['D__short_rest_flag'])
  key=tuple(sorted((p['A'],p['B'])))
  hh=h2h.get(key,[])
  a_first=(p['A']==key[0])