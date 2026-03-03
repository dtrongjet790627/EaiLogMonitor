# -*- coding: utf-8 -*-
"""
ACC_ERP_REPORT_SUCCESS 全面排查修复脚本
目标：iplant_smt2/acc@172.17.10.165:1521/orcl.ecdag.com（电控二线工厂库）
日期：2026-03-02
任务：
  第一步：查2026年以来PARTNO和PACK_INFO.PRODTYPE不一致的记录
  第二步：查2026年以来LINE字段为空的记录
  第三步：批量修正PARTNO不一致记录
  第四步：批量填充LINE为空记录
  第五步：验证修复结果
"""

import oracledb
import sys

DB_HOST = "172.17.10.165"
DB_PORT = 1521
DB_SERVICE = "orcl.ecdag.com"
DB_USER = "iplant_smt2"
DB_PASSWORD = "acc"


INSTANT_CLIENT = r"D:\Software_Space\instantclient_23_0"


def connect():
    try:
        oracledb.init_oracle_client(lib_dir=INSTANT_CLIENT)
    except Exception:
        pass  # 已初始化则忽略
    dsn = oracledb.makedsn(DB_HOST, DB_PORT, service_name=DB_SERVICE)
    conn = oracledb.connect(user=DB_USER, password=DB_PASSWORD, dsn=dsn)
    conn.autocommit = False
    return conn


def step1_check_partno(cursor):
    print("=" * 70)
    print("第一步：查2026年以来PARTNO与PACK_INFO.PRODTYPE不一致的记录")
    print("=" * 70)

    sql = """
        SELECT r.id, r.wono, r.packid, r.partno AS rep_partno,
               p.prodtype AS pack_prodtype,
               r.cnt, r.line, r.schb_number,
               TO_CHAR(r.report_time, 'YYYY-MM-DD HH24:MI:SS') AS report_time
        FROM acc_erp_report_success r
        JOIN pack_info p ON r.packid = p.packid
        WHERE r.report_time >= TO_DATE('2026-01-01', 'YYYY-MM-DD')
          AND r.partno != p.prodtype
        ORDER BY r.report_time
    """
    cursor.execute(sql)
    rows = cursor.fetchall()

    if not rows:
        print("  结果：无不一致记录，PARTNO数据正常。")
        return 0

    print(f"  发现 {len(rows)} 条PARTNO不一致记录：")
    print(f"  {'ID':<12} {'WONO':<20} {'PACKID':<20} {'REP_PARTNO':<20} {'PACK_PRODTYPE':<20} {'CNT':<6} {'LINE':<10} {'REPORT_TIME'}")
    print("  " + "-" * 130)
    for row in rows:
        rid, wono, packid, rep_partno, pack_prodtype, cnt, line, schb_number, report_time = row
        print(f"  {str(rid or ''):<12} {str(wono or ''):<20} {str(packid or ''):<20} {str(rep_partno or ''):<20} {str(pack_prodtype or ''):<20} {str(cnt or ''):<6} {str(line or ''):<10} {str(report_time or '')}")

    return len(rows)


def step2_check_line(cursor):
    print()
    print("=" * 70)
    print("第二步：查2026年以来LINE字段为空的记录")
    print("=" * 70)

    sql = """
        SELECT id, wono, packid, partno, cnt, line, schb_number,
               TO_CHAR(report_time, 'YYYY-MM-DD HH24:MI:SS') AS report_time
        FROM acc_erp_report_success
        WHERE report_time >= TO_DATE('2026-01-01', 'YYYY-MM-DD')
          AND (line IS NULL OR TRIM(line) = ' ')
        ORDER BY report_time
    """
    cursor.execute(sql)
    rows = cursor.fetchall()

    if not rows:
        print("  结果：无LINE为空记录，LINE数据正常。")
        return 0

    print(f"  发现 {len(rows)} 条LINE为空记录：")
    print(f"  {'ID':<12} {'WONO':<20} {'PACKID':<20} {'PARTNO':<20} {'CNT':<6} {'LINE':<10} {'REPORT_TIME'}")
    print("  " + "-" * 110)
    for row in rows:
        rid, wono, packid, partno, cnt, line, schb_number, report_time = row
        print(f"  {str(rid or ''):<12} {str(wono or ''):<20} {str(packid or ''):<20} {str(partno or ''):<20} {str(cnt or ''):<6} {str(line or ''):<10} {str(report_time or '')}")

    return len(rows)


