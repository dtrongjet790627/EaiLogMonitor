# -*- coding: utf-8 -*-
"""
验证补录结果 - 查询各数据库中的记录数和样本数据
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import ACC_DATABASE, get_dsn

def verify_database(schema_name: str):
    """验证单个数据库的补录结果"""
    import cx_Oracle

    schema_config = ACC_DATABASE['schemas'].get(schema_name)
    if not schema_config:
        print(f"未知的schema: {schema_name}")
        return

    dsn = get_dsn(schema_name)

    try:
        conn = cx_Oracle.connect(
            user=schema_config['user'],
            password=schema_config['password'],
            dsn=dsn,
            encoding='UTF-8'
        )

        cursor = conn.cursor()

        # 查询总记录数
        cursor.execute("SELECT COUNT(*) FROM ACC_ERP_REPORT_SUCCESS")
        total = cursor.fetchone()[0]

        # 查询2026-01-01之后的记录数
        cursor.execute("""
            SELECT COUNT(*) FROM ACC_ERP_REPORT_SUCCESS
            WHERE REPORT_TIME >= TO_DATE('2026-01-01', 'YYYY-MM-DD')
        """)
        jan_count = cursor.fetchone()[0]

        # 查询最近10条记录 (使用ROWNUM兼容旧版Oracle)
        cursor.execute("""
            SELECT * FROM (
                SELECT SCHB_NUMBER, WONO, PACKID, PARTNO, CNT, LINE, REPORT_TIME
                FROM ACC_ERP_REPORT_SUCCESS
                WHERE REPORT_TIME >= TO_DATE('2026-01-01', 'YYYY-MM-DD')
                ORDER BY REPORT_TIME DESC
            ) WHERE ROWNUM <= 10
        """)

        recent_records = cursor.fetchall()

        print(f"\n{'='*60}")
        print(f"数据库: {schema_name}")
        print(f"{'='*60}")
        print(f"总记录数: {total}")
        print(f"2026年1月以来记录数: {jan_count}")
        print(f"\n最近10条记录:")
        print("-" * 100)
        print(f"{'SCHB_NUMBER':<15} {'WONO':<15} {'PACKID':<20} {'PARTNO':<20} {'CNT':<8} {'LINE':<12} {'REPORT_TIME'}")
        print("-" * 100)

        for row in recent_records:
            schb, wono, packid, partno, cnt, line, rtime = row
            print(f"{schb or '':<15} {wono or '':<15} {packid or '':<20} {partno or '':<20} {cnt or 0:<8} {line or '':<12} {rtime}")

        conn.close()

    except Exception as e:
        print(f"连接 {schema_name} 失败: {e}")


def main():
    print("验证EAI日志补录结果")
    print("=" * 60)

    for schema in ['dpeps1', 'smt2', 'dpepp1']:
        verify_database(schema)

    print("\n验证完成")


if __name__ == '__main__':
    main()
