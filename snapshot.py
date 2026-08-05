from pathlib import Path
import yaml
from engine import get_snapshot, earnings_date, grade, option_chain, recommendations, save_snapshot
BASE=Path(__file__).resolve().parent
cfg=yaml.safe_load((BASE/"config.yaml").read_text(encoding="utf-8"))
snap=get_snapshot(cfg); result=grade(snap,earnings_date(cfg),cfg)
recs=recommendations(option_chain(cfg,snap["spot"]),snap,result,cfg)
save_snapshot(str(BASE/"data/latest_snapshot.json"),snap,result,recs)
print(result["label"],result["score"])
