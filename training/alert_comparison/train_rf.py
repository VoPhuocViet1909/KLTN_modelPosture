"""Fit ONLY RF on the old v3 dataset; preserve the deployed Transformer."""
import argparse
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import confusion_matrix

from common import (FEATURES, WINDOW, check_reference, environment, load_dataset,
                    sha256, win_stats, write_json)


def train(dataset, config, out, *, loso=False, jobs=-1):
    cfg = json.loads(Path(config).read_text(encoding='utf-8-sig'))
    x, y, g = load_dataset(dataset)
    counts = check_reference(x, y, g, cfg)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    features = win_stats(x)
    params = dict(n_estimators=300, class_weight='balanced', random_state=0, n_jobs=jobs)
    fold_results = {}
    if loso:
        for person in sorted(counts):
            mask = g != person
            if set(np.unique(y[mask])) != {0, 1}:
                raise ValueError(f'Train fold {person} does not contain two classes')
            rf = RandomForestClassifier(**params).fit(features[mask], y[mask])
            pred = rf.predict(features[~mask])
            tn, fp, fn, tp = confusion_matrix(y[~mask], pred, labels=[0, 1]).ravel()
            fold_results[person] = dict(n=int((~mask).sum()), tn=int(tn), fp=int(fp),
                                       fn=int(fn), tp=int(tp), accuracy=float((pred == y[~mask]).mean()))
    rf = RandomForestClassifier(**params).fit(features, y)
    model_path = out / 'posture_rf.joblib'
    joblib.dump(rf, model_path, compress=3)
    restored = joblib.load(model_path)  # artifact just written by this process
    np.testing.assert_allclose(rf.predict_proba(features[:32]),
                               restored.predict_proba(features[:32]), atol=0, rtol=0)
    env = environment()
    metadata = dict(format_version=1, features=FEATURES, window=WINDOW, angle_scale=30,
                    stats_order=['mean', 'std_ddof0', 'min', 'max'], parameters=params,
                    people=sorted(counts), counts=counts, n=len(y), bad_count=int(y.sum()),
                    dataset_sha256=sha256(dataset), reference_config_sha256=sha256(config),
                    model_sha256=sha256(model_path), environment=env, loso=fold_results,
                    provenance='Counts and class ratio match reference; not proof of historical byte identity.',
                    intended_test='New people excluded from all original training data')
    write_json(out / 'rf_metadata.json', metadata)
    packages = ('numpy', 'scipy', 'scikit-learn', 'joblib', 'threadpoolctl')
    (out / 'rf-requirements.txt').write_text(''.join(f'{p}=={env[p]}\n' for p in packages), encoding='utf-8')
    print(json.dumps({'output': str(out), 'counts': counts, 'bad': int(y.sum()),
                      'model_sha256': metadata['model_sha256']}, indent=2))
    return metadata


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dataset', required=True, type=Path)
    ap.add_argument('--reference-config', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path, help='New directory, never overwrite a run')
    ap.add_argument('--loso', action='store_true', help='Optional diagnostic RF LOSO; no Transformer training')
    ap.add_argument('--jobs', type=int, default=-1)
    a = ap.parse_args()
    train(a.dataset, a.reference_config, a.out, loso=a.loso, jobs=a.jobs)
