# -*- coding: utf-8 -*-
r"""
net_diag.py —— 判断"到底是哪一层断的"：本机网络 / TLS 中间盒 / Python 环境
用法（PowerShell，在 C:\FYP\data_repo\scripts 下）：
    python net_diag.py
输出可以整段贴回对话。
"""
import socket
import ssl
import sys
import os

HOSTS = [
    ("search.patentsview.org", "PatentsView（本轮卡住的）"),
    ("api.openalex.org", "OpenAlex（papers/shares 依赖）"),
    ("clinicaltrials.gov", "ClinicalTrials"),
    ("api.github.com", "GitHub API"),
    ("www.baidu.com", "对照组-国内"),
    ("www.python.org", "对照组-国外普通站"),
]

print("=" * 78)
print(f"python {sys.version.split()[0]}   位置: {sys.executable}")
print(f"ssl    {ssl.OPENSSL_VERSION}")
try:
    import requests, certifi
    print(f"requests {requests.__version__}   certifi {certifi.__version__}")
    print(f"certifi路径: {certifi.where()}")
except Exception as e:
    print("requests/certifi 导入异常:", e)
print("代理环境变量:", {k: v for k, v in os.environ.items()
                        if k.upper() in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")} or "（无）")
print("=" * 78)
print(f"{'主机':32s} {'DNS':22s} {'TCP443':8s} {'TLS握手':10s}")
print("-" * 78)

ctx = ssl.create_default_context()
for host, label in HOSTS:
    # 1) DNS
    try:
        ip = socket.gethostbyname(host)
        dns = ip
    except Exception as e:
        print(f"{host:32s} {'FAIL ' + type(e).__name__:22s} {'-':8s} {'-':10s}")
        continue
    # 2) TCP
    try:
        s = socket.create_connection((host, 443), timeout=8)
        tcp = "OK"
    except Exception as e:
        print(f"{host:32s} {dns:22s} {'FAIL':8s} {type(e).__name__:10s}")
        continue
    # 3) TLS
    try:
        w = ctx.wrap_socket(s, server_hostname=host)
        tls = f"OK {w.version()}"
        w.close()
    except Exception as e:
        tls = f"FAIL {type(e).__name__}"
        try:
            s.close()
        except Exception:
            pass
    print(f"{host:32s} {dns:22s} {tcp:8s} {tls:10s}")

print("-" * 78)
print("\n解读：")
print("  · DNS 解析出的 IP 明显异常（如 0.0.0.0 / 127.0.0.1 / 与其它站相同）→ DNS 污染")
print("  · TCP 通、TLS 握手 FAIL（尤其 SSLEOFError）→ 中间盒按 SNI 掐断，不是你代码的问题")
print("  · 全部 FAIL 包括 baidu → 本机网络/VPN 配置问题")
print("  · 只有部分站 FAIL → 逐站封锁，需要换网络出口")
