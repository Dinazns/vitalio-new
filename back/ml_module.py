"""
VitalIO - Module de détection d'anomalies physiologiques par Machine Learning.

Modèle : Isolation Forest (non supervisé) sur les mesures « normales » + feedback médecin.
Entrées : heart_rate, spo2, temperature, signal_quality
Sorties : anomaly_score (0-1), anomaly_level (normal/warning/critical),
          contributing_variables, model_version

Feedback (ml_anomalies rejected / validated) :
  - rejected (FP) : sur-échantillonnés comme inliers dans fit(IF) uniquement.
  - validated (TP) : banque d’exemplaires (global + optionnel par patient via user_id_auth) ;
    à l’inférence, boost du score si proximité (noyau gaussien en espace normalisé),
    sans mélanger les TP dans fit(IF).

Forecasting v2 : Weighted Linear Regression + Mann-Kendall trend test +
  proper prediction intervals + clinical drift detection + confidence scoring.
"""

import math
import os
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.linear_model import LinearRegression

logger=logging.getLogger(__name__)

FEATURE_NAMES=["heart_rate","spo2","temperature","signal_quality"]

PHYSIOLOGICAL_RANGES:Dict[str,Tuple[float,float]]={
    "heart_rate":(50.0,120.0),
    "spo2":(92.0,100.0),
    "temperature":(35.5,38.0),
    "signal_quality":(50.0,100.0),
}

HARD_RANGES:Dict[str,Tuple[float,float]]={
    "heart_rate":(30.0,220.0),
    "spo2":(70.0,100.0),
    "temperature":(34.0,42.0),
    "signal_quality":(0.0,100.0),
}

DEFAULT_ML_THRESHOLDS={
    "normal_max":0.45,
    "warning_max":0.70,
}

# Doctor feedback - entraînement / inférence
# Rejet (faux positif) : sur-échantillonner le vecteur comme inlier pour l’Isolation Forest uniquement.
FP_INLIER_OVERSAMPLE_COPIES:int=3
# Validation (vrai positif) : ne pas mélanger dans fit() ; banque d’exemplaires pour booster le score si proximité.
TP_EXEMPLAR_MAX_GLOBAL:int=2000
TP_EXEMPLAR_MAX_PER_PATIENT:int=500
TP_DISTANCE_SIGMA:float=1.0  # unités normalisées (écart-type effectif du noyau gaussien)
TP_BOOST_GAMMA:float=0.22   # plafond de boost ajouté au score IF [0,1]

MODEL_DIR=os.path.join(os.path.dirname(__file__),"ml_models")
DEFAULT_MODEL_PATH=os.path.join(MODEL_DIR,"isolation_forest_latest.joblib")

_lock=threading.Lock()
_model:Optional[IsolationForest]=None
_model_version:str="v0.0.0"
_model_trained_at:Optional[str]=None
_ml_thresholds:Dict[str,float]=dict(DEFAULT_ML_THRESHOLDS)
# Banque TP : chargée avec le modèle, mise à jour au réentraînement (pas dans fit IF).
_tp_exemplars_global:np.ndarray=np.zeros((0,len(FEATURE_NAMES)))
_tp_exemplars_by_patient:Dict[str,np.ndarray]={}

def _ensure_model_dir():
    os.makedirs(MODEL_DIR,exist_ok=True)

def get_model_version()->str:
    return _model_version

def get_model_info()->Dict[str,Any]:
    n_pat=0 if not _tp_exemplars_by_patient else sum(
        1 for _k,_arr in _tp_exemplars_by_patient.items() if isinstance(_arr,np.ndarray) and _arr.size>0
    )
    return{
        "version":_model_version,
        "trained_at":_model_trained_at,
        "loaded": _model is not None,
        "thresholds":dict(_ml_thresholds),
        "features":list(FEATURE_NAMES),
        "tp_exemplars_global":int(_tp_exemplars_global.shape[0]),
        "tp_exemplars_patients":n_pat,
    }

def configure_thresholds(normal_max:Optional[float]=None, warning_max:Optional[float]=None):
    global _ml_thresholds
    if normal_max is not None:
        _ml_thresholds["normal_max"]=float(normal_max)
    if warning_max is not None:
        _ml_thresholds["warning_max"]=float(warning_max)

def load_model(path:Optional[str]=None)->bool:
    """Load a serialised Isolation Forest model from disk. Returns True on success."""
    global _model,_model_version,_model_trained_at,_tp_exemplars_global,_tp_exemplars_by_patient
    path=path or DEFAULT_MODEL_PATH
    if not os.path.isfile(path):
        logger.info("No persisted ML model at %s - will need initial training",path)
        return False
    try:
        with _lock:
            bundle=joblib.load(path)
            _model=bundle["model"]
            _model_version=bundle.get("version","v0.0.0")
            _model_trained_at=bundle.get("trained_at")
            _tp_exemplars_global=_coerce_tp_matrix(bundle.get("tp_exemplars_global"))
            raw_by=bundle.get("tp_exemplars_by_patient") or {}
            _tp_exemplars_by_patient={
                str(k):_coerce_tp_matrix(v) for k,v in raw_by.items()
            } if isinstance(raw_by,dict) else {}
        logger.info("ML model loaded: %s (trained %s)",_model_version,_model_trained_at)
        return True
    except Exception:
        logger.exception("Failed to load ML model from %s",path)
        return False

def save_model(path:Optional[str]=None):
    """Persist the current model to disk."""
    path=path or DEFAULT_MODEL_PATH
    _ensure_model_dir()
    bundle={
        "model":_model,
        "version":_model_version,
        "trained_at":_model_trained_at,
        "features":list(FEATURE_NAMES),
        "thresholds":dict(_ml_thresholds),
        "tp_exemplars_global":_tp_exemplars_global,
        "tp_exemplars_by_patient":dict(_tp_exemplars_by_patient),
    }
    joblib.dump(bundle,path)
    logger.info("ML model saved: %s → %s",_model_version,path)

def _impute_value(feature:str, value:Any)->Optional[float]:
    """Return a usable float or None if the value is irrecoverable."""
    if value is None:
        return None
    try:
        v=float(value)
    except (TypeError,ValueError):
        return None
    lo,hi=HARD_RANGES.get(feature,(-1e9,1e9))
    if v < lo or v > hi:
        return None
    return v

def prepare_feature_vector(measurement:Dict[str,Any])->Tuple[Optional[np.ndarray],List[str]]:
    """
    Build a 1×4 feature array from a measurement dict.
    Returns (vector, skip_reasons).  If vector is None the measurement
    cannot be scored (INVALID or too many missing values).
    """
    skip_reasons:List[str]=[]
    values:List[float]=[]

    for feat in FEATURE_NAMES:
        raw=measurement.get(feat)
        cleaned=_impute_value(feat,raw)
        if cleaned is None:
            skip_reasons.append(f"{feat}_missing_or_invalid")
            lo,hi=PHYSIOLOGICAL_RANGES[feat]
            cleaned=(lo+hi)/2.0
        values.append(cleaned)

    if measurement.get("status")=="INVALID":
        return None,["measurement_invalid"]

    required_present=sum(
        1 for feat in ("heart_rate","spo2","temperature")
        if measurement.get(feat) is not None
    )
    if required_present < 2:
        return None,skip_reasons+["too_many_missing_features"]

    return np.array(values).reshape(1,-1), skip_reasons

def _next_version()->str:
    """Increment the patch segment of the current version string."""
    parts=_model_version.lstrip("v").split(".")
    try:
        parts[-1]=str(int(parts[-1])+1)
    except (ValueError,IndexError):
        parts=["0","0","1"]
    return "v"+".".join(parts)

