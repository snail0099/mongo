import wttest, threading, wiredtiger
from helper import simulate_crash_restart

def timestamp_str(t):
    return '%x' % t

# test_hs24.py
# Test that out of order timestamp fix racing with checkpointing the history store doesn't create inconsistent checkpoint.
class test_hs24(wttest.WiredTigerTestCase):
    conn_config = 'cache_size=50MB,timing_stress_for_test=(history_store_checkpoint_delay)'
    session_config = 'isolation=snapshot'
    uri = 'table:test_hs24'

    value1 = 'a' * 500
    value2 = 'b' * 500
    value3 = 'c' * 500
    value4 = 'd' * 500
    def test_zero_ts(self):
        self.session.create(self.uri, 'key_format=S,value_format=S')
        self.conn.set_timestamp('oldest_timestamp=' + timestamp_str(1))
        cursor = self.session.open_cursor(self.uri)
        for i in range(0, 2000):
            self.session.begin_transaction()
            cursor[str(i)] = self.value1
            self.session.commit_transaction('commit_timestamp=' + timestamp_str(4))
            self.session.begin_transaction()
            cursor[str(i)] = self.value2
            self.session.commit_transaction('commit_timestamp=' + timestamp_str(5))
        cursor.close()
        self.conn.set_timestamp('stable_timestamp=' + timestamp_str(5))
        thread = threading.Thread(target=self.zero_ts_deletes)
        thread.start()
        self.session.checkpoint()
        thread.join()
        simulate_crash_restart(self, '.', "RESTART")
        cursor = self.session.open_cursor(self.uri)
        session2 = self.conn.open_session(None)
        cursor2 = session2.open_cursor(self.uri)
        self.session.begin_transaction('read_timestamp=' + timestamp_str(5))
        session2.begin_transaction('read_timestamp=' + timestamp_str(4))
        # Check the data store and the history store content is consistent.
        # If we have a value in the data store, we should see the older
        # version in the history store as well.
        for i in range(0, 2000):
            cursor.set_key(str(i))
            cursor2.set_key(str(i))
            ret = cursor.search()
            ret2 = cursor2.search()
            if ret == 0:
                self.assertEquals(cursor.get_value(), self.value2)
                self.assertEquals(cursor2.get_value(), self.value1)
            else:
                self.assertEquals(ret, wiredtiger.WT_NOTFOUND)
                self.assertEquals(ret2, wiredtiger.WT_NOTFOUND)
        session2.rollback_transaction()
        self.session.rollback_transaction()

    def zero_ts_deletes(self):
        session = self.setUpSessionOpen(self.conn)
        cursor = session.open_cursor(self.uri)
        for i in range(1, 2000):
            session.begin_transaction()
            cursor.set_key(str(i))
            cursor.remove()
            session.commit_transaction()
        cursor.close()
        session.close()

    def test_zero_commit(self):
        self.session.create(self.uri, 'key_format=S,value_format=S')
        self.conn.set_timestamp('oldest_timestamp=' + timestamp_str(1))
        cursor = self.session.open_cursor(self.uri)
        for i in range(0, 2000):
            self.session.begin_transaction()
            cursor[str(i)] = self.value1
            self.session.commit_transaction('commit_timestamp=' + timestamp_str(4))
            self.session.begin_transaction()
            cursor[str(i)] = self.value2
            self.session.commit_transaction('commit_timestamp=' + timestamp_str(5))
        cursor.close()
        self.conn.set_timestamp('stable_timestamp=' + timestamp_str(4))
        thread = threading.Thread(target=self.zero_ts_commits)
        thread.start()
        self.session.checkpoint()
        thread.join()
        simulate_crash_restart(self, '.', "RESTART")
        cursor = self.session.open_cursor(self.uri)
        self.session.begin_transaction('read_timestamp=' + timestamp_str(4))
        # Check we can only see the version committed by the zero timestamp
        # commit thread before the checkpoint starts or value1.
        for i in range(0, 2000):
            value = cursor[str(i)]
            if value != self.value3:
                self.assertEquals(value, self.value1)
        self.session.rollback_transaction()

    def zero_ts_commits(self):
        session = self.setUpSessionOpen(self.conn)
        cursor = session.open_cursor(self.uri)
        for i in range(1, 2000):
            session.begin_transaction()
            cursor[str(i)] = self.value3
            session.commit_transaction()
        cursor.close()
        session.close()

    def test_out_of_order_ts(self):
        self.session.create(self.uri, 'key_format=S,value_format=S')
        self.conn.set_timestamp('oldest_timestamp=' + timestamp_str(1))
        cursor = self.session.open_cursor(self.uri)
        for i in range(0, 2000):
            self.session.begin_transaction()
            cursor[str(i)] = self.value1
            self.session.commit_transaction('commit_timestamp=' + timestamp_str(4))
            self.session.begin_transaction()
            cursor[str(i)] = self.value2
            self.session.commit_transaction('commit_timestamp=' + timestamp_str(5))
        self.conn.set_timestamp('stable_timestamp=' + timestamp_str(4))
        for i in range(0, 2000):
            self.session.begin_transaction()
            cursor[str(i)] = self.value3
            self.session.commit_transaction('commit_timestamp=' + timestamp_str(6))
        cursor.close()
        thread = threading.Thread(target=self.out_of_order_ts_commits)
        thread.start()
        self.session.checkpoint()
        thread.join()
        simulate_crash_restart(self, '.', "RESTART")
        cursor = self.session.open_cursor(self.uri)
        self.session.begin_transaction('read_timestamp=' + timestamp_str(4))
        # Check we can only see the version at timestamp 4, it's either
        # committed by the out of order timestamp commit thread before the
        # checkpoint starts or value1.
        for i in range(0, 2000):
            value = cursor[str(i)]
            if value != self.value4:
                self.assertEquals(value, self.value1)
        self.session.rollback_transaction()

    def out_of_order_ts_commits(self):
        session = self.setUpSessionOpen(self.conn)
        cursor = session.open_cursor(self.uri)
        for i in range(0, 2000):
            session.begin_transaction()
            cursor[str(i)] = self.value4
            session.commit_transaction('commit_timestamp=' + timestamp_str(4))
        cursor.close()
        session.close()
