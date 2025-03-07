import logging
import pytest
from multiprocessing.dummy import Pool

from helpers.cluster import ClickHouseCluster

cluster = ClickHouseCluster(__file__)
node1 = cluster.add_instance('node1', with_postgres=True)
node2 = cluster.add_instance('node2', with_postgres_cluster=True)


@pytest.fixture(scope="module")
def started_cluster():
    try:
        cluster.start()
        yield cluster

    finally:
        cluster.shutdown()


def test_postgres_select_insert(started_cluster):
    cursor = started_cluster.postgres_conn.cursor()
    table_name = 'test_many'
    table = f'''postgresql('{started_cluster.postgres_ip}:{started_cluster.postgres_port}', 'postgres', '{table_name}', 'postgres', 'mysecretpassword')'''
    cursor.execute(f'DROP TABLE IF EXISTS {table_name}')
    cursor.execute(f'CREATE TABLE {table_name} (a integer, b text, c integer)')

    result = node1.query(f'''
        INSERT INTO TABLE FUNCTION {table}
        SELECT number, concat('name_', toString(number)), 3 from numbers(10000)''')
    check1 = f"SELECT count() FROM {table}"
    check2 = f"SELECT Sum(c) FROM {table}"
    check3 = f"SELECT count(c) FROM {table} WHERE a % 2 == 0"
    check4 = f"SELECT count() FROM {table} WHERE b LIKE concat('name_', toString(1))"
    assert (node1.query(check1)).rstrip() == '10000'
    assert (node1.query(check2)).rstrip() == '30000'
    assert (node1.query(check3)).rstrip() == '5000'
    assert (node1.query(check4)).rstrip() == '1'

    # Triggers issue https://github.com/ClickHouse/ClickHouse/issues/26088
    # for i in range(1, 1000):
    #     assert (node1.query(check1)).rstrip() == '10000', f"Failed on {i}"

    cursor.execute(f'DROP TABLE {table_name} ')