def _coerce_tp_matrix(raw:Any)->np.ndarray:
    """N×len(FEATURE_NAMES) float matrix; empty if invalid."""
    if raw is None:
        return np.zeros((0,len(FEATURE_NAMES)))
    try:
        arr=np.asarray(raw,dtype=float)
    except Exception:
        return np.zeros((0,len(FEATURE_NAMES)))
    if arr.size==0:
        return np.zeros((0,len(FEATURE_NAMES)))
    if arr.ndim==1:
        if arr.shape[0]!=len(FEATURE_NAMES):
            return np.zeros((0,len(FEATURE_NAMES)))
        return arr.reshape(1,-1)
    if arr.shape[1]!=len(FEATURE_NAMES):
        return np.zeros((0,len(FEATURE_NAMES)))
    return arr

def _physio_span_array()->np.ndarray:
    return np.array(
        [(PHYSIOLOGICAL_RANGES[f][1]-PHYSIOLOGICAL_RANGES[f][0]) for f in FEATURE_NAMES],
        dtype=float,
    )

def _max_tp_gaussian_weight(query_flat:np.ndarray, exemplars:np.ndarray)->float:
    """Poids max exp(-‖(q-e)/s‖² / (2σ²)) sur les lignes d’exemplars."""
    if exemplars is None or exemplars.size==0 or exemplars.shape[0]==0:
        return 0.0
    spans=np.maximum(_physio_span_array(),1e-6)
    q=query_flat.reshape(1,-1)
    diff=(exemplars-q)/spans
    d2=np.sum(diff*diff,axis=1)
    sig2=TP_DISTANCE_SIGMA*TP_DISTANCE_SIGMA
    w=np.exp(-d2/(2.0*sig2))
    return float(np.max(w))

def _compute_tp_exemplar_boost(vec_flat:np.ndarray,user_id_auth:Optional[str])->float:
    """Boost [0, TP_BOOST_GAMMA] selon proximité aux TP validés (global + patient)."""
    global _tp_exemplars_global,_tp_exemplars_by_patient
    w_g=_max_tp_gaussian_weight(vec_flat,_tp_exemplars_global)
    w_p=0.0
    if user_id_auth:
        uid=str(user_id_auth).strip()
        if uid and uid in _tp_exemplars_by_patient:
            w_p=_max_tp_gaussian_weight(vec_flat,_tp_exemplars_by_patient[uid])
    w=max(w_g,w_p)
    return float(TP_BOOST_GAMMA*w)

def _cap_tp_matrix_rows(mat:np.ndarray,max_rows:int)->np.ndarray:
    if mat.shape[0]<=max_rows:
        return mat
    return mat[-max_rows:,:]

def train_model(
    measurements:List[Dict[str,Any]],
    validated_anomalies:Optional[List[Dict[str,Any]]]=None,
    contamination:float=0.05,
    n_estimators:int=150,
    random_state:int=42,
)->Dict[str,Any]:
    """
    Train (or retrain) the Isolation Forest on historical measurements.

    Feedback médecin (validated_anomalies) :
    - rejected (faux positif) : sur-échantillonnage comme inliers dans fit() uniquement.
    - validated (vrai positif) : exclus du fit IF ; stockés comme banque d’exemplaires TP
      pour l’inférence (boost de score si proximité), optionnellement par patient.
    """
    global _model,_model_version,_model_trained_at,_tp_exemplars_global,_tp_exemplars_by_patient

    rows:List[np.ndarray]=[]
    for m in measurements:
        vec,_=prepare_feature_vector(m)
        if vec is not None:
            rows.append(vec.flatten())

    tp_global_rows:List[np.ndarray]=[]
    tp_by_patient:Dict[str,List[np.ndarray]]={}

    if validated_anomalies:
        for a in validated_anomalies:
            status=str(a.get("status") or "").strip().lower()
            m_data={feat: a.get(feat) for feat in FEATURE_NAMES}
            if "measurement" in a and a["measurement"]:
                m_data={feat: a["measurement"].get(feat) for feat in FEATURE_NAMES}
            vec,_=prepare_feature_vector(m_data)
            if vec is None:
                continue
            flat=vec.flatten()
            if status=="rejected":
                for _ in range(FP_INLIER_OVERSAMPLE_COPIES):
                    rows.append(flat.copy())
            elif status=="validated":
                tp_global_rows.append(flat.copy())
                uid=a.get("user_id_auth")
                if uid is not None and str(uid).strip():
                    u=str(uid).strip()
                    tp_by_patient.setdefault(u,[]).append(flat.copy())

    if len(rows)<20:
        raise ValueError(f"Not enough valid samples to train ({len(rows)} < 20)")

    X=np.array(rows)

    effective_contamination=min(contamination,0.5)

    model=IsolationForest(
        n_estimators=n_estimators,
        contamination=effective_contamination,
        random_state=random_state,
        n_jobs=-1,
    )
    model.fit(X)

    tg=np.array(tp_global_rows) if tp_global_rows else np.zeros((0,len(FEATURE_NAMES)))
    tg=_cap_tp_matrix_rows(tg,TP_EXEMPLAR_MAX_GLOBAL)
    tpat:Dict[str,np.ndarray]={}
    for uid,lst in tp_by_patient.items():
        arr=np.array(lst) if lst else np.zeros((0,len(FEATURE_NAMES)))
        tpat[uid]=_cap_tp_matrix_rows(arr,TP_EXEMPLAR_MAX_PER_PATIENT)

    with _lock:
        _model=model
        _model_version=_next_version()
        _model_trained_at=datetime.now(timezone.utc).isoformat()
        _tp_exemplars_global=tg
        _tp_exemplars_by_patient=tpat

    save_model()

    meta={
        "version":_model_version,
        "trained_at":_model_trained_at,
        "n_samples":len(rows),
        "n_features":X.shape[1],
        "contamination":effective_contamination,
        "n_estimators":n_estimators,
        "n_tp_exemplars_global":int(_tp_exemplars_global.shape[0]),
        "n_tp_exemplar_patients":len(_tp_exemplars_by_patient),
    }
    logger.info(
        "ML model trained: %s (%d IF rows, %d TP exemplars global)",
        _model_version,len(rows),_tp_exemplars_global.shape[0],
    )
    return meta

def _raw_score_to_normalized(raw_score:float)->float:
    """
    Isolation Forest decision_function return s negative scores for anomalies
    and positive scores for inliers. Typical range is [-0.3, 0.3] for
    moderately contaminated data.
    Map to 0-1 range where 1 = most anomalous.
    """
    clamped=max(-0.3,min(0.3,raw_score))
    return round(1.0-(clamped+0.3)/0.6,4)

def _score_to_level(score:float)->str:
    if score<=_ml_thresholds["normal_max"]:
        return "normal"
    if score<=_ml_thresholds["warning_max"]:
        return "warning"
    return "critical"

def _compute_contributing_variables(measurement:Dict[str,Any])->List[Dict[str,Any]]:
    """
    Simple interpretability: compare each observed value against its
    expected physiological range and compute a normalised deviation weight.
    """
    contributions:List[Dict[str,Any]]=[]
    deviations:List[float]=[]

    for feat in FEATURE_NAMES:
        raw=measurement.get(feat)
        if raw is None:
            deviations.append(0.0)
            continue
        try:
            val=float(raw)
        except (TypeError,ValueError):
            deviations.append(0.0)
            continue
        lo,hi=PHYSIOLOGICAL_RANGES[feat]
        span=hi-lo if hi>lo else 1.0
        if val<lo:
            dev=(lo-val)/span
        elif val>hi:
            dev=(val-hi)/span
        else:
            dev=0.0
        deviations.append(dev)

    total=sum(deviations) or 1.0
    for idx, feat in enumerate(FEATURE_NAMES):
        raw=measurement.get(feat)
        if raw is None:
            continue
        lo,hi=PHYSIOLOGICAL_RANGES[feat]
        contributions.append({
            "variable":feat,
            "observed_value":raw,
            "expected_min":lo,
            "expected_max":hi,
            "contribution_weight":round(deviations[idx]/total,4),
        })

    contributions.sort(key=lambda c:c["contribution_weight"],reverse=True)
    return contributions

