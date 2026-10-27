"""Run all offline tests, including unchanged review acceptance requirements.
Exit nonzero for any failure; no provider requests or real dispatch/payment.
"""
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
suite=unittest.defaultTestLoader.discover(str(ROOT/'human_board'),pattern='test_*.py')
spec=importlib.util.spec_from_file_location('review_requirements',ROOT/'evidence/verify_review_requirements.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(module.ReviewRequirements))
result=unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() and result.testsRun>0 else 1)
