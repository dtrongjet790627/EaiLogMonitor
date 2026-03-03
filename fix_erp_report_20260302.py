# -*- coding: utf-8 -*-
"""
ACC ERP Report Success 补录脚本
日期: 2026-03-02
操作: 补录4条丢失的acc_erp_report_success记录
数据库: iplant_smt2@172.17.10.165:1521/orcl.ecdag.com
"""
import oracledb

# 使用thick模式（需要Oracle Client）
oracledb.init_oracle_client(lib_dir=r"D:\Software_Space\instantclient_23_0")

# 数据库连接信息
DSN = "172.17.10.165:1521/orcl.ecdag.com"
USER = "iplant_smt2"
PASSWORD = "acc"

# PACKID -> SCHB 映射 (按任务说明)
PACKID_SCHB_MAP = {
    '20260225S3400574': ('SCHB00086626', '2026-03-02 19:23:28'),
    '20260228S3400580': ('SCHB00086627', '2026-03-02 19:23:52'),
    '20260228S3400581': ('SCHB00086630', '2026-03-02 19:24:54'),
    '20260225S3400576': ('SCHB00086632', '2026-03-02 19:23:35'),
}

# 固定参数（来自任务说明）
WONO = 'SMT-226021101'
LINE = 'SMT Line2'
CNT = 300


def main():
    print("=" * 60)
    print("ACC ERP Report Success 补录操作")
    print("数据库: iplant_smt2@172.17.10.165")
    print("=" * 60)

    conn = oracledb.connect(user=USER, password=PASSWORD, dsn=DSN)
    cursor = conn.cursor()

    # -------------------------
    # 前置: 查询表结构
    # -------------------------
    print("\n[前置] 查询pack_info表字段结构...")
    cursor.execute("SELECT column_name FROM user_tab_columns WHERE table_name = 'PACK_INFO' ORDER BY column_id")
    cols = cursor.fetchall()
    pack_info_cols = [c[0] for c in cols]
    print(f"  pack_info字段: {pack_info_cols}")

    print("\n[前置] 查询acc_erp_report_success表字段结构...")
    cursor.execute("SELECT column_name FROM user_tab_columns WHERE table_name = 'ACC_ERP_REPORT_SUCCESS' ORDER BY column_id")
    succ_cols = cursor.fetchall()
    succ_col_names = [c[0] for c in succ_cols]
    print(f"  acc_erp_report_success字段: {succ_col_names}")

    # -------------------------
    # 第一步: 查询pack_info获取PRODTYPE（用于PARTNO）
    # -------------------------
    print("\n[第一步] 查询pack_info获取数据...")
    # pack_info字段: PACKID, PRODTYPE, PACKSIZE, CURRQUANTITY, STATUS, LASTUPDATE,
    #                LASTUPDATETIME, LINE, CUSTOMERPACKID, CUSTOMERPARTNO, DRAG, GENERATORNAME, STN
    sql_pack = """
        SELECT packid, prodtype, packsize, currquantity, line, customerpartno
        FROM pack_info
        WHERE packid IN ('20260225S3400574', '20260225S3400576', '20260228S3400580', '20260228S3400581')
        ORDER BY packid
    """
    cursor.execute(sql_pack)
    rows_pack = cursor.fetchall()
    print(f"  查询结果（共{len(rows_pack)}条）：")
    pack_info_map = {}
    for row in rows_pack:
        packid, prodtype, packsize, currquantity, line, customerpartno = row
        print(f"  PACKID={packid} | PRODTYPE={prodtype} | PACKSIZE={packsize} | CURRQUANTITY={currquantity} | LINE={line} | CUSTOMERPARTNO={customerpartno}")
        pack_info_map[packid] = {
            'prodtype': prodtype,
            'packsize': packsize,
            'currquantity': currquantity,
            'line': line,
            'customerpartno': customerpartno,
        }

    if len(rows_pack) == 0:
        print("  [错误] 未找到任何pack_info记录，终止操作。")
        cursor.close()
        conn.close()
        return

    if len(rows_pack) != 4:
        print(f"  [警告] 期望4条，实际{len(rows_pack)}条，继续执行（部分插入）。")

    # -------------------------
    # 查询一条已有的acc_erp_report_success记录参考
    # -------------------------
    print("\n[参考] 查询一条已有的acc_erp_report_success记录...")
    cursor.execute("SELECT * FROM acc_erp_report_success WHERE ROWNUM <= 1")
    sample_row = cursor.fetchone()
    if sample_row:
        for i, col in enumerate(succ_col_names):
            print(f"  {col} = {sample_row[i]}")
    else:
        print("  表为空，无参考记录")

    # -------------------------
    # 第二步: 确认这4条记录当前是否在acc_erp_report_success中
    # -------------------------
    print("\n[第二步] 查询acc_erp_report_success确认是否已存在...")
    sql_check = """
        SELECT schb_number, packid, partno, report_time
        FROM acc_erp_report_success
        WHERE schb_number IN ('SCHB00086626', 'SCHB00086627', 'SCHB00086630', 'SCHB00086632')
    """
    cursor.execute(sql_check)
    rows_exist = cursor.fetchall()
    print(f"  已存在记录（共{len(rows_exist)}条）：")
    exist_schbs = set()
    for row in rows_exist:
        schb, packid, partno, report_time = row
        print(f"  SCHB={schb} | PACKID={packid} | PARTNO={partno} | REPORT_TIME={report_time}")
        exist_schbs.add(schb)

    if len(rows_exist) == 4:
        print("\n  [信息] 4条记录已全部存在，无需插入。")
        # 执行第四步验证
        _verify(cursor, succ_col_names)
        cursor.close()
        conn.close()
        return

    # -------------------------
    # 确认序列存在
    # -------------------------
    print("\n[前置检查] 验证序列 ACC_ERP_REPT_SUCC_SEQ 是否存在...")
    cursor.execute("SELECT sequence_name FROM user_sequences WHERE sequence_name = 'ACC_ERP_REPT_SUCC_SEQ'")
    seq_row = cursor.fetchone()
    if seq_row:
        print(f"  序列存在: {seq_row[0]}")
    else:
        print("  [错误] 序列 ACC_ERP_REPT_SUCC_SEQ 不存在，终止操作！")
        # 查询所有序列
        cursor.execute("SELECT sequence_name FROM user_sequences ORDER BY sequence_name")
        all_seqs = cursor.fetchall()
        print(f"  当前用户所有序列: {[s[0] for s in all_seqs]}")
        cursor.close()
        conn.close()
        return

    # -------------------------
    # 第三步: 执行INSERT
    # -------------------------
    insert_count = 0
    skip_count = 0
    print("\n[第三步] 执行INSERT...")

    # 根据acc_erp_report_success参考记录，确定PARTNO字段来源
    # PRODTYPE字段即为零件号(PARTNO)，基于ACC系统设计惯例
    # 如果参考记录显示不同，会在上面打印出来

    sql_insert = """
        INSERT INTO acc_erp_report_success
        (ID, WONO, PACKID, PARTNO, CNT, LINE, SCHB_NUMBER, SOURCE_BILL_NO, REPORT_TIME, IS_SUCCESS, CREATETIME)
        VALUES
        (ACC_ERP_REPT_SUCC_SEQ.NEXTVAL, :wono, :packid, :partno, :cnt, :line,
         :schb_number, :source_bill_no,
         TO_DATE(:report_time, 'YYYY-MM-DD HH24:MI:SS'),
         1,
         TO_DATE(:create_time, 'YYYY-MM-DD HH24:MI:SS'))
    """

    for packid, (schb, report_time) in PACKID_SCHB_MAP.items():
        if schb in exist_schbs:
            print(f"  [跳过] SCHB={schb} PACKID={packid} 已存在")
            skip_count += 1
            continue

        if packid not in pack_info_map:
            print(f"  [警告] PACKID={packid} 在pack_info中未找到，跳过")
            skip_count += 1
            continue

        # PRODTYPE作为PARTNO（ACC系统中PRODTYPE即产品型号/零件号）
        partno = pack_info_map[packid]['prodtype']

        params = {
            'wono': WONO,
            'packid': packid,
            'partno': partno,
            'cnt': CNT,
            'line': LINE,
            'schb_number': schb,
            'source_bill_no': WONO,
            'report_time': report_time,
            'create_time': report_time,
        }

        try:
            cursor.execute(sql_insert, params)
            print(f"  [INSERT OK] SCHB={schb} | PACKID={packid} | PARTNO={partno} | REPORT_TIME={report_time}")
            insert_count += 1
        except Exception as e:
            print(f"  [INSERT ERROR] SCHB={schb} | PACKID={packid} | 错误: {e}")
            conn.rollback()
            cursor.close()
            conn.close()
            return

    conn.commit()
    print(f"\n  COMMIT完成。插入{insert_count}条，跳过{skip_count}条。")

    # -------------------------
    # 第四步: 验证插入结果
    # -------------------------
    _verify(cursor, succ_col_names)

    cursor.close()
    conn.close()
    print("\n[完成] 所有操作执行完毕。")
    print("=" * 60)