def score_measurement(measurement:Dict[str,Any])->Dict[str,Any]:
    """
    Score a single measurement. This is the main entry point called from the
    ingestion pipeline.  Returns a dict with all ML decision fields.
    Performance target: < 100 ms.
    """
    result:Dict[str,Any]={
        "ml_score":None,
        "ml_level":None,
        "ml_model_version":_model_version,
        "ml_contributing_variables":[],
        "ml_skipped":False,
        "ml_skip_reasons":[],
        "ml_processed_at":datetime.now(timezone.utc).isoformat(),
    }

    vec,skip_reasons=prepare_feature_vector(measurement)
    if vec is None:
        result["ml_skipped"]=True
        result["ml_skip_reasons"]=skip_reasons
        return result

    with _lock:
        model=_model

    if model is None:
        result["ml_skipped"]=True
        result["ml_skip_reasons"]=["model_not_loaded"]
        return result

    try:
        raw_scores=model.decision_function(vec)
        raw=float(raw_scores[0])
    except Exception as exc:
        logger.exception("ML scoring failed")
        result["ml_skipped"]=True
        result["ml_skip_reasons"]=[f"scoring_error: {exc}"]
        return result

    base_score=_raw_score_to_normalized(raw)
    uid=measurement.get("user_id_auth") or measurement.get("patient_user_id_auth")
    tp_boost=_compute_tp_exemplar_boost(vec.flatten(),str(uid).strip() if uid else None)
    score=round(min(1.0,max(0.0,base_score+tp_boost)),4)
    level=_score_to_level(score)
    contribs=_compute_contributing_variables(measurement)

    if skip_reasons:
        result["ml_skip_reasons"]=skip_reasons

    suggestion=generate_clinical_suggestion(measurement,contribs,level)

    result.update({
        "ml_score":score,
        "ml_if_base_score":base_score,
        "ml_tp_exemplar_boost":round(tp_boost,4),
        "ml_level":level,
        "ml_contributing_variables":contribs,
        "ml_is_anomaly": level in ("warning","critical"),
        "ml_criticality":level,
        "ml_recommended_action":suggestion["recommended_action"],
        "ml_clinical_reasoning":suggestion["clinical_reasoning"],
        "ml_urgency":suggestion["urgency"],
    })
    return result

CLINICAL_RULES:List[Dict[str,Any]]=[
    {"condition":lambda m:(m.get("spo2") or 100)<88,
     "action":"Oxygénothérapie immédiate recommandée - SpO₂ critique",
     "reasoning":"SpO₂ < 88% : hypoxémie sévère",
     "urgency":"immediate"},
    {"condition":lambda m:(m.get("spo2") or 100)<92,
     "action":"Surveillance rapprochée SpO₂ - envisager oxygénothérapie",
     "reasoning":"SpO₂ < 92% : hypoxémie modérée",
     "urgency":"priority"},
    {"condition":lambda m:(m.get("heart_rate") or 70)>150,
     "action":"Évaluation cardiaque urgente - tachycardie sévère",
     "reasoning":"FC > 150 bpm : tachycardie sévère",
     "urgency":"immediate"},
    {"condition":lambda m:(m.get("heart_rate") or 70)>120,
     "action":"Surveillance cardiaque renforcée - tachycardie",
     "reasoning":"FC > 120 bpm : tachycardie",
     "urgency":"priority"},
    {"condition":lambda m:(m.get("heart_rate") or 70)<40,
     "action":"Évaluation cardiaque urgente - bradycardie sévère",
     "reasoning":"FC < 40 bpm : bradycardie sévère",
     "urgency":"immediate"},
    {"condition":lambda m:(m.get("heart_rate") or 70)<50,
     "action":"Surveillance cardiaque - bradycardie",
     "reasoning":"FC < 50 bpm : bradycardie",
     "urgency":"priority"},
    {"condition":lambda m:(m.get("temperature") or 37)>39.5,
     "action":"Antipyrétiques + bilan infectieux - hyperthermie sévère",
     "reasoning":"Température > 39.5°C : fièvre élevée",
     "urgency":"immediate"},
    {"condition":lambda m:(m.get("temperature") or 37)>38.0,
     "action":"Surveillance thermique renforcée - fièvre",
     "reasoning":"Température > 38°C : fièvre",
     "urgency":"priority"},
    {"condition":lambda m:(m.get("temperature") or 37)<35.0,
     "action":"Réchauffement actif - hypothermie",
     "reasoning":"Température < 35°C : hypothermie",
     "urgency":"immediate"},
    {"condition":lambda m:(m.get("temperature") or 37)<35.5,
     "action":"Surveillance thermique - hypothermie légère",
     "reasoning":"Température < 35.5°C : hypothermie légère",
     "urgency":"priority"},
]

URGENCY_ORDER={"immediate":3,"priority":2,"routine":1}

def generate_clinical_suggestion(
    measurement:Dict[str,Any],
    contributing_variables:List[Dict[str,Any]],
    ml_level:str,
)->Dict[str,Any]:
    """
    Deterministic clinical suggestion engine.
    Returns recommended_action, clinical_reasoning, urgency.
    """
    if ml_level=="normal":
        return{
            "recommended_action":"Aucune action requise - valeurs normales",
            "clinical_reasoning":[],
            "urgency":"routine",
        }

    triggered:List[Dict[str,str]]=[]
    max_urgency="routine"

    for rule in CLINICAL_RULES:
        try:
            if rule["condition"](measurement):
                triggered.append({
                    "reasoning":rule["reasoning"],
                    "urgency":rule["urgency"],
                })
                if URGENCY_ORDER.get(rule["urgency"],0)>URGENCY_ORDER.get(max_urgency,0):
                    max_urgency=rule["urgency"]
        except (TypeError,ValueError):
            continue

    top_vars=[v for v in contributing_variables if v.get("contribution_weight",0)>0.2]
    for cv in top_vars:
        var=cv["variable"]
        obs=cv.get("observed_value")
        lo=cv.get("expected_min")
        hi=cv.get("expected_max")
        if obs is not None and lo is not None and hi is not None:
            try:
                obs_f=float(obs)
                if obs_f<float(lo):
                    triggered.append({
                        "reasoning":f"{var} ({obs_f}) sous le seuil physiologique ({lo})",
                        "urgency":"priority" if ml_level=="critical" else "routine",
                    })
                elif obs_f>float(hi):
                    triggered.append({
                        "reasoning":f"{var} ({obs_f}) au-dessus du seuil physiologique ({hi})",
                        "urgency":"priority" if ml_level=="critical" else "routine",
                    })
            except (TypeError,ValueError):
                continue

    seen=set()
    unique_reasoning=[]
    for t in triggered:
        if t["reasoning"] not in seen:
            seen.add(t["reasoning"])
            unique_reasoning.append(t["reasoning"])
        if URGENCY_ORDER.get(t["urgency"],0)>URGENCY_ORDER.get(max_urgency,0):
            max_urgency=t["urgency"]

    if not unique_reasoning:
        if ml_level=="critical":
            unique_reasoning=["Score d'anomalie ML élevé - combinaison de paramètres atypique"]
            max_urgency="priority"
        else:
            unique_reasoning=["Déviation légère détectée par le modèle ML"]

    if triggered:
        action=triggered[0].get("action") if hasattr(triggered[0],"get") and "action" in triggered[0] else None
    else:
        action=None

    if not action:
        for rule in CLINICAL_RULES:
            try:
                if rule["condition"](measurement):
                    action=rule["action"]
                    break
            except (TypeError,ValueError):
                continue

    if not action:
        action=("Évaluation clinique recommandée" if ml_level=="critical"
                else "Surveillance renforcée conseillée")

    return{
        "recommended_action":action,
        "clinical_reasoning":unique_reasoning[:3],
        "urgency":max_urgency,
    }

