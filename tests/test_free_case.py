"""Functional checks use an isolated copy, never the project's user database."""
import gc
import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile
import unittest


class FreeCaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        source = Path(__file__).resolve().parents[1]
        shutil.copy2(source / 'app.py', cls.root / 'app.py')
        shutil.copytree(source / 'templates', cls.root / 'templates')
        shutil.copytree(source / 'static' / 'characters', cls.root / 'static' / 'characters')
        shutil.copytree(source / 'static' / 'cases', cls.root / 'static' / 'cases')
        spec = importlib.util.spec_from_file_location('isolated_meme_case', cls.root / 'app.py')
        cls.module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.module
        spec.loader.exec_module(cls.module)
        cls.module.app.config['TESTING'] = True

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop('isolated_meme_case', None)
        gc.collect()
        cls.temp.cleanup()

    def setUp(self):
        self.module.GAME_DB.clear()
        with self.module.db_connection() as conn:
            conn.execute('DELETE FROM users')
        self.client = self.module.app.test_client()
        response = self.client.post('/api/register', json={'username': 'tester', 'password': 'test-pass'})
        self.assertEqual(response.status_code, 201)

    def test_unlimited_free_opening_at_zero_balance(self):
        new_ids = {item['id'] for item in self.module.ITEM_POOL if item['value'] < 10}
        self.assertEqual(len(new_ids), 11)
        instances = set()
        for count in range(1, 26):
            response = self.client.post('/api/open_case/free')
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data['coins'], 0)
            self.assertEqual(data['cases_opened'], count)
            self.assertEqual(len(data['inventory']), count)
            self.assertIn(data['won']['id'], new_ids)
            instances.add(data['won']['instance_id'])
        self.assertEqual(len(instances), 25)

    def test_new_drop_can_be_sold_and_upgraded(self):
        won = self.client.post('/api/open_case/free').get_json()['won']
        sale = self.client.post('/api/sell', json={'instance_id': won['instance_id']})
        self.assertEqual(sale.status_code, 200)
        self.assertEqual(sale.get_json()['coins'], won['value'])
        won = self.client.post('/api/open_case/free').get_json()['won']
        target = next(item for item in self.module.ITEM_POOL if item['value'] == 10)
        upgrade = self.client.post('/api/upgrade', json={'instance_id': won['instance_id'], 'target_id': target['id']})
        self.assertEqual(upgrade.status_code, 200)
        self.assertGreater(upgrade.get_json()['chance'], 0)

    def test_paid_cases_keep_their_balance_and_drop_rules(self):
        response = self.client.post('/api/open_case/bomzh')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['error'], 'insufficient_funds')
        with self.client.session_transaction() as session:
            user_id = session['user_id']
        self.module.GAME_DB[str(user_id)]['coins'] = 70
        data = self.client.post('/api/open_case/bomzh').get_json()
        self.assertEqual(data['coins'], 0)
        self.assertGreaterEqual(data['won']['value'], 10)
        self.assertLessEqual(data['won']['value'], 95)

    def test_catalog_and_images_are_served(self):
        pool = self.module.ITEM_POOL
        self.assertEqual(len(pool), 54)
        self.assertEqual(len({item['id'] for item in pool}), 54)
        self.assertEqual(self.module.CASES[0]['id'], 'free')
        for item in pool:
            with self.client.get(item['image']) as response:
                self.assertEqual(response.status_code, 200)
        for case in self.module.CASES:
            with self.client.get(case['image']) as response:
                self.assertEqual(response.status_code, 200)
        html = self.client.get('/').get_data(as_text=True)
        self.assertIn('Открыть бесплатно', html)
        self.assertIn('Бесплатные', html)

    def test_free_case_requires_login(self):
        self.client.post('/api/logout')
        self.assertEqual(self.client.post('/api/open_case/free').status_code, 401)


if __name__ == '__main__':
    unittest.main()
