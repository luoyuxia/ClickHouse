-- { echo }
select * from remote('127.{1,2}', system, one, dummy)  where 0 settings optimize_skip_unused_shards=1, force_optimize_skip_unused_shards=1;
select count() from remote('127.{1,2}', system, one, dummy)  where 0 settings optimize_skip_unused_shards=1, force_optimize_skip_unused_shards=1;
