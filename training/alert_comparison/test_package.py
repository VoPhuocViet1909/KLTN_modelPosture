"""Notebook syntax/contract checks; optional tiny synthetic RF smoke test."""
import ast
import json
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


class NotebookTests(unittest.TestCase):
    def inventory_source(self):
        nb = json.loads((HERE / 'kaggle_train_rf_v3.ipynb').read_text(encoding='utf-8'))
        return next(''.join(c['source']) for c in nb['cells']
                    if c['cell_type'] == 'code' and 'video_manifest.json' in ''.join(c['source'])
                    and 'side_videos = ' in ''.join(c['source']))

    def test_inventory_without_digest_or_imports(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data, run = root/'videos', root/'run'
            data.mkdir()
            run.mkdir()
            (data/'P01_S01_GOOD_01.mp4').write_bytes(b'fixture; only hashing, no decode')
            env = dict(MODE='video', DATA_DIR=str(data), RUN_DIR=run)
            exec(compile(self.inventory_source(), 'inventory', 'exec'), env)
            manifest = json.loads((run/'video_manifest.json').read_text())
            self.assertEqual(len(manifest), 1)
            self.assertEqual(manifest[0]['sha256'], hashlib.sha256(b'fixture; only hashing, no decode').hexdigest())
            # NPZ mode must not require a dataset directory or run directory.
            exec(compile(self.inventory_source(), 'inventory', 'exec'),
                 dict(MODE='npz', DATASET_PATH=root/'old.npz'))

    def test_inventory_missing_setup_has_actionable_error(self):
        for env in ({}, {'MODE':'video'}, {'MODE':'video','DATA_DIR':'unused','RUN_DIR':'/not-a-real-run-dir'}):
            with self.subTest(env=env), self.assertRaisesRegex(RuntimeError, 'Cấu hình'):
                exec(compile(self.inventory_source(), 'inventory', 'exec'), env.copy())

    def test_notebook_compiles(self):
        nb = json.loads((HERE / 'kaggle_train_rf_v3.ipynb').read_text(encoding='utf-8'))
        self.assertEqual(nb['nbformat'], 4)
        for i, cell in enumerate(nb['cells']):
            if cell['cell_type'] != 'code':
                continue
            self.assertIsNone(cell['execution_count'])
            self.assertEqual(cell['outputs'], [])
            src = ''.join(cell['source'])
            if src.startswith('%%writefile'):
                src = src.split('\n', 1)[1]
            compile(src, f'cell_{i}', 'exec')

    def test_embedded_scripts_and_preserved_features(self):
        nb = json.loads((HERE / 'kaggle_train_rf_v3.ipynb').read_text(encoding='utf-8'))
        sources = [''.join(c['source']) for c in nb['cells'] if c['cell_type'] == 'code']
        for name in ('common.py', 'train_rf.py'):
            cell = next(s for s in sources if s.startswith(f'%%writefile /kaggle/working/{name}\n'))
            self.assertEqual(cell.split('\n', 1)[1].replace('\r\n', '\n'),
                             (HERE / name).read_text(encoding='utf-8'))
        old = json.loads((HERE.parent / 'notebook_v3_1cam90_kaggle.ipynb').read_text(encoding='utf-8'))
        self.assertIn(''.join(old['cells'][6]['source']), sources)
        code = '\n'.join(sources)
        self.assertNotIn('torch.save', code)
        self.assertNotIn('torch.onnx.export', code)
        self.assertNotIn('urllib.request.urlretrieve', code)
        self.assertIn('np.savez_compressed(DATASET_PATH,', code)

    def test_reference_hashes(self):
        import hashlib
        nb = json.loads((HERE / 'kaggle_train_rf_v3.ipynb').read_text(encoding='utf-8'))
        src = next(''.join(c['source']) for c in nb['cells'] if 'REFERENCE_HASHES = ' in ''.join(c['source']))
        tree = ast.parse(src)
        hashes = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == 'REFERENCE_HASHES' for t in n.targets))
        for name, expected in hashes.items():
            self.assertEqual(hashlib.sha256((HERE.parents[1] / 'posture_model' / name).read_bytes()).hexdigest(), expected)

    def test_synthetic_rf_roundtrip_and_rejection(self):
        try:
            import numpy as np
            from common import FEATURES, check_reference, load_dataset, win_stats
            from train_rf import train
        except ModuleNotFoundError as exc:
            self.skipTest(f'Optional RF smoke dependency unavailable: {exc.name}')
        rng = np.random.default_rng(1)
        x = rng.random((24,20,6), dtype=np.float32)
        y = np.tile([0,1], 12)
        g = np.repeat(['P01','P02','P03'], 8)
        cfg = dict(features=FEATURES, window=20, angle_scale=30, n_train_windows=24,
                   bad_ratio=0.5, loso_transformer={p:{'n':8} for p in np.unique(g)})
        probe = np.arange(120, dtype=np.float32).reshape(1,20,6)
        np.testing.assert_array_equal(win_stats(probe)[0,:6], probe.mean(1)[0])
        np.testing.assert_array_equal(win_stats(probe)[0,6:12], probe.std(1)[0])
        np.testing.assert_array_equal(win_stats(probe)[0,12:18], probe.min(1)[0])
        np.testing.assert_array_equal(win_stats(probe)[0,18:], probe.max(1)[0])
        with self.assertRaises(ValueError):
            check_reference(x[:-1],y[:-1],g[:-1],cfg)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            np.savez(p/'data.npz', X=x, Y=y, G=g)
            (p/'config.json').write_text(json.dumps(cfg), encoding='utf-8')
            meta = train(p/'data.npz',p/'config.json',p/'rf',loso=True,jobs=1)
            self.assertEqual(meta['n'],24)
            self.assertEqual(set(meta['loso']),{'P01','P02','P03'})
            with self.assertRaises(FileExistsError):
                train(p/'data.npz',p/'config.json',p/'rf',jobs=1)
            np.savez(p/'bad.npz', X=x, Y=np.zeros(24), G=g)
            with self.assertRaises(ValueError):
                load_dataset(p/'bad.npz')

    def test_dataset_contract_without_rf_dependencies(self):
        import numpy as np
        from common import FEATURES, check_reference, load_dataset, win_stats
        x = np.zeros((6,20,6), dtype=np.float32)
        y = np.array([0,1,0,1,0,1])
        g = np.array(['P01','P01','P02','P02','P03','P03'])
        cfg = dict(features=FEATURES, window=20, angle_scale=30, n_train_windows=6,
                   bad_ratio=0.5, loso_transformer={p:{'n':2} for p in np.unique(g)})
        self.assertEqual(check_reference(x,y,g,cfg), {'P01':2,'P02':2,'P03':2})
        with self.assertRaises(ValueError):
            check_reference(x,y,g,{**cfg,'bad_ratio':0.7})
        with self.assertRaises(ValueError):
            check_reference(x,y,g,{**cfg,'features':list(reversed(FEATURES))})
        with self.assertRaises(ValueError):
            win_stats(np.full((1,20,6),np.nan))
        with self.assertRaises(ValueError):
            win_stats(np.zeros((1,19,6)))
        probe = np.arange(120,dtype=np.float32).reshape(1,20,6)
        expected = np.concatenate([probe.mean(1),probe.std(1),probe.min(1),probe.max(1)],1)
        np.testing.assert_array_equal(win_stats(probe),expected)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'dataset.npz'
            np.savez(p,X=x,Y=y,G=g)
            xx,yy,gg=load_dataset(p)
            np.testing.assert_array_equal(xx,x)
            np.testing.assert_array_equal(yy,y)
            np.testing.assert_array_equal(gg,g)
            x[:,:,3:]=2
            np.savez(p,X=x,Y=y,G=g)
            with self.assertRaises(ValueError):
                load_dataset(p)


if __name__ == '__main__':
    unittest.main()