def test_postgres_conversions(started_cluster):
    cursor = started_cluster.postgres_conn.cursor()
    cursor.execute(f'DROP TABLE IF EXISTS test_types')
    cursor.execute(f'DROP TABLE IF EXISTS test_array_dimensions')

    cursor.execute(
        '''CREATE TABLE test_types (
        a smallint, b integer, c bigint, d real, e double precision, f serial, g bigserial,
        h timestamp, i date, j decimal(5, 3), k numeric, l boolean)''')
    node1.query('''
        INSERT INTO TABLE FUNCTION postgresql('postgres1:5432', 'postgres', 'test_types', 'postgres', 'mysecretpassword') VALUES
        (-32768, -2147483648, -9223372036854775808, 1.12345, 1.1234567890, 2147483647, 9223372036854775807, '2000-05-12 12:12:12.012345', '2000-05-12', 22.222, 22.222, 1)''')
    result = node1.query('''
        SELECT a, b, c, d, e, f, g, h, i, j, toDecimal128(k, 3), l FROM postgresql('postgres1:5432', 'postgres', 'test_types', 'postgres', 'mysecretpassword')''')
    assert(result == '-32768\t-2147483648\t-9223372036854775808\t1.12345\t1.123456789\t2147483647\t9223372036854775807\t2000-05-12 12:12:12.012345\t2000-05-12\t22.222\t22.222\t1\n')

    cursor.execute("INSERT INTO test_types (l) VALUES (TRUE), (true), ('yes'), ('y'), ('1');")
    cursor.execute("INSERT INTO test_types (l) VALUES (FALSE), (false), ('no'), ('off'), ('0');")
    expected = "1\n1\n1\n1\n1\n1\n0\n0\n0\n0\n0\n"
    result = node1.query('''SELECT l FROM postgresql('postgres1:5432', 'postgres', 'test_types', 'postgres', 'mysecretpassword')''')
    assert(result == expected)

    cursor.execute(
        '''CREATE TABLE IF NOT EXISTS test_array_dimensions
           (
                a Date[] NOT NULL,                          -- Date
                b Timestamp[] NOT NULL,                     -- DateTime64(6)
                c real[][] NOT NULL,                        -- Float32
                d double precision[][] NOT NULL,            -- Float64
                e decimal(5, 5)[][][] NOT NULL,             -- Decimal32
                f integer[][][] NOT NULL,                   -- Int32
                g Text[][][][][] NOT NULL,                  -- String
                h Integer[][][],                            -- Nullable(Int32)
                i Char(2)[][][][],                          -- Nullable(String)
                k Char(2)[]                                 -- Nullable(String)
           )''')

    result = node1.query('''
        DESCRIBE TABLE postgresql('postgres1:5432', 'postgres', 'test_array_dimensions', 'postgres', 'mysecretpassword')''')
    expected = ('a\tArray(Date)\t\t\t\t\t\n' +
               'b\tArray(DateTime64(6))\t\t\t\t\t\n' +
               'c\tArray(Array(Float32))\t\t\t\t\t\n' +
               'd\tArray(Array(Float64))\t\t\t\t\t\n' +
               'e\tArray(Array(Array(Decimal(5, 5))))\t\t\t\t\t\n' +
               'f\tArray(Array(Array(Int32)))\t\t\t\t\t\n' +
               'g\tArray(Array(Array(Array(Array(String)))))\t\t\t\t\t\n' +
               'h\tArray(Array(Array(Nullable(Int32))))\t\t\t\t\t\n' +
               'i\tArray(Array(Array(Array(Nullable(String)))))\t\t\t\t\t\n' +
               'k\tArray(Nullable(String))'
               )
    assert(result.rstrip() == expected)

    node1.query("INSERT INTO TABLE FUNCTION postgresql('postgres1:5432', 'postgres', 'test_array_dimensions', 'postgres', 'mysecretpassword') "
        "VALUES ("
        "['2000-05-12', '2000-05-12'], "
        "['2000-05-12 12:12:12.012345', '2000-05-12 12:12:12.012345'], "
        "[[1.12345], [1.12345], [1.12345]], "
        "[[1.1234567891], [1.1234567891], [1.1234567891]], "
        "[[[0.11111, 0.11111]], [[0.22222, 0.22222]], [[0.33333, 0.33333]]], "
        "[[[1, 1], [1, 1]], [[3, 3], [3, 3]], [[4, 4], [5, 5]]], "
        "[[[[['winx', 'winx', 'winx']]]]], "
        "[[[1, NULL], [NULL, 1]], [[NULL, NULL], [NULL, NULL]], [[4, 4], [5, 5]]], "
        "[[[[NULL]]]], "
        "[]"
        ")")

    result = node1.query('''
        SELECT * FROM postgresql('postgres1:5432', 'postgres', 'test_array_dimensions', 'postgres', 'mysecretpassword')''')
    expected = (
        "['2000-05-12','2000-05-12']\t" +
        "['2000-05-12 12:12:12.012345','2000-05-12 12:12:12.012345']\t" +
        "[[1.12345],[1.12345],[1.12345]]\t" +
        "[[1.1234567891],[1.1234567891],[1.1234567891]]\t" +
        "[[[0.11111,0.11111]],[[0.22222,0.22222]],[[0.33333,0.33333]]]\t"
        "[[[1,1],[1,1]],[[3,3],[3,3]],[[4,4],[5,5]]]\t"
        "[[[[['winx','winx','winx']]]]]\t"
        "[[[1,NULL],[NULL,1]],[[NULL,NULL],[NULL,NULL]],[[4,4],[5,5]]]\t"
        "[[[[NULL]]]]\t"
        "[]\n"
        )
    assert(result == expected)

    cursor.execute(f'DROP TABLE test_types')
    cursor.execute(f'DROP TABLE test_array_dimensions')