def build_anomaly_event(
    device_id:str,
    user_id_auth:Optional[str],
    measurement_id:Any,
    measurement:Dict[str,Any],
    ml_result:Dict[str,Any],
    suggestion:Optional[Dict[str,Any]]=None,
)->Optional[Dict[str,Any]]:
    """
    If the ML level is 'critical', build an anomaly document ready for
    insertion into the ml_anomalies collection.
    Returns None if level is not critical.
    """
    if ml_result.get("ml_level")!="critical":
        return None

    event={
        "device_id":device_id,
        "user_id_auth":user_id_auth,
        "measurement_id":measurement_id,
        "measured_at":measurement.get("measured_at",datetime.now(timezone.utc)),
        "anomaly_score":ml_result["ml_score"],
        "anomaly_level":"critical",
        "model_version":ml_result["ml_model_version"],
        "contributing_variables":ml_result["ml_contributing_variables"],
        "status":"pending",
        "validated_by":None,
        "validated_at":None,
        "created_at":datetime.now(timezone.utc),
    }
    if suggestion:
        event["recommended_action"]=suggestion.get("recommended_action")
    event["clinical_reasoning"]=suggestion.get("clinical_reasoning",[])
    event["urgency"]=suggestion.get("urgency","routine")
    return event

FORECAST_FEATURES=["heart_rate","spo2","temperature"]

FEATURE_UNITS:Dict[str,str]={
    "heart_rate":"bpm",
    "spo2":"%",
    "temperature":"°C",
}

FEATURE_LABELS:Dict[str,str]={
    "heart_rate":"Fréquence cardiaque",
    "spo2":"SpO₂",
    "temperature":"Température",
}

FORECAST_MIN_SAMPLES=3
FORECAST_MAX_HORIZON_HOURS=72
FORECAST_EMA_HALF_LIFE_HOURS=4.0
PROPHET_MIN_HOURLY_POINTS=12  # Prophet: min hourly buckets (12h = half day)
CIRCADIAN_STRENGTH=0.6  # How much to apply hourly pattern when Prophet not used (0=flat, 1=full)
FORECAST_OUTLIER_IQR_FACTOR=2.0
FORECAST_TREND_P_THRESHOLD=0.05

CLINICAL_THRESHOLDS:Dict[str,Dict[str,float]]={
    "heart_rate":{"low_critical":40,"low_warning":50,"high_warning":100,"high_critical":120},
    "spo2":{"low_critical":88,"low_warning":92,"high_warning":100,"high_critical":100},
    "temperature":{"low_critical":35.0,"low_warning":35.5,"high_warning":38.0,"high_critical":39.0},
}

TREND_STRENGTH_THRESHOLDS:Dict[str,Dict[str,float]]={
    "heart_rate":{"negligible":0.5,"mild":2.0,"moderate":5.0},
    "spo2":{"negligible":0.2,"mild":0.5,"moderate":1.0},
    "temperature":{"negligible":0.1,"mild":0.3,"moderate":0.5},
}

def _normal_cdf(x:float)->float:
    """Standard normal CDF via the error function (no scipy needed)."""
    return 0.5*(1.0+math.erf(x/math.sqrt(2.0)))

def _t_critical(n:int)->float:
    """Approximate t critical value for 95% two-sided PI with n-2 dof."""
    dof=max(n-2,1)
    if dof>=120: return 1.96
    if dof>=60: return 2.00
    if dof>=30: return 2.04
    if dof>=20: return 2.09
    if dof>=15: return 2.13
    if dof>=10: return 2.23
    if dof>=5: return 2.57
    return 3.18

def _preprocess_series(
    times:np.ndarray,values:np.ndarray,feat:str
)->Tuple[np.ndarray,np.ndarray,int]:
    """Remove hard-range violations and IQR outliers. Returns (times, values, n_removed)."""
    n_orig=len(values)

    hard_lo,hard_hi=HARD_RANGES.get(feat,(-1e9,1e9))
    mask=(values>=hard_lo)&(values<=hard_hi)
    times,values=times[mask],values[mask]

    if len(values)>10:
        q1,q3=np.percentile(values,[25,75])
        iqr=q3-q1
        lo=q1-FORECAST_OUTLIER_IQR_FACTOR*iqr
        hi=q3+FORECAST_OUTLIER_IQR_FACTOR*iqr
        mask=(values>=lo)&(values<=hi)
        times,values=times[mask],values[mask]

    return times,values,n_orig-len(values)

def _compute_ema(
    times:np.ndarray,values:np.ndarray,half_life_hours:float
)->np.ndarray:
    """Time-aware exponential moving average - adapts to irregular spacing."""
    if len(values)==0:
        return np.array([])
    ema=np.zeros_like(values,dtype=float)
    ema[0]=values[0]
    for i in range(1,len(values)):
        dt=max(times[i]-times[i-1],0.001)
        alpha=1.0-math.exp(-math.log(2)*dt/half_life_hours)
        ema[i]=alpha*values[i]+(1.0-alpha)*ema[i-1]
    return ema

def _mann_kendall(values:np.ndarray)->Tuple[float,float]:
    """
    Mann-Kendall non-parametric monotonic trend test.
    Returns (Kendall tau, two-sided p-value).
    """
    n=len(values)
    if n<4:
        return 0.0,1.0

    s=0
    for k in range(n-1):
        for j in range(k+1,n):
            diff=values[j]-values[k]
            if diff>0:
                s+=1
            elif diff<0:
                s-=1

    var_s=n*(n-1)*(2*n+5)/18.0
    if var_s<1e-10:
        return 0.0,1.0

    if s>0:
        z=(s-1)/math.sqrt(var_s)
    elif s<0:
        z=(s+1)/math.sqrt(var_s)
    else:
        return 0.0,1.0

    p_value=2.0*(1.0-_normal_cdf(abs(z)))
    tau=2.0*s/(n*(n-1))
    return float(tau),float(p_value)

def _wls_with_prediction_intervals(
    times:np.ndarray,
    values:np.ndarray,
    weights:np.ndarray,
    forecast_times:np.ndarray,
    feat:str,
    anchor:Optional[tuple]=None,
)->Dict[str,Any]:
    """
    Weighted least squares with prediction intervals that correctly widen
    as extrapolation distance from the data centroid increases.
    When anchor=(t_last, last_ema) is given, predictions are anchored to last_ema
    for continuity: pred = last_ema + slope*(x0 - t_last).

    PI formula: ŷ ± t_{α/2,n-2} · s_e · √(1 + 1/n + (x₀ - x̄)²/Sxx)
    """
    n=len(values)
    X=times.reshape(-1,1)

    reg=LinearRegression()
    reg.fit(X,values,sample_weight=weights)

    slope=float(reg.coef_[0])
    intercept=float(reg.intercept_)
    y_hat_in=reg.predict(X)
    residuals=values-y_hat_in

    w_sum=float(np.sum(weights))
    x_bar=float(np.average(times,weights=weights))
    sxx=float(np.sum(weights*(times-x_bar)**2))

    dof=max(n-2,1)
    se_sq=float(np.sum(weights*residuals**2))/(w_sum*dof/n) if w_sum > 0 else float(np.var(residuals))
    s_e=math.sqrt(max(se_sq,1e-10))

    ss_tot=float(np.sum(weights*(values-np.average(values,weights=weights))**2))
    ss_res=float(np.sum(weights*residuals**2))
    r_squared=max(0.0,1.0-ss_res/max(ss_tot,1e-10)) if ss_tot > 1e-10 else 0.0

    t_val=_t_critical(n)
    hard_lo,hard_hi=HARD_RANGES.get(feat,(-1e9,1e9))

    anchor_t,anchor_val=(anchor[0],anchor[1]) if anchor and len(anchor)==2 else (None,None)

    predictions=[]
    for x0 in forecast_times:
        if anchor_t is not None and anchor_val is not None:
            y_hat=anchor_val+slope*(float(x0)-anchor_t)
        else:
            y_hat=slope*float(x0)+intercept
        leverage=1.0+1.0/n+(float(x0)-x_bar)**2/max(sxx,1e-10)
        pi_half=t_val*s_e*math.sqrt(leverage)

        clamped=float(np.clip(y_hat,hard_lo,hard_hi))
        lower=float(np.clip(y_hat-pi_half,hard_lo,hard_hi))
        upper=float(np.clip(y_hat+pi_half,hard_lo,hard_hi))

        predictions.append({
            "value":round(clamped,2),
            "lower":round(lower,2),
            "upper":round(upper,2),
        })

    return{
        "slope":slope,
        "intercept":intercept,
        "s_e":s_e,
        "r_squared":r_squared,
        "predictions":predictions,
    }