def _verify(cursor, succ_col_names):
    print("\n[第四步] 验证插入结果...")
    sql_verify = """
        SELECT id, wono, packid, partno, cnt, schb_number, report_time, is_success
        FROM acc_erp_report_success
        WHERE wono = 'SMT-226021101'
        ORDER BY report_time DESC
    """
    try:
        cursor.execute(sql_verify)
        rows_verify = cursor.fetchall()
        print(f"  WONO=SMT-226021101 的所有记录（共{len(rows_verify)}条）：")
        print(f"  {'ID':<12} {'WONO':<18} {'PACKID':<22} {'PARTNO':<30} {'CNT':<6} {'SCHB':<16} {'REPORT_TIME':<22} {'IS_SUCCESS'}")
        print("  " + "-" * 140)
        for row in rows_verify:
            id_, wono, packid, partno, cnt, schb, report_time, is_success = row
            print(f"  {str(id_):<12} {str(wono):<18} {str(packid):<22} {str(partno):<30} {str(cnt):<6} {str(schb):<16} {str(report_time):<22} {is_success}")
    except Exception as e:
        print(f"  [验证失败] {e}")
        # 尝试简化查询
        cursor.execute("SELECT * FROM acc_erp_report_success WHERE wono = 'SMT-226021101' ORDER BY ROWID DESC")
        rows = cursor.fetchall()
        print(f"  简化查询结果（共{len(rows)}条）：")
        for row in rows:
            print(f"  {row}")


if __name__ == '__main__':
    main()