def test_non_default_scema(started_cluster):
    node1.query('DROP TABLE IF EXISTS test_pg_table_schema')
    node1.query('DROP TABLE IF EXISTS test_pg_table_schema_with_dots')

    cursor = started_cluster.postgres_conn.cursor()
    cursor.execute('DROP SCHEMA IF EXISTS test_schema CASCADE')
    cursor.execute('DROP SCHEMA IF EXISTS "test.nice.schema" CASCADE')

    cursor.execute('CREATE SCHEMA test_schema')
    cursor.execute('CREATE TABLE test_schema.test_table (a integer)')
    cursor.execute('INSERT INTO test_schema.test_table SELECT i FROM generate_series(0, 99) as t(i)')

    node1.query('''
        CREATE TABLE test_pg_table_schema (a UInt32)
        ENGINE PostgreSQL('postgres1:5432', 'postgres', 'test_table', 'postgres', 'mysecretpassword', 'test_schema');
    ''')

    result = node1.query('SELECT * FROM test_pg_table_schema')
    expected = node1.query('SELECT number FROM numbers(100)')
    assert(result == expected)

    table_function = '''postgresql('postgres1:5432', 'postgres', 'test_table', 'postgres', 'mysecretpassword', 'test_schema')'''
    result = node1.query(f'SELECT * FROM {table_function}')
    assert(result == expected)

    cursor.execute('''CREATE SCHEMA "test.nice.schema"''')
    cursor.execute('''CREATE TABLE "test.nice.schema"."test.nice.table" (a integer)''')
    cursor.execute('INSERT INTO "test.nice.schema"."test.nice.table" SELECT i FROM generate_series(0, 99) as t(i)')

    node1.query('''
        CREATE TABLE test_pg_table_schema_with_dots (a UInt32)
        ENGINE PostgreSQL('postgres1:5432', 'postgres', 'test.nice.table', 'postgres', 'mysecretpassword', 'test.nice.schema');
    ''')
    result = node1.query('SELECT * FROM test_pg_table_schema_with_dots')
    assert(result == expected)

    cursor.execute('INSERT INTO "test_schema"."test_table" SELECT i FROM generate_series(100, 199) as t(i)')
    result = node1.query(f'SELECT * FROM {table_function}')
    expected = node1.query('SELECT number FROM numbers(200)')
    assert(result == expected)

    cursor.execute('DROP SCHEMA test_schema CASCADE')
    cursor.execute('DROP SCHEMA "test.nice.schema" CASCADE')
    node1.query('DROP TABLE test_pg_table_schema')
    node1.query('DROP TABLE test_pg_table_schema_with_dots')


def test_concurrent_queries(started_cluster):
    cursor = started_cluster.postgres_conn.cursor()

    node1.query('''
        CREATE TABLE test_table (key UInt32, value UInt32)
        ENGINE = PostgreSQL('postgres1:5432', 'postgres', 'test_table', 'postgres', 'mysecretpassword')''')

    cursor.execute('CREATE TABLE test_table (key integer, value integer)')

    prev_count =  node1.count_in_log('New connection to postgres1:5432')
    def node_select(_):
        for i in range(20):
            result = node1.query("SELECT * FROM test_table", user='default')
    busy_pool = Pool(20)
    p = busy_pool.map_async(node_select, range(20))
    p.wait()
    count =  node1.count_in_log('New connection to postgres1:5432')
    logging.debug(f'count {count}, prev_count {prev_count}')
    # 16 is default size for connection pool
    assert(int(count) <= int(prev_count) + 16)

    def node_insert(_):
        for i in range(5):
            result = node1.query("INSERT INTO test_table SELECT number, number FROM numbers(1000)", user='default')

    busy_pool = Pool(5)
    p = busy_pool.map_async(node_insert, range(5))
    p.wait()
    result = node1.query("SELECT count() FROM test_table", user='default')
    logging.debug(result)
    assert(int(result) == 5 * 5 * 1000)

    def node_insert_select(_):
        for i in range(5):
            result = node1.query("INSERT INTO test_table SELECT number, number FROM numbers(1000)", user='default')
            result = node1.query("SELECT * FROM test_table LIMIT 100", user='default')

    busy_pool = Pool(5)
    p = busy_pool.map_async(node_insert_select, range(5))
    p.wait()
    result = node1.query("SELECT count() FROM test_table", user='default')
    logging.debug(result)
    assert(int(result) == 5 * 5 * 1000  * 2)

    node1.query('DROP TABLE test_table;')
    cursor.execute('DROP TABLE test_table;')

    count =  node1.count_in_log('New connection to postgres1:5432')
    logging.debug(f'count {count}, prev_count {prev_count}')
    assert(int(count) <= int(prev_count) + 16)


