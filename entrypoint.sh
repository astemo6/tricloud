#!/bin/sh
# 以 root 修正挂载目录权限，再降权为 tricloud 运行
set -e
mkdir -p /data
chown -R 10001:10001 /data
chmod 700 /data
exec setpriv --reuid=10001 --regid=10001 --init-groups "$@"