def _try_prophet_predict(
    base_ts:datetime,
    clean_t:np.ndarray,
    clean_v:np.ndarray,
    last_ts:datetime,
    horizon_hours:int,
    feat:str,
)->Optional[List[Dict[str,float]]]:
    """
    Try Prophet forecast for a single feature. Returns list of {value, lower, upper}
    or None on any failure. Safe: no exception propagates, output clamped to HARD_RANGES.
    """
    try:
        import pandas as pd
        from prophet import Prophet
    except ImportError:
        logger.info("Prophet non installé, utilisation du modèle linéaire + circadien")
        return None

    if len(clean_v)<PROPHET_MIN_HOURLY_POINTS:
        return None

    lo,hi=HARD_RANGES.get(feat,(-1e9,1e9))

    try:
        hour_from_base=np.floor(clean_t).astype(int)
        agg:Dict[int,List[float]]={}
        for i in range(len(clean_t)):
            h=int(hour_from_base[i])
            agg.setdefault(h,[]).append(float(clean_v[i]))

        rows=[{"ds":base_ts+timedelta(hours=h),"y":float(np.mean(vals))} for h,vals in sorted(agg.items())]
        df=pd.DataFrame(rows)
        df["y"]=np.clip(df["y"].values,lo,hi)

        if len(df)<PROPHET_MIN_HOURLY_POINTS:
            logger.debug("Prophet %s: données insuffisantes (%d tranches horaires)",feat,len(df))
            return None

        m=Prophet(
            daily_seasonality=True,
            weekly_seasonality=True,
            yearly_seasonality=False,
            seasonality_mode="additive",
            uncertainty_samples=100,
        )
        m.fit(df)

        future=m.make_future_dataframe(periods=int(horizon_hours),freq="h")
        forecast=m.predict(future)
        tail=forecast.tail(int(horizon_hours))

        preds:List[Dict[str,float]]=[]
        for _,row in tail.iterrows():
            v=float(np.clip(row["yhat"],lo,hi))
            v_lo=float(np.clip(row["yhat_lower"],lo,hi))
            v_hi=float(np.clip(row["yhat_upper"],lo,hi))
            if not (math.isfinite(v) and math.isfinite(v_lo) and math.isfinite(v_hi)):
                return None
            preds.append({"value":round(v,2),"lower":round(v_lo,2),"upper":round(v_hi,2)})

        if len(preds)!=horizon_hours:
            return None
        logger.info("Prophet utilisé pour %s (%d points)",feat,len(preds))
        return preds
    except Exception as e:
        logger.info("Prophet fallback pour %s: %s",feat,str(e))
        return None


def _apply_circadian_to_predictions(
    base_ts:datetime,
    clean_t:np.ndarray,
    clean_v:np.ndarray,
    forecast_times:np.ndarray,
    predictions:List[Dict[str,float]],
    feat:str,
    strength:float,
)->List[Dict[str,float]]:
    """
    Apply circadian (hour-of-day) pattern to linear predictions for more realistic variation.
    Uses historical mean per hour vs global mean. strength in [0,1].
    """
    if len(predictions)==0 or strength<=0:
        return predictions
    lo,hi=HARD_RANGES.get(feat,(-1e9,1e9))
    global_mean=float(np.mean(clean_v))
    hourly_sum:Dict[int,List[float]]={}
    for i in range(len(clean_t)):
        dt=base_ts+timedelta(hours=float(clean_t[i]))
        hod=dt.hour
        hourly_sum.setdefault(hod,[]).append(float(clean_v[i]))
    if len(hourly_sum)<6:
        return predictions
    hourly_mean={h:float(np.mean(v)) for h,v in hourly_sum.items()}
    result=[]
    for j,pred in enumerate(predictions):
        t=forecast_times[j] if j<len(forecast_times) else 0
        dt=base_ts+timedelta(hours=float(t))
        hod=dt.hour
        deviation=hourly_mean.get(hod,global_mean)-global_mean
        adj=deviation*strength
        v=float(np.clip(pred["value"]+adj,lo,hi))
        v_lo=float(np.clip(pred["lower"]+adj,lo,hi))
        v_hi=float(np.clip(pred["upper"]+adj,lo,hi))
        result.append({"value":round(v,2),"lower":round(v_lo,2),"upper":round(v_hi,2)})
    return result


def _classify_trend(feat:str,slope_per_hour:float,p_value:float)->Dict[str,Any]:
    """Classify trend direction + strength with statistical significance gate."""
    significant=p_value<FORECAST_TREND_P_THRESHOLD
    slope_per_day=slope_per_hour*24.0
    abs_spd=abs(slope_per_day)

    thresholds=TREND_STRENGTH_THRESHOLDS.get(
        feat,{"negligible":0.01,"mild":0.1,"moderate":0.5}
    )

    if abs_spd<thresholds["negligible"] or not significant:
        return{"label":"stable","strength":"negligible",
               "slope_per_hour":round(slope_per_hour,6),
               "slope_per_day":round(slope_per_day,3),
               "p_value":round(p_value,4),"significant":significant}

    if abs_spd<thresholds["mild"]:
        strength="mild"
    elif abs_spd<thresholds["moderate"]:
        strength="moderate"
    else:
        strength="strong"

    label="increasing" if slope_per_hour > 0 else "decreasing"
    return{"label":label,"strength":strength,
           "slope_per_hour":round(slope_per_hour,6),
           "slope_per_day":round(slope_per_day,3),
           "p_value":round(p_value,4),"significant":significant}

def _detect_clinical_drift(
    ema_values:np.ndarray,times:np.ndarray,feat:str
)->List[Dict[str,Any]]:
    """Detect progressive drift toward clinical warning/critical thresholds."""
    alerts:List[Dict[str,Any]]=[]
    thresholds=CLINICAL_THRESHOLDS.get(feat)
    if not thresholds or len(ema_values)<5:
        return alerts

    current=float(ema_values[-1])
    window_n=min(20,len(ema_values))
    window=ema_values[-window_n:]
    window_t=times[-window_n:]

    dt=float(window_t[-1]-window_t[0])
    if dt<0.1:
        return alerts

    slope_h=(float(window[-1])-float(window[0]))/dt
    feat_label=FEATURE_LABELS.get(feat,feat)
    unit=FEATURE_UNITS.get(feat,"")

    checks:List[Tuple[str,float,str]]=[]
    if slope_h>0:
        for lvl in ("warning","critical"):
            th=thresholds.get(f"high_{lvl}")
            if th is not None and current<th:
                checks.append((lvl,th,"hausse"))
    elif slope_h<0:
        for lvl in ("warning","critical"):
            th=thresholds.get(f"low_{lvl}")
            if th is not None and current>th:
                checks.append((lvl,th,"baisse"))

    for lvl, th, direction in checks:
        gap=abs(th-current)
        hours=gap/abs(slope_h) if abs(slope_h) > 1e-8 else 9999
        if 0 < hours < 72:
            alerts.append({
                "type":"progressive_drift",
                "severity":lvl,
                "direction":direction,
                "target_threshold":th,
                "estimated_breach_hours":round(hours,1),
                "message":(
                    f"{feat_label} en {direction}: seuil {lvl} "
                    f"({th}{unit}) estimé dans ~{round(hours)}h"
                ),
            })

    return alerts

def _compute_regularity(times:np.ndarray)->float:
    """Coefficient of variation of inter-measurement gaps → 1 = regular, 0 = chaotic."""
    if len(times)<2:
        return 0.0
    diffs=np.diff(times)
    mean_d=float(np.mean(diffs))
    if mean_d<1e-6:
        return 0.0
    cv=float(np.std(diffs))/mean_d
    return max(0.0,min(1.0,1.0-min(cv,2.0)/2.0))