def test_postgres_distributed(started_cluster):
    cursor0 = started_cluster.postgres_conn.cursor()
    cursor1 = started_cluster.postgres2_conn.cursor()
    cursor2 = started_cluster.postgres3_conn.cursor()
    cursor3 = started_cluster.postgres4_conn.cursor()
    cursors = [cursor0, cursor1, cursor2, cursor3]

    for i in range(4):
        cursors[i].execute('DROP TABLE IF EXISTS test_replicas')
        cursors[i].execute('CREATE TABLE test_replicas (id Integer, name Text)')
        cursors[i].execute(f"""INSERT INTO test_replicas select i, 'host{i+1}' from generate_series(0, 99) as t(i);""");

    # test multiple ports parsing
    result = node2.query('''SELECT DISTINCT(name) FROM postgresql(`postgres{1|2|3}:5432`, 'postgres', 'test_replicas', 'postgres', 'mysecretpassword'); ''')
    assert(result == 'host1\n' or result == 'host2\n' or result == 'host3\n')
    result = node2.query('''SELECT DISTINCT(name) FROM postgresql(`postgres2:5431|postgres3:5432`, 'postgres', 'test_replicas', 'postgres', 'mysecretpassword'); ''')
    assert(result == 'host3\n' or result == 'host2\n')

    # Create storage with with 3 replicas
    node2.query('DROP TABLE IF EXISTS test_replicas')
    node2.query('''
        CREATE TABLE test_replicas
        (id UInt32, name String)
        ENGINE = PostgreSQL(`postgres{2|3|4}:5432`, 'postgres', 'test_replicas', 'postgres', 'mysecretpassword'); ''')

    # Check all replicas are traversed
    query = "SELECT name FROM ("
    for i in range (3):
        query += "SELECT name FROM test_replicas UNION DISTINCT "
    query += "SELECT name FROM test_replicas) ORDER BY name"
    result = node2.query(query)
    assert(result == 'host2\nhost3\nhost4\n')

    # Create storage with with two two shards, each has 2 replicas
    node2.query('DROP TABLE IF EXISTS test_shards')

    node2.query('''
        CREATE TABLE test_shards
        (id UInt32, name String, age UInt32, money UInt32)
        ENGINE = ExternalDistributed('PostgreSQL', `postgres{1|2}:5432,postgres{3|4}:5432`, 'postgres', 'test_replicas', 'postgres', 'mysecretpassword'); ''')

    # Check only one replica in each shard is used
    result = node2.query("SELECT DISTINCT(name) FROM test_shards ORDER BY name")
    assert(result == 'host1\nhost3\n')

    # Check all replicas are traversed
    query = "SELECT name FROM ("
    for i in range (3):
        query += "SELECT name FROM test_shards UNION DISTINCT "
    query += "SELECT name FROM test_shards) ORDER BY name"
    result = node2.query(query)
    assert(result == 'host1\nhost2\nhost3\nhost4\n')

    # Disconnect postgres1
    started_cluster.pause_container('postgres1')
    result = node2.query("SELECT DISTINCT(name) FROM test_shards ORDER BY name")
    started_cluster.unpause_container('postgres1')
    assert(result == 'host2\nhost4\n' or result == 'host3\nhost4\n')
    node2.query('DROP TABLE test_shards')
    node2.query('DROP TABLE test_replicas')