def step3_fix_partno(cursor, conn, count):
    print()
    print("=" * 70)
    print("第三步：批量修正PARTNO不一致记录")
    print("=" * 70)

    if count == 0:
        print("  第一步无不一致记录，跳过第三步。")
        return 0

    sql = """
        UPDATE acc_erp_report_success r
        SET r.partno = (
            SELECT p.prodtype FROM pack_info p WHERE p.packid = r.packid
        )
        WHERE r.report_time >= TO_DATE('2026-01-01', 'YYYY-MM-DD')
          AND r.packid IN (
            SELECT r2.packid FROM acc_erp_report_success r2
            JOIN pack_info p2 ON r2.packid = p2.packid
            WHERE r2.report_time >= TO_DATE('2026-01-01', 'YYYY-MM-DD')
              AND r2.partno != p2.prodtype
          )
    """
    cursor.execute(sql)
    affected = cursor.rowcount
    conn.commit()
    print(f"  UPDATE执行完毕，受影响行数：{affected}")
    print("  COMMIT已提交。")
    return affected


def step4_fix_line(cursor, conn, count):
    print()
    print("=" * 70)
    print("第四步：批量填充LINE为空记录")
    print("=" * 70)

    if count == 0:
        print("  第二步无LINE为空记录，跳过第四步。")
        return 0

    sql = """
        UPDATE acc_erp_report_success r
        SET r.line = (
            SELECT p.line FROM pack_info p WHERE p.packid = r.packid
        )
        WHERE report_time >= TO_DATE('2026-01-01', 'YYYY-MM-DD')
          AND (r.line IS NULL OR TRIM(r.line) = ' ')
    """
    cursor.execute(sql)
    affected = cursor.rowcount
    conn.commit()
    print(f"  UPDATE执行完毕，受影响行数：{affected}")
    print("  COMMIT已提交。")
    return affected


def step5_verify(cursor):
    print()
    print("=" * 70)
    print("第五步：验证修复结果")
    print("=" * 70)

    sql_partno = """
        SELECT COUNT(*) AS wrong_partno_count
        FROM acc_erp_report_success r
        JOIN pack_info p ON r.packid = p.packid
        WHERE r.report_time >= TO_DATE('2026-01-01', 'YYYY-MM-DD')
          AND r.partno != p.prodtype
    """
    cursor.execute(sql_partno)
    wrong_partno_count = cursor.fetchone()[0]

    sql_line = """
        SELECT COUNT(*) AS empty_line_count
        FROM acc_erp_report_success
        WHERE report_time >= TO_DATE('2026-01-01', 'YYYY-MM-DD')
          AND (line IS NULL OR TRIM(line) = ' ')
    """
    cursor.execute(sql_line)
    empty_line_count = cursor.fetchone()[0]

    print(f"  验证PARTNO：剩余不一致记录数 = {wrong_partno_count}")
    print(f"  验证LINE：剩余LINE为空记录数   = {empty_line_count}")

    if wrong_partno_count == 0 and empty_line_count == 0:
        print()
        print("  [通过] 全部数据已修复，无残留异常记录。")
    else:
        print()
        print("  [警告] 仍有残留异常记录，请人工复核！")

    return wrong_partno_count, empty_line_count


def main():
    print()
    print("=" * 70)
    print("ACC_ERP_REPORT_SUCCESS 全面排查修复")
    print(f"目标数据库：{DB_USER}@{DB_HOST}:{DB_PORT}/{DB_SERVICE}")
    print("=" * 70)

    try:
        conn = connect()
        print("数据库连接成功。")
        cursor = conn.cursor()
    except Exception as e:
        print(f"数据库连接失败：{e}")
        sys.exit(1)

    try:
        # 第一步
        partno_count = step1_check_partno(cursor)

        # 第二步
        line_count = step2_check_line(cursor)

        # 第三步
        partno_fixed = step3_fix_partno(cursor, conn, partno_count)

        # 第四步
        line_fixed = step4_fix_line(cursor, conn, line_count)

        # 第五步
        remaining_partno, remaining_line = step5_verify(cursor)

        print()
        print("=" * 70)
        print("修复汇总")
        print("=" * 70)
        print(f"  PARTNO不一致：发现 {partno_count} 条，修复 {partno_fixed} 条，剩余 {remaining_partno} 条")
        print(f"  LINE为空：    发现 {line_count} 条，修复 {line_fixed} 条，剩余 {remaining_line} 条")
        print("=" * 70)

    except Exception as e:
        print(f"\n执行出错，执行ROLLBACK：{e}")
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()
        print("\n数据库连接已关闭。")


if __name__ == "__main__":
    main()