def _confidence_score(
    n_samples:int,time_span_hours:float,regularity:float,
    r_squared:float,p_value:float,n_outliers:int,
)->int:
    """Composite confidence score (0-100) combining data quality metrics."""
    s=0.0

    if n_samples>=100:s+=25
    elif n_samples>=50:s+=20
    elif n_samples>=20:s+=15
    elif n_samples>=10:s+=8
    else:s+=3

    if time_span_hours>=168:s+=20
    elif time_span_hours>=72:s+=15
    elif time_span_hours>=24:s+=10
    else:s+=5

    s+=20.0*regularity
    s+=20.0*max(0.0,min(1.0,r_squared))

    if p_value<0.01:s+=15
    elif p_value<0.05:s+=10
    elif p_value<0.10:s+=5

    total=n_samples+n_outliers
    if total>0:
        rate=n_outliers/total
        if rate>0.10:s-=10
        elif rate>0.05:s-=5

    return max(0,min(100,int(round(s))))

def _build_feature_description(
    feat:str,trend:Dict,ema_last:float,alerts:List
)->str:
    """Auto-generate a doctor-facing text description per vital sign."""
    fl=FEATURE_LABELS.get(feat,feat)
    unit=FEATURE_UNITS.get(feat,"")
    label=trend["label"]
    strength=trend["strength"]
    spd=abs(trend.get("slope_per_day",0))
    p=trend.get("p_value",1)

    if label=="stable" or strength=="negligible":
        txt=f"{fl} stable (EMA: {round(ema_last,1)}{unit})"
    else:
        d="en hausse" if label=="increasing" else "en baisse"
        sf={"mild":"légère","moderate":"modérée","strong":"marquée"}.get(strength,"")
        sign="+" if label=="increasing" else "-"
        sig=f", p={round(p,3)}" if p < 0.1 else ""
        txt=f"{fl} {d} {sf} ({sign}{round(spd,1)} {unit}/jour{sig})"

    for a in alerts:
        txt+=f" - {a['message']}"
    return txt

def _generate_summary(vitals:Dict[str,Dict])->Dict[str,Any]:
    """Aggregate per-vital analysis into a global summary for the doctor."""
    sev_order={"normal":0,"negligible":0,"mild":1,"moderate":2,
               "warning":3,"strong":4,"critical":5}
    texts:List[str]=[]
    max_sev="normal"

    for feat, info in vitals.items():
        if info.get("status")!="ok":
            continue
        desc=info.get("description","")
        if desc:
            texts.append(desc)

        for a in info.get("clinical_alerts",[]):
            sev=a.get("severity","warning")
            if sev_order.get(sev,0)>sev_order.get(max_sev,0):
                max_sev=sev

        strength=info.get("trend",{}).get("strength","negligible")
        if sev_order.get(strength,0)>sev_order.get(max_sev,0):
            max_sev=strength

    if max_sev in ("critical","strong"):
        risk,action="high","Consultation médicale recommandée"
    elif max_sev in ("warning","moderate"):
        risk,action="moderate","Surveillance renforcée recommandée"
    elif max_sev=="mild":
        risk,action="low","Surveillance standard"
    else:
        risk,action="minimal","Pas d'action nécessaire"

    return{
        "text":". ".join(texts)+"." if texts else "Données insuffisantes.",
        "risk_level":risk,
        "recommended_action":action,
    }

