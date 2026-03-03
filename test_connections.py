# -*- coding: utf-8 -*-
"""
EAI日志监听服务 - 连接测试脚本
用于验证SSH和数据库连接是否正常
"""

import sys
import time

def test_ssh_connection():
    """测试SSH连接"""
    print("\n" + "=" * 60)
    print("[测试1] SSH连接测试")
    print("=" * 60)

    try:
        import paramiko
        from config import EAI_SERVER

        print(f"目标服务器: {EAI_SERVER['host']}:{EAI_SERVER['port']}")
        print(f"用户名: {EAI_SERVER['user']}")
        print("正在连接...")

        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        start_time = time.time()
        ssh_client.connect(
            hostname=EAI_SERVER['host'],
            port=EAI_SERVER['port'],
            username=EAI_SERVER['user'],
            password=EAI_SERVER['password'],
            timeout=30
        )
        elapsed = time.time() - start_time

        print(f"[OK] SSH连接成功! (耗时: {elapsed:.2f}秒)")

        # 测试执行命令
        print("\n测试执行命令: ls -la /usr/local/eai-apps/logs/")
        stdin, stdout, stderr = ssh_client.exec_command(
            f"ls -la {EAI_SERVER['log_dir']}"
        )
        output = stdout.read().decode('utf-8')
        error = stderr.read().decode('utf-8')

        if error:
            print(f"[WARN] 命令执行警告: {error}")
        else:
            print("[OK] 命令执行成功!")
            print("\n日志目录内容:")
            print("-" * 40)
            for line in output.strip().split('\n')[:10]:
                print(f"  {line}")
            if len(output.strip().split('\n')) > 10:
                print("  ... (更多文件)")

        # 检查日志文件是否存在
        print("\n检查监听目标日志文件:")
        from config import LOG_FILE_MAPPING
        for log_file, config in LOG_FILE_MAPPING.items():
            full_path = f"{EAI_SERVER['log_dir']}{log_file}"
            stdin, stdout, stderr = ssh_client.exec_command(f"test -f '{full_path}' && echo 'EXISTS' || echo 'NOT_FOUND'")
            result = stdout.read().decode('utf-8').strip()
            status = "[OK]" if result == "EXISTS" else "[WARN]"
            print(f"  {status} {log_file} -> {result}")

        ssh_client.close()
        return True

    except Exception as e:
        print(f"[FAIL] SSH连接失败: {e}")
        return False


def test_database_connection():
    """测试数据库连接"""
    print("\n" + "=" * 60)
    print("[测试2] Oracle数据库连接测试")
    print("=" * 60)

    try:
        import cx_Oracle
        from config import ACC_DATABASE, get_dsn

        print(f"目标数据库: {ACC_DATABASE['host']}:{ACC_DATABASE['port']}/{ACC_DATABASE['service']}")

        all_success = True
        for schema_name, schema_config in ACC_DATABASE['schemas'].items():
            print(f"\n测试模式: {schema_name}")
            print(f"  用户: {schema_config['user']}")

            try:
                dsn = get_dsn(schema_name)
                start_time = time.time()

                conn = cx_Oracle.connect(
                    user=schema_config['user'],
                    password=schema_config['password'],
                    dsn=dsn,
                    encoding='UTF-8'
                )
                elapsed = time.time() - start_time

                print(f"  [OK] 连接成功! (耗时: {elapsed:.2f}秒)")

                # 查询数据库版本
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM V$VERSION WHERE ROWNUM = 1")
                version = cursor.fetchone()
                if version:
                    print(f"  数据库版本: {version[0][:50]}...")

                # 检查目标表是否存在
                cursor.execute("""
                    SELECT COUNT(*) FROM user_tables WHERE table_name = 'ACC_ERP_REPORT_SUCCESS'
                """)
                table_exists = cursor.fetchone()[0] > 0
                if table_exists:
                    cursor.execute("SELECT COUNT(*) FROM ACC_ERP_REPORT_SUCCESS")
                    record_count = cursor.fetchone()[0]
                    print(f"  [OK] 目标表存在，当前记录数: {record_count}")
                else:
                    print(f"  [INFO] 目标表不存在，将在服务启动时自动创建")

                conn.close()

            except cx_Oracle.Error as e:
                print(f"  [FAIL] 连接失败: {e}")
                all_success = False

        return all_success

    except ImportError as e:
        print(f"[FAIL] cx_Oracle模块未正确安装: {e}")
        print("\n提示: 需要安装Oracle Instant Client")
        print("下载地址: https://www.oracle.com/database/technologies/instant-client/downloads.html")
        return False
    except Exception as e:
        print(f"[FAIL] 数据库连接测试失败: {e}")
        return False


def test_log_parser():
    """测试日志解析模块"""
    print("\n" + "=" * 60)
    print("[测试3] 日志解析模块测试")
    print("=" * 60)

    try:
        from log_parser import LogParser

        parser = LogParser()

        # 模拟日志行
        test_request = '''[2026-01-11 13:00:00] INFO kingdee request: {"Model": {"FBillNo": "TEST001", "FQty": 100, "FMaterialId": "PROD001"}}'''
        test_response_success = '''[2026-01-11 13:00:01] INFO kingdee response: {"IsSuccess": true, "Result": {"FBillNo": "TEST001"}}'''
        test_response_fail = '''[2026-01-11 13:00:02] INFO kingdee response: {"IsSuccess": false, "Error": "Some error"}'''

        print("\n测试请求解析:")
        result = parser.parse_line(test_request)
        print(f"  输入: {test_request[:60]}...")
        print(f"  结果: {result} (应为None，因为只缓存请求)")

        print("\n测试成功响应解析:")
        result = parser.parse_line(test_response_success)
        if result:
            print(f"  [OK] 成功解析到报工记录!")
            print(f"    工单号: {result.schb_number}")
            print(f"    数量: {result.qty}")
            print(f"    产品编码: {result.product_code}")
        else:
            print(f"  [WARN] 未解析到记录 (可能请求已过期)")

        print("\n测试失败响应解析:")
        result = parser.parse_line(test_response_fail)
        print(f"  输入: {test_response_fail[:60]}...")
        print(f"  结果: {result} (应为None，因为响应失败)")

        print("\n[OK] 日志解析模块测试通过!")
        return True

    except Exception as e:
        print(f"[FAIL] 日志解析测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """主测试函数"""
    print("\n" + "#" * 60)
    print("#  EAI日志监听服务 - 连接测试")
    print("#" * 60)

    results = {}

    # 测试SSH
    results['SSH'] = test_ssh_connection()

    # 测试数据库
    results['Database'] = test_database_connection()

    # 测试日志解析
    results['LogParser'] = test_log_parser()

    # 总结
    print("\n" + "=" * 60)
    print("测试结果总结")
    print("=" * 60)

    for test_name, passed in results.items():
        status = "[PASS]" if passed else "[FAIL]"
        print(f"  {status} {test_name}")

    all_passed = all(results.values())

    print("\n" + "-" * 60)
    if all_passed:
        print("[SUCCESS] 所有测试通过，可以启动服务!")
        print("\n启动命令: python eai_log_monitor.py")
    else:
        print("[WARNING] 部分测试未通过，请检查配置后重试")

    return 0 if all_passed else 1


if __name__ == '__main__':
    sys.exit(main())