def test_datetime_with_timezone(started_cluster):
    cursor = started_cluster.postgres_conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS test_timezone")
    node1.query("DROP TABLE IF EXISTS test_timezone")
    cursor.execute("CREATE TABLE test_timezone (ts timestamp without time zone, ts_z timestamp with time zone)")
    cursor.execute("insert into test_timezone select '2014-04-04 20:00:00', '2014-04-04 20:00:00'::timestamptz at time zone 'America/New_York';")
    cursor.execute("select * from test_timezone")
    result = cursor.fetchall()[0]
    logging.debug(f'{result[0]}, {str(result[1])[:-6]}')
    node1.query("create table test_timezone ( ts DateTime, ts_z DateTime('America/New_York')) ENGINE PostgreSQL('postgres1:5432', 'postgres', 'test_timezone', 'postgres', 'mysecretpassword');")
    assert(node1.query("select ts from test_timezone").strip() == str(result[0]))
    # [:-6] because 2014-04-04 16:00:00+00:00 -> 2014-04-04 16:00:00
    assert(node1.query("select ts_z from test_timezone").strip() == str(result[1])[:-6])
    assert(node1.query("select * from test_timezone") == "2014-04-04 20:00:00\t2014-04-04 16:00:00\n")
    cursor.execute("DROP TABLE test_timezone")
    node1.query("DROP TABLE test_timezone")


def test_postgres_ndim(started_cluster):
    cursor = started_cluster.postgres_conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS arr1, arr2")

    cursor.execute('CREATE TABLE arr1 (a Integer[])')
    cursor.execute("INSERT INTO arr1 SELECT '{{1}, {2}}'")

    # The point is in creating a table via 'as select *', in postgres att_ndim will not be correct in this case.
    cursor.execute('CREATE TABLE arr2 AS SELECT * FROM arr1')
    cursor.execute("SELECT attndims AS dims FROM pg_attribute WHERE attrelid = 'arr2'::regclass; ")
    result = cursor.fetchall()[0]
    assert(int(result[0]) == 0)

    result = node1.query('''SELECT toTypeName(a) FROM postgresql('postgres1:5432', 'postgres', 'arr2', 'postgres', 'mysecretpassword')''')
    assert(result.strip() == "Array(Array(Nullable(Int32)))")
    cursor.execute("DROP TABLE arr1, arr2")


def test_postgres_on_conflict(started_cluster):
    cursor = started_cluster.postgres_conn.cursor()
    table = 'test_conflict'
    cursor.execute(f'DROP TABLE IF EXISTS {table}')
    cursor.execute(f'CREATE TABLE {table} (a integer PRIMARY KEY, b text, c integer)')

    node1.query('''
        CREATE TABLE test_conflict (a UInt32, b String, c Int32)
        ENGINE PostgreSQL('postgres1:5432', 'postgres', 'test_conflict', 'postgres', 'mysecretpassword', '', 'ON CONFLICT DO NOTHING');
    ''')
    node1.query(f''' INSERT INTO {table} SELECT number, concat('name_', toString(number)), 3 from numbers(100)''')
    node1.query(f''' INSERT INTO {table} SELECT number, concat('name_', toString(number)), 4 from numbers(100)''')

    check1 = f"SELECT count() FROM {table}"
    assert (node1.query(check1)).rstrip() == '100'

    table_func = f'''postgresql('{started_cluster.postgres_ip}:{started_cluster.postgres_port}', 'postgres', '{table}', 'postgres', 'mysecretpassword', '', 'ON CONFLICT DO NOTHING')'''
    node1.query(f'''INSERT INTO TABLE FUNCTION {table_func} SELECT number, concat('name_', toString(number)), 3 from numbers(100)''')
    node1.query(f'''INSERT INTO TABLE FUNCTION {table_func} SELECT number, concat('name_', toString(number)), 3 from numbers(100)''')

    check1 = f"SELECT count() FROM {table}"
    assert (node1.query(check1)).rstrip() == '100'

    cursor.execute(f'DROP TABLE {table} ')


if __name__ == '__main__':
    cluster.start()
    input("Cluster created, press any key to destroy...")
    cluster.shutdown()