def forecast_vitals(
    measurements:List[Dict[str,Any]],
    horizon:int=24,
    history_window_hours:Optional[float]=None,
)->Dict[str,Any]:
    """
    Professional time-series forecast with:
    - horizon: number of HOURS to forecast (e.g. 24 = full next day)
    - Fixed 1-hour step for predictable 24h coverage
    - Robust preprocessing (IQR outlier removal, hard-range filtering)
    - Time-aware EMA smoothing, predictions anchored to last EMA for continuity
    - Mann-Kendall statistical trend test (non-parametric, no linearity assumption)
    - Proper prediction intervals that widen with extrapolation distance
    - Per-vital confidence score (0-100)
    """
    for m in measurements:
        if not m.get("measured_at") and m.get("timestamp"):
            m["measured_at"]=m["timestamp"]

    sorted_m=sorted(
        [m for m in measurements if m.get("measured_at")],
        key=lambda m:m["measured_at"],
    )

    if len(sorted_m)<FORECAST_MIN_SAMPLES:
        raise ValueError(
            f"Not enough data points ({len(sorted_m)} < {FORECAST_MIN_SAMPLES})"
        )

    def _parse_ts(ts):
        if isinstance(ts,str):
            ts=datetime.fromisoformat(ts.replace("Z","+00:00"))
        if ts.tzinfo is not None:
            ts=ts.replace(tzinfo=None)
        return ts

    base_ts=_parse_ts(sorted_m[0]["measured_at"])

    def _ts_hours(ts)->float:
        return (_parse_ts(ts)-base_ts).total_seconds()/3600.0

    time_idx=np.array([_ts_hours(m["measured_at"]) for m in sorted_m])
    time_span=float(time_idx[-1]-time_idx[0]) if len(time_idx) > 1 else 0
    avg_gap=time_span/max(len(time_idx)-1,1) if time_span > 0.01 else 1.0
    regularity=_compute_regularity(time_idx)

    # horizon = hours to forecast; fixed 1h step for predictable coverage (e.g. 24h = 24 points)
    horizon_hours=int(max(1,min(horizon,FORECAST_MAX_HORIZON_HOURS)))
    forecast_times=np.array([
        time_idx[-1]+(i+1) for i in range(horizon_hours)
    ])
    forecast_times=forecast_times[
        forecast_times<=time_idx[-1]+FORECAST_MAX_HORIZON_HOURS
    ]
    if len(forecast_times)==0:
        forecast_times=np.array([time_idx[-1]+1])
    actual_horizon=len(forecast_times)

    last_ts=_parse_ts(sorted_m[-1]["measured_at"])
    forecast_timestamps=[
        (last_ts+timedelta(hours=i+1)).isoformat()
        for i in range(actual_horizon)
    ]

    history_points_all:List[Dict[str,Any]]=[]
    for idx, m in enumerate(sorted_m):
        pt:Dict[str,Any]={
            "t_hours":round(float(time_idx[idx]),2),
            "timestamp":str(m["measured_at"]),
        }
        for feat in FORECAST_FEATURES:
            val=m.get(feat)
            if val is not None:
                try:
                    pt[feat]=round(float(val),2)
                except (TypeError,ValueError):
                    pass
        history_points_all.append(pt)

    if history_window_hours is not None:
        hist_cutoff=float(time_idx[-1]-max(float(history_window_hours),0.0))
        history_points=[
            p for p in history_points_all
            if float(p.get("t_hours",0.0))>=hist_cutoff
        ]
    else:
        history_points=history_points_all

    vitals:Dict[str,Any]={}
    all_warnings:List[str]=[]
    total_outliers=0
    n_global=len(time_idx)
    recency_w=np.linspace(0.3,1.0,n_global)

    predictions_flat:List[Dict[str,Any]]=[
        {"t_hours":round(float(t),2),"timestamp": forecast_timestamps[j] if j<len(forecast_timestamps) else None}
        for j, t in enumerate(forecast_times)
    ]

    for feat in FORECAST_FEATURES:
        raw_vals:List[float]=[]
        raw_times:List[float]=[]
        raw_w:List[float]=[]

        for i, m in enumerate(sorted_m):
            v=m.get(feat)
            if v is not None:
                try:
                    raw_vals.append(float(v))
                    raw_times.append(float(time_idx[i]))
                    raw_w.append(float(recency_w[i]))
                except (TypeError,ValueError):
                    continue

        if len(raw_vals)<FORECAST_MIN_SAMPLES:
            vitals[feat]={
                "unit":FEATURE_UNITS.get(feat,""),"status":"insufficient_data",
                "n_samples":len(raw_vals),
                "trend":{"label":"unknown","strength":"unknown",
                         "significant":False,"slope_per_hour":0,
                         "slope_per_day":0,"p_value":1.0},
                "confidence_score":0,"predictions":[],
                "clinical_alerts":[],"description":"Données insuffisantes",
            }
            all_warnings.append(f"{feat}_insufficient_data")
            continue

        t_arr=np.array(raw_times)
        v_arr=np.array(raw_vals)

        clean_t,clean_v,n_removed=_preprocess_series(t_arr,v_arr,feat)
        total_outliers+=n_removed
        if n_removed>0:
            all_warnings.append(f"{feat}_{n_removed}_outliers_removed")

        if len(clean_v)<3:
            vitals[feat]={
                "unit":FEATURE_UNITS.get(feat,""),
                "status":"insufficient_after_cleaning",
                "n_samples":len(clean_v),
                "trend":{"label":"unknown","strength":"unknown",
                         "significant":False,"slope_per_hour":0,
                         "slope_per_day":0,"p_value":1.0},
                "confidence_score":0,"predictions":[],
                "clinical_alerts":[],"description":"Données insuffisantes après nettoyage",
            }
            continue

        clean_w=np.linspace(0.3,1.0,len(clean_v))

        ema=_compute_ema(clean_t,clean_v,FORECAST_EMA_HALF_LIFE_HOURS)

        mk_tau,mk_p=_mann_kendall(ema)

        wls=_wls_with_prediction_intervals(
            clean_t,clean_v,clean_w,forecast_times,feat,
            anchor=(float(clean_t[-1]),float(ema[-1])),
        )

        prophet_preds=_try_prophet_predict(
            base_ts,clean_t,clean_v,last_ts,actual_horizon,feat
        )
        use_preds=prophet_preds if prophet_preds is not None else wls["predictions"]
        if prophet_preds is None and CIRCADIAN_STRENGTH>0:
            use_preds=_apply_circadian_to_predictions(
                base_ts,clean_t,clean_v,forecast_times,use_preds,feat,CIRCADIAN_STRENGTH
            )

        trend=_classify_trend(feat,wls["slope"],mk_p)

        clinical_alerts=_detect_clinical_drift(ema,clean_t,feat)

        feat_span=float(clean_t[-1]-clean_t[0]) if len(clean_t) > 1 else 0
        feat_conf=_confidence_score(
            len(clean_v),feat_span,regularity,
            wls["r_squared"],mk_p,n_removed,
        )

        lo,hi=PHYSIOLOGICAL_RANGES.get(feat,(-1e9,1e9))

        preds_list=[]
        for j, pred in enumerate(use_preds):
            in_range=lo<=pred["value"]<=hi
            entry={
                "t_hours":round(float(forecast_times[j]),2),
                "timestamp":forecast_timestamps[j] if j<len(forecast_timestamps) else None,
                "value":pred["value"],
                "lower":pred["lower"],
                "upper":pred["upper"],
                "in_physiological_range":in_range,
            }
            preds_list.append(entry)

            predictions_flat[j][feat]=pred["value"]
            predictions_flat[j][f"{feat}_upper"]=pred["upper"]
            predictions_flat[j][f"{feat}_lower"]=pred["lower"]
            predictions_flat[j][f"{feat}_alert"]=not in_range

        desc=_build_feature_description(feat,trend,float(ema[-1]),clinical_alerts)

        vitals[feat]={
            "unit":FEATURE_UNITS.get(feat,""),
            "status":"ok",
            "n_samples":len(clean_v),
            "n_outliers_removed":n_removed,
            "current_ema":round(float(ema[-1]),2),
            "last_raw":round(float(clean_v[-1]),2),
            "physiological_range":[lo,hi],
            "trend":trend,
            "confidence_score":feat_conf,
            "r_squared":round(wls["r_squared"],4),
            "residual_std":round(wls["s_e"],4),
            "predictions":preds_list,
            "clinical_alerts":clinical_alerts,
            "description":desc,
        }

    data_quality={
        "n_raw":len(measurements),
        "n_used":len(sorted_m),
        "n_outliers_removed":total_outliers,
        "time_span_hours":round(time_span,2),
        "avg_interval_hours":round(avg_gap,2),
        "regularity_score":round(regularity,3),
        "warnings":all_warnings,
    }

    summary=_generate_summary(vitals)

    ok_scores=[v["confidence_score"] for v in vitals.values() if v.get("status")=="ok"]
    global_confidence=round(sum(ok_scores)/len(ok_scores)) if ok_scores else 0

    return {
        "model_version":"forecast-v3.0",
        "generated_at":datetime.now(timezone.utc).isoformat(),
        "n_measurements":len(sorted_m),
        "horizon":actual_horizon,
        "avg_gap_hours":round(avg_gap,2),
        "confidence_score":global_confidence,
        "data_quality":data_quality,
        "vitals":vitals,
        "summary":summary,
        "history":history_points,
        "predictions":predictions_flat,
    }

MOVING_AVG_WINDOWS=[6,12,24]

def _compute_moving_averages(values:np.ndarray,times:np.ndarray,windows:List[int])->Dict[str,List[Optional[float]]]:
    """Compute multiple time-window moving averages over irregularly-spaced data."""
    result:Dict[str,List[Optional[float]]]={}
    n=len(values)
    for w in windows:
        key=f"ma_{w}"
        ma:List[Optional[float]]=[]
        for i in range(n):
            t_cutoff=times[i]-w
            mask=(times>=t_cutoff)&(times<=times[i])
            window_vals=values[mask]
            if len(window_vals)>=2:
                ma.append(round(float(np.mean(window_vals)),2))
            else:
                ma.append(None)
        result[key]=ma
    return result

def _compute_vital_statistics(values:np.ndarray)->Dict[str,Any]:
    """Compute descriptive statistics for a vital sign series."""
    if len(values)==0:
        return{}
    return{
        "mean":round(float(np.mean(values)),2),
        "median":round(float(np.median(values)),2),
        "std":round(float(np.std(values)),2),
        "min":round(float(np.min(values)),2),
        "max":round(float(np.max(values)),2),
        "q25":round(float(np.percentile(values,25)),2),
        "q75":round(float(np.percentile(values,75)),2),
        "iqr":round(float(np.percentile(values,75)-np.percentile(values,25)),2),
        "cv":round(float(np.std(values)/np.mean(values))*100,2) if np.mean(values) != 0 else 0,
        "count":int(len(values)),
    }

def _detect_anomalous_points(
    values:np.ndarray,times:np.ndarray,feat:str
)->List[Dict[str,Any]]:
    """Detect individual anomalous data points using physiological ranges + IQR."""
    anomalies:List[Dict[str,Any]]=[]
    lo,hi=PHYSIOLOGICAL_RANGES.get(feat,(0,100))

    q1,q3=(np.percentile(values,25),np.percentile(values,75)) if len(values) > 4 else (lo,hi)
    iqr=q3-q1
    stat_lo=q1-1.5*iqr
    stat_hi=q3+1.5*iqr

    for i,(v,t) in enumerate(zip(values,times)):
        reasons=[]
        severity="normal"
        if v<lo:
            reasons.append("below_physiological_min")
            severity="warning"
        elif v>hi:
            reasons.append("above_physiological_max")
            severity="warning"
        if v<stat_lo or v>stat_hi:
            reasons.append("statistical_outlier")
        if severity=="normal":
            severity="warning"

        hard_lo,hard_hi=HARD_RANGES.get(feat,(0,999))
        if v<hard_lo or v>hard_hi:
            severity="critical"
            reasons.append("outside_hard_range")

        if reasons:
            anomalies.append({
                "index":i,
                "t_hours":round(float(t),2),
                "value":round(float(v),2),
                "severity":severity,
                "reasons":reasons,
            })
    return anomalies

def _compute_correlation_matrix(data:Dict[str,np.ndarray])->Dict[str,Dict[str,float]]:
    """Compute pairwise Pearson correlations between vital signs."""
    features=list(data.keys())
    result:Dict[str,Dict[str,float]]={}
    for i,f1 in enumerate(features):
        result[f1]={}
        for f2 in features:
            if len(data[f1])==len(data[f2]) and len(data[f1])>3:
                corr=float(np.corrcoef(data[f1],data[f2])[0,1])
                result[f1][f2]=round(corr,3) if not np.isnan(corr) else 0.0
            else:
                result[f1][f2]=0.0
    return result

