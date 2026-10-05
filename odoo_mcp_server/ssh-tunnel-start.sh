#!/bin/zsh
# 启动本机 -> <REGION>轻量服务器(<SERVER_IP>) 的 SSH 反向隧道：
#   云端 127.0.0.1:7069 -> 本机 127.0.0.1:8069 (Odoo)
# 云端 MCP Server (odoo-mcp.service) 通过 ODOO_URL=http://127.0.0.1:7069 访问本机 Odoo。
# 密钥: ~/.ssh/odoo_tunnel_ed25519 (云端 authorized_keys 中带 restrict,port-forwarding 限制)
# 用法: ./ssh-tunnel-start.sh   （停止: pkill -f 'ssh -N -R'）
# 注意: 公司办公网已放行 22 端口；需先启动 Rancher Desktop 与本机 Odoo。
KEY="$HOME/.ssh/odoo_tunnel_ed25519"
if [ ! -f "$KEY" ]; then
  echo "隧道密钥不存在: $KEY"
  exit 1
fi
pkill -f 'ssh -N -R 7069' 2>/dev/null
nohup ssh -N -R 7069:127.0.0.1:8069 -i "$KEY" \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -o ExitOnForwardFailure=yes -o BatchMode=yes \
  root@<SERVER_IP> > /tmp/ssh-tunnel.log 2>&1 &
sleep 3
if pgrep -f 'ssh -N -R 7069' > /dev/null; then
  echo "SSH 反向隧道已启动 (pid=$!), 日志: /tmp/ssh-tunnel.log"
else
  echo "隧道启动失败:"; cat /tmp/ssh-tunnel.log
  exit 1
fi
