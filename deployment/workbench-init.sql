-- Local synthetic environment only. Hosted roles use managed secrets.
CREATE ROLE workbench_runtime LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD 'workbench-local-runtime';