def _segment_by_period(
    times:np.ndarray,values:np.ndarray,period_hours:float=24
)->List[Dict[str,Any]]:
    """Segment data into periods and compute stats per period (for daily patterns)."""
    if len(times)==0:
        return []
    segments:List[Dict[str,Any]]=[]
    t_min=float(times[0])
    t_max=float(times[-1])
    t=t_min
    while t<t_max:
        mask=(times>=t)&(times<t+period_hours)
        seg_vals=values[mask]
        if len(seg_vals)>0:
            segments.append({
                "start_hours":round(t,2),
                "end_hours":round(t+period_hours,2),
                "mean":round(float(np.mean(seg_vals)),2),
                "min":round(float(np.min(seg_vals)),2),
                "max":round(float(np.max(seg_vals)),2),
                "std":round(float(np.std(seg_vals)),2),
                "count":int(len(seg_vals)),
            })
        t+=period_hours
    return segments

def analyze_patient_vitals(
    measurements:List[Dict[str,Any]],
    ml_scores:Optional[List[Dict[str,Any]]]=None,
    anomaly_records:Optional[List[Dict[str,Any]]]=None,
)->Dict[str,Any]:
    """
    Comprehensive patient-level analysis combining:
    - Per-vital trend charts with multiple moving averages
    - Statistical summaries (mean, std, percentiles, CV)
    - Point-level anomaly detection (physiological + IQR)
    - ML anomaly score timeline (from ml_decisions)
    - Vital sign correlations
    - Daily segmentation for pattern detection
    - Forecast integration
    """
    for m in measurements:
        if not m.get("measured_at") and m.get("timestamp"):
            m["measured_at"]=m["timestamp"]

    sorted_m=sorted(
        [m for m in measurements if m.get("measured_at")],
        key=lambda m:m["measured_at"],
    )

    if len(sorted_m)<3:
        return{"status":"insufficient_data","n_measurements":len(sorted_m)}

    def _parse_ts_local(ts):
        if isinstance(ts,str):
            ts=datetime.fromisoformat(ts.replace("Z","+00:00"))
        if ts.tzinfo is not None:
            ts=ts.replace(tzinfo=None)
        return ts

    base_ts=_parse_ts_local(sorted_m[0]["measured_at"])

    def _ts_hours(ts)->float:
        return (_parse_ts_local(ts)-base_ts).total_seconds()/3600.0

    time_idx=np.array([_ts_hours(m["measured_at"]) for m in sorted_m])

    timeline:List[Dict[str,Any]]=[]
    for i, m in enumerate(sorted_m):
        pt:Dict[str,Any]={
            "t_hours":round(float(time_idx[i]),2),
            "timestamp":str(m["measured_at"]),
        }
        for feat in FORECAST_FEATURES:
            v=m.get(feat)
            if v is not None:
                try:
                    pt[feat]=round(float(v),2)
                except (TypeError,ValueError):
                    pass
        pt["ml_score"]=m.get("ml_score")
        pt["ml_level"]=m.get("ml_level")
        timeline.append(pt)

    vitals_analysis:Dict[str,Any]={}
    aligned_data:Dict[str,np.ndarray]={}

    for feat in FORECAST_FEATURES:
        raw_vals:List[float]=[]
        raw_times:List[float]=[]
        raw_timestamps:List[str]=[]

        for i, m in enumerate(sorted_m):
            v=m.get(feat)
            if v is not None:
                try:
                    raw_vals.append(float(v))
                    raw_times.append(float(time_idx[i]))
                    raw_timestamps.append(str(m["measured_at"]))
                except (TypeError,ValueError):
                    continue

        if len(raw_vals)<3:
            vitals_analysis[feat]={
                "status":"insufficient_data",
                "label":FEATURE_LABELS.get(feat,feat),
                "unit":FEATURE_UNITS.get(feat,""),
                "n_samples":len(raw_vals),
            }
            continue

        t_arr=np.array(raw_times)
        v_arr=np.array(raw_vals)
        aligned_data[feat]=v_arr

        statistics=_compute_vital_statistics(v_arr)

        ema=_compute_ema(t_arr,v_arr,FORECAST_EMA_HALF_LIFE_HOURS)

        ma_data=_compute_moving_averages(v_arr,t_arr,MOVING_AVG_WINDOWS)

        mk_tau,mk_p=_mann_kendall(ema)
        recency_w=np.linspace(0.3,1.0,len(v_arr))
        wls=_wls_with_prediction_intervals(t_arr,v_arr,recency_w,np.array([]),feat)
        trend=_classify_trend(feat,wls["slope"],mk_p)

        anomalous_points=_detect_anomalous_points(v_arr,t_arr,feat)

        clinical_alerts=_detect_clinical_drift(ema,t_arr,feat)

        daily_segments=_segment_by_period(t_arr,v_arr,24.0)

        lo,hi=PHYSIOLOGICAL_RANGES.get(feat,(0,100))

        series_points:List[Dict[str,Any]]=[]
        for j in range(len(v_arr)):
            pt={
                "t_hours":round(float(t_arr[j]),2),
                "timestamp":raw_timestamps[j],
                "value":round(float(v_arr[j]),2),
                "ema":round(float(ema[j]),2),
            }
            for ma_key,ma_vals in ma_data.items():
                pt[ma_key]=ma_vals[j]

            is_anomaly=any(a["index"]==j for a in anomalous_points)
            pt["is_anomaly"]=is_anomaly
            series_points.append(pt)

        vitals_analysis[feat]={
            "status":"ok",
            "label":FEATURE_LABELS.get(feat,feat),
            "unit":FEATURE_UNITS.get(feat,""),
            "n_samples":len(v_arr),
            "physiological_range":[lo,hi],
            "statistics":statistics,
            "trend":trend,
            "clinical_alerts":clinical_alerts,
            "anomalous_points":anomalous_points,
            "n_anomalies":len(anomalous_points),
            "daily_segments":daily_segments,
            "series":series_points,
        }

    correlations=_compute_correlation_matrix(aligned_data)

    ml_score_timeline:List[Dict[str,Any]]=[]
    if ml_scores:
        for d in ml_scores:
            ml_score_timeline.append({
                "timestamp":str(d.get("measured_at",d.get("processed_at",""))),
                "score":d.get("anomaly_score",0),
                "level":d.get("anomaly_level","normal"),
                "device_id":d.get("device_id"),
            })

    anomaly_summary:Dict[str,Any]={"total":0,"by_status":{},"recent":[]}
    if anomaly_records:
        anomaly_summary["total"]=len(anomaly_records)
        for a in anomaly_records:
            st=a.get("status","pending")
            anomaly_summary["by_status"][st]=anomaly_summary["by_status"].get(st,0)+1
        anomaly_summary["recent"]=[
            {
                "timestamp":str(a.get("measured_at","")),
                "score":a.get("anomaly_score",0),
                "level":a.get("anomaly_level","critical"),
                "status":a.get("status","pending"),
                "contributing_variables":a.get("contributing_variables",[]),
            }
            for a in anomaly_records[:20]
        ]

    time_span=float(time_idx[-1]-time_idx[0]) if len(time_idx) > 1 else 0

    return{
        "status":"ok",
        "generated_at":datetime.now(timezone.utc).isoformat(),
        "n_measurements":len(sorted_m),
        "time_span_hours":round(time_span,2),
        "timeline":timeline,
        "vitals":vitals_analysis,
        "correlations":correlations,
        "ml_score_timeline":ml_score_timeline,
        "anomaly_summary":anomaly_summary,
    }

def init_ml():
    """Call once at application startup to load a persisted model if available."""
    loaded=load_model()
    if not loaded:
        logger.info("No pre-trained ML model found. Train via /api/admin/ml/retrain.")
